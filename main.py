from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from radar_core.config_loader import filter_sources
from radar_core.date_storage import apply_date_storage_policy
from radar_core.ontology import annotate_articles_with_ontology
from radar_core.raw_logger import RawLogger

from cryptoradar.analyzer import apply_entity_rules
from cryptoradar.collector import article_matches_source_scope, collect_sources
from cryptoradar.config_loader import (
    load_category_config,
    load_category_quality_config,
    load_settings,
)
from cryptoradar.logger import configure_logging, get_logger
from cryptoradar.models import Article, Source
from cryptoradar.quality_report import build_quality_report, write_quality_report
from cryptoradar.reporter import generate_index_html, generate_report
from cryptoradar.storage import RadarStorage


logger = get_logger(__name__)


def run(
    *,
    category: str,
    config_path: Path | None = None,
    categories_dir: Path | None = None,
    per_source_limit: int = 30,
    recent_days: int = 7,
    timeout: int = 15,
    keep_days: int = 90,
    keep_raw_days: int = 180,
    keep_report_days: int = 90,
    snapshot_db: bool = False,
    max_sources: int | None = None,
    exclude_sources: tuple[str, ...] | list[str] = (),
) -> Path:
    """Execute the lightweight collect -> analyze -> report pipeline."""
    configure_logging()
    cycle_start = datetime.now(UTC)
    settings = load_settings(config_path)
    raw_data_dir = getattr(settings, "raw_data_dir", settings.database_path.parent / "raw")
    category_cfg = load_category_config(category, categories_dir=categories_dir)
    quality_config = load_category_quality_config(category, categories_dir=categories_dir)

    effective_sources = filter_sources(
        category_cfg.sources,
        max_sources=max_sources,
        exclude_sources=tuple(exclude_sources or ()),
    )
    enabled_effective_sources = [source for source in effective_sources if source.enabled]

    logger.info(
        "pipeline_start",
        category=category_cfg.category_name,
        sources_count=len(enabled_effective_sources),
        configured_sources_count=len(effective_sources),
    )
    collected, errors = collect_sources(
        effective_sources,
        category=category_cfg.category_name,
        limit_per_source=per_source_limit,
        timeout=timeout,
    )
    collected = annotate_articles_with_ontology(
        collected,
        repo_name="CryptoRadar",
        sources_by_name={source.name: source for source in effective_sources},
        category_name=category_cfg.category_name,
        search_from=Path(__file__),
        attach_event_model_payload=True,
    )

    raw_logger = RawLogger(raw_data_dir)
    for source in effective_sources:
        source_articles = [article for article in collected if article.source == source.name]
        if source_articles:
            _ = raw_logger.log(source_articles, source_name=source.name)

    analyzed = apply_entity_rules(collected, category_cfg.entities)

    storage = RadarStorage(settings.database_path)
    storage.upsert_articles(analyzed)
    _ = storage.delete_older_than(keep_days)

    recent_articles = _filter_report_articles(
        storage.recent_articles(category_cfg.category_name, days=recent_days),
        effective_sources,
    )
    recent_articles = [a for a in recent_articles if a.matched_entities]
    quality_articles = _filter_report_articles(
        storage.recent_articles_by_collected_at(
            category_cfg.category_name,
            days=max(recent_days, 14),
            limit=max(500, per_source_limit * max(len(effective_sources), 1) * 2),
        ),
        effective_sources,
    )
    storage.close()

    matched_count = sum(1 for a in collected if a.matched_entities)
    logger.info(
        "collection_complete",
        collected_count=len(collected),
        errors_count=len(errors),
    )
    logger.info("analysis_complete", matched_count=matched_count)

    stats = {
        "sources": len(enabled_effective_sources),
        "collected": len(collected),
        "matched": matched_count,
        "window_days": recent_days,
    }

    quality_report = build_quality_report(
        category=category_cfg,
        articles=quality_articles,
        errors=errors,
        quality_config=quality_config,
        generated_at=cycle_start,
    )
    output_path = settings.report_dir / f"{category_cfg.category_name}_report.html"
    _ = generate_report(
        category=category_cfg,
        articles=recent_articles,
        output_path=output_path,
        stats=stats,
        errors=errors,
        quality_report=quality_report,
    )
    logger.info("report_generated", output_path=str(output_path))
    quality_paths = write_quality_report(
        quality_report,
        output_dir=settings.report_dir,
        category_name=category_cfg.category_name,
    )
    logger.info("quality_report_generated", output_path=str(quality_paths["latest"]))
    generate_index_html(settings.report_dir)
    if errors:
        logger.warning("collection_errors", errors_count=len(errors))

    date_storage = apply_date_storage_policy(
        database_path=settings.database_path,
        raw_data_dir=raw_data_dir,
        report_dir=settings.report_dir,
        keep_raw_days=keep_raw_days,
        keep_report_days=keep_report_days,
        snapshot_db=snapshot_db,
    )
    snapshot_path = date_storage.get("snapshot_path")
    if isinstance(snapshot_path, str) and snapshot_path:
        print(f"[Radar] Snapshot saved at {snapshot_path}")

    return output_path


def _filter_report_articles(
    articles: list[Article],
    sources: list[Source],
) -> list[Article]:
    sources_by_name = {source.name: source for source in sources}
    scoped_articles: list[Article] = []
    for article in articles:
        source = sources_by_name.get(article.source)
        if source is None:
            scoped_articles.append(article)
            continue
        if not source.enabled:
            continue
        if article_matches_source_scope(
            source,
            article.title,
            article.summary,
            article.link,
        ):
            scoped_articles.append(article)
    return scoped_articles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CryptoRadar - Korean cryptocurrency news collector"
    )
    _ = parser.add_argument(
        "--category",
        required=True,
        help="Category name matching a YAML in config/categories/",
    )
    _ = parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config/config.yaml (optional)",
    )
    _ = parser.add_argument(
        "--categories-dir",
        type=Path,
        default=None,
        help="Custom directory for category YAML files",
    )
    _ = parser.add_argument(
        "--per-source-limit",
        type=int,
        default=30,
        help="Max items to pull from each source",
    )
    _ = parser.add_argument(
        "--recent-days", type=int, default=7, help="Window (days) to show in the report"
    )
    _ = parser.add_argument(
        "--timeout", type=int, default=15, help="HTTP timeout per request (seconds)"
    )
    _ = parser.add_argument(
        "--keep-days", type=int, default=90, help="Retention window for stored items"
    )
    _ = parser.add_argument(
        "--keep-raw-days", type=int, default=180, help="Retention window for raw JSONL directories"
    )
    _ = parser.add_argument(
        "--keep-report-days", type=int, default=90, help="Retention window for dated HTML reports"
    )
    _ = parser.add_argument(
        "--snapshot-db",
        action="store_true",
        default=False,
        help="Create a dated DuckDB snapshot after each run",
    )
    _ = parser.add_argument(
        "--max-sources",
        type=int,
        default=None,
        help="Hard cap on number of sources iterated (after --exclude-source). Default: no cap.",
    )
    _ = parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        metavar="ID_OR_NAME",
        help="Skip this source id or name. May be repeated.",
    )
    return parser.parse_args()


def _to_path(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    return None


def _to_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default




def _to_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _to_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in cast(list[object], value) if isinstance(item, str)]
    return []
if __name__ == "__main__":
    args = cast(dict[str, object], vars(parse_args()))
    _ = run(
        category=str(args.get("category", "")),
        config_path=_to_path(args.get("config")),
        categories_dir=_to_path(args.get("categories_dir")),
        per_source_limit=_to_int(args.get("per_source_limit"), 30),
        recent_days=_to_int(args.get("recent_days"), 7),
        timeout=_to_int(args.get("timeout"), 15),
        keep_days=_to_int(args.get("keep_days"), 90),
        keep_raw_days=_to_int(args.get("keep_raw_days"), 180),
        keep_report_days=_to_int(args.get("keep_report_days"), 90),
        snapshot_db=bool(args.get("snapshot_db", False)),
        max_sources=_to_optional_int(args.get("max_sources")),
        exclude_sources=_to_str_list(args.get("exclude_source")),
    )
