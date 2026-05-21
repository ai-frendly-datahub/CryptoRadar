#!/usr/bin/env python3
"""Run DuckDB checks and write CryptoRadar quality JSON."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import duckdb
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RADAR_CORE_ROOT = PROJECT_ROOT.parent / "radar-core"
if RADAR_CORE_ROOT.exists():
    sys.path.insert(0, str(RADAR_CORE_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from radar_core.common.quality_checks import (  # noqa: E402
    check_dates,
    check_duplicate_urls,
    check_missing_fields,
    check_text_lengths,
)

from cryptoradar.config_loader import (  # noqa: E402
    load_category_config,
    load_category_quality_config,
)
from cryptoradar.quality_report import build_quality_report, write_quality_report  # noqa: E402
from cryptoradar.storage import RadarStorage  # noqa: E402


CATEGORY_NAME = "crypto"


def _project_path(project_root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load((project_root / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _latest_article_date(db_path: Path, category_name: str) -> date | None:
    if not db_path.exists():
        return None
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT MAX(COALESCE(published, collected_at))
                FROM articles
                WHERE category = ?
                """,
                [category_name],
            ).fetchone()
    except duckdb.Error:
        return None
    if not row:
        return None
    return _coerce_date(row[0])


def _lookback_days(target_date: date | None, *, minimum_days: int = 14) -> int:
    if target_date is None:
        return minimum_days
    age_days = (datetime.now(UTC).date() - target_date).days + 1
    return max(minimum_days, age_days)


def generate_quality_artifacts(
    project_root: Path = PROJECT_ROOT,
    *,
    category_name: str = CATEGORY_NAME,
) -> tuple[dict[str, Path], dict[str, Any]]:
    runtime_config = _load_runtime_config(project_root)
    db_path = _project_path(
        project_root,
        str(runtime_config.get("database_path", "data/radar_data.duckdb")),
    )
    report_dir = _project_path(
        project_root,
        str(runtime_config.get("report_dir", "reports")),
    )
    categories_dir = project_root / "config" / "categories"
    category = load_category_config(category_name, categories_dir=categories_dir)
    quality_config = load_category_quality_config(category_name, categories_dir=categories_dir)
    lookback_days = _lookback_days(_latest_article_date(db_path, category.category_name))
    with duckdb.connect(str(db_path), read_only=True) as con:
        record_quality = _record_quality_summary(con)
    with RadarStorage(db_path) as storage:
        articles = cast(Any, storage).recent_articles_by_collected_at(
            category.category_name,
            days=lookback_days,
            limit=1500,
        )

    report = build_quality_report(
        category=category,
        articles=articles,
        errors=[],
        quality_config=quality_config,
    )
    report["record_quality"] = record_quality
    paths = write_quality_report(
        report,
        output_dir=report_dir,
        category_name=category.category_name,
    )
    return paths, report


def main() -> None:
    runtime_config = _load_runtime_config(PROJECT_ROOT)
    db_path = _project_path(
        PROJECT_ROOT,
        str(runtime_config.get("database_path", "data/radar_data.duckdb")),
    )
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        total = con.execute("SELECT COUNT(*) FROM articles").fetchone()
        print(f"Total records: {total[0] if total else 0}")
        check_missing_fields(
            con,
            table_name="articles",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "link": "link IS NULL OR link = ''",
                "summary": "summary IS NULL OR summary = ''",
                "published": "published IS NULL",
            },
        )
        check_duplicate_urls(con, table_name="articles", url_column="link")
        check_text_lengths(con, table_name="articles", text_columns=["title", "summary"])
        check_dates(con, table_name="articles", date_column="published")
        record_quality = _record_quality_summary(con)

    paths, report = generate_quality_artifacts(PROJECT_ROOT)
    summary = report["summary"]
    if isinstance(summary, dict):
        print(f"scoped_articles={report.get('scoped_article_count', 0)}")
        print(f"event_count={report.get('event_count', len(report.get('events', [])))}")
        print(f"quality_report={paths['latest']}")
        print(f"tracked_sources={summary.get('tracked_sources', 0)}")
        print(f"fresh_sources={summary.get('fresh_sources', 0)}")
        print(f"stale_sources={summary.get('stale_sources', 0)}")
        print(f"missing_sources={summary.get('missing_sources', 0)}")
        print(f"not_tracked_sources={summary.get('not_tracked_sources', 0)}")
        print(f"crypto_signal_event_count={summary.get('crypto_signal_event_count', 0)}")
        print(
            "summary_missing_ratio="
            f"{record_quality.get('missing_summary_ratio', 0.0)}"
        )


def _record_quality_summary(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN title IS NULL OR title = '' THEN 1 ELSE 0 END) AS missing_title_rows,
            SUM(CASE WHEN link IS NULL OR link = '' THEN 1 ELSE 0 END) AS missing_link_rows,
            SUM(CASE WHEN summary IS NULL OR summary = '' THEN 1 ELSE 0 END) AS missing_summary_rows,
            SUM(CASE WHEN published IS NULL THEN 1 ELSE 0 END) AS missing_published_rows,
            SUM(CASE WHEN published > CURRENT_TIMESTAMP THEN 1 ELSE 0 END) AS future_published_rows
        FROM articles
        """
    ).fetchone()
    (
        total_rows,
        missing_title_rows,
        missing_link_rows,
        missing_summary_rows,
        missing_published_rows,
        future_published_rows,
    ) = row or (0, 0, 0, 0, 0, 0)
    total = int(total_rows or 0)
    missing_summary = int(missing_summary_rows or 0)
    return {
        "total_rows": total,
        "missing_title_rows": int(missing_title_rows or 0),
        "missing_link_rows": int(missing_link_rows or 0),
        "missing_summary_rows": missing_summary,
        "missing_summary_ratio": round((missing_summary / total) * 100, 1) if total else 0.0,
        "missing_published_rows": int(missing_published_rows or 0),
        "future_published_rows": int(future_published_rows or 0),
        "summary_completeness_status": "needs_attention" if missing_summary else "ok",
    }


if __name__ == "__main__":
    main()
