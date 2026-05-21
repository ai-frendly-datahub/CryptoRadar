from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Article, CategoryConfig, Source


TRACKED_EVENT_MODEL_ORDER = [
    "exchange_listing_notice",
    "regulatory_action",
    "onchain_metric",
    "liquidity_snapshot",
]
TRACKED_EVENT_MODELS = set(TRACKED_EVENT_MODEL_ORDER)
GENERIC_EXCHANGE_TERMS = {
    "exchange",
    "거래소",
    "listing",
    "listed",
    "delisting",
    "상장",
    "상폐",
    "거래지원",
}
REGULATORY_ACTION_TERMS = (
    "approval",
    "approved",
    "approve",
    "reject",
    "rejected",
    "lawsuit",
    "suit",
    "charge",
    "charged",
    "settlement",
    "settled",
    "fine",
    "fined",
    "penalty",
    "sanction",
    "enforcement",
    "investigation",
    "probe",
    "license",
    "licence",
    "rule",
    "bill",
    "law",
    "act",
    "policy",
    "guidance",
    "ban",
    "승인",
    "거부",
    "제소",
    "소송",
    "기소",
    "합의",
    "벌금",
    "과징금",
    "제재",
    "집행",
    "조사",
    "허가",
    "라이선스",
    "법안",
    "법률",
    "규정",
    "정책",
    "가이드라인",
    "금지",
)
METRIC_VALUE_RE = re.compile(
    r"[$₩€£]?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(t|tn|trillion|b|bn|billion|m|mn|million|k|thousand|%|percent)?",
    re.I,
)
METRIC_SIGNAL_RE = re.compile(r"\b(tvl|liquidity|volume|hashrate|dominance)\b", re.I)


def build_quality_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    errors: Iterable[str] | None = None,
    quality_config: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = _as_utc(generated_at or datetime.now(UTC))
    articles_list = list(articles)
    errors_list = [str(error) for error in (errors or [])]
    quality = _dict(quality_config or {}, "data_quality")
    freshness_sla = _dict(quality, "freshness_sla")
    event_model_config = _dict(quality, "event_models")
    tracked_event_models = _tracked_event_models(quality)

    events = _build_event_rows(
        articles=articles_list,
        sources=category.sources,
        tracked_event_models=tracked_event_models,
        event_model_config=event_model_config,
    )
    source_rows = [
        _build_source_row(
            source=source,
            articles=articles_list,
            event_rows=events,
            errors=errors_list,
            freshness_sla=freshness_sla,
            tracked_event_models=tracked_event_models,
            generated_at=generated,
        )
        for source in category.sources
    ]

    status_counts = Counter(str(row["status"]) for row in source_rows)
    event_counts = Counter(str(row["event_model"]) for row in events)
    configured_event_counts = Counter(
        event_model
        for event_model in (_source_event_model(source) for source in category.sources)
        if event_model in tracked_event_models
    )
    unconfigured_event_models = [
        event_model
        for event_model in TRACKED_EVENT_MODEL_ORDER
        if event_model in tracked_event_models and configured_event_counts.get(event_model, 0) == 0
    ]
    summary = {
        "total_sources": len(source_rows),
        "enabled_sources": sum(1 for row in source_rows if row["enabled"]),
        "tracked_sources": sum(1 for row in source_rows if row["tracked"]),
        "fresh_sources": status_counts.get("fresh", 0),
        "stale_sources": status_counts.get("stale", 0),
        "missing_sources": status_counts.get("missing", 0),
        "missing_event_sources": status_counts.get("missing_event", 0),
        "unknown_event_date_sources": status_counts.get("unknown_event_date", 0),
        "not_tracked_sources": status_counts.get("not_tracked", 0),
        "skipped_disabled_sources": status_counts.get("skipped_disabled", 0),
        "collection_error_count": len(errors_list),
        "unconfigured_tracked_event_models": unconfigured_event_models,
    }
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        summary[f"{event_model}_configured_sources"] = configured_event_counts.get(event_model, 0)
        summary[f"{event_model}_events"] = event_counts.get(event_model, 0)
    summary.update(
        _event_quality_summary(
            events=events,
            source_rows=source_rows,
            quality_config=quality_config or {},
            tracked_event_models=tracked_event_models,
        )
    )
    daily_review_items = _daily_review_items(
        events=events,
        source_rows=source_rows,
        quality_config=quality_config or {},
        tracked_event_models=tracked_event_models,
    )
    summary["daily_review_item_count"] = len(daily_review_items)

    return {
        "category": category.category_name,
        "generated_at": generated.isoformat(),
        "scoped_article_count": len(articles_list),
        "event_count": len(events),
        "scope_note": (
            "CryptoRadar keeps news and market sentiment separate from official exchange "
            "listing notices, regulator actions, on-chain metrics, and liquidity snapshots. "
            "Article-level signals are proxies until canonical exchange, asset-pair, "
            "chain, and metric fields are collected from operational sources."
        ),
        "summary": summary,
        "sources": source_rows,
        "events": events,
        "daily_review_items": daily_review_items,
        "source_backlog": (quality_config or {}).get("source_backlog", {}),
        "errors": errors_list,
    }


def write_quality_report(
    report: Mapping[str, object],
    *,
    output_dir: Path,
    category_name: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_datetime(str(report.get("generated_at") or "")) or datetime.now(UTC)
    date_stamp = _as_utc(generated_at).strftime("%Y%m%d")
    latest_path = output_dir / f"{category_name}_quality.json"
    dated_path = output_dir / f"{category_name}_{date_stamp}_quality.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    latest_path.write_text(encoded + "\n", encoding="utf-8")
    dated_path.write_text(encoded + "\n", encoding="utf-8")
    return {"latest": latest_path, "dated": dated_path}


def _build_event_rows(
    *,
    articles: list[Article],
    sources: list[Source],
    tracked_event_models: set[str],
    event_model_config: Mapping[str, object],
) -> list[dict[str, Any]]:
    source_map = {source.name: source for source in sources}
    rows: list[dict[str, Any]] = []
    for article in articles:
        source = source_map.get(article.source)
        if source is None:
            continue
        for event_model in _article_event_models(article, source, tracked_event_models):
            event_at = _event_datetime(article)
            row: dict[str, Any] = {
                "source": source.name,
                "source_type": source.type,
                "trust_tier": source.trust_tier,
                "content_type": source.content_type,
                "collection_tier": source.collection_tier,
                "producer_role": source.producer_role,
                "info_purpose": source.info_purpose,
                "event_model": event_model,
                "title": article.title,
                "url": article.link,
                "source_url": article.link or source.url,
                "event_at": event_at.isoformat() if event_at else None,
                "cryptocurrency": _matches(article, "Cryptocurrency"),
                "exchange": _matches(article, "Exchange"),
                "regulation": _matches(article, "Regulation"),
                "technology": _matches(article, "Technology"),
                "market": _matches(article, "Market"),
                "crypto_general": _matches(article, "CryptoGeneral"),
                "asset_symbol": _asset_symbol(article),
                "project_id": _project_id(article),
                "regulator": _regulator(article),
                "jurisdiction": _jurisdiction(article),
                "chain": _chain(article),
                "metric_name": _metric_name(article),
                "metric_value": _metric_value(article),
                "asset_pair": _asset_pair(article),
                "liquidity_metric": _liquidity_metric(article),
            }
            canonical_key, canonical_key_status = _canonical_key(row)
            row["canonical_key"] = canonical_key
            row["canonical_key_status"] = canonical_key_status
            row["event_key"] = _event_key(row, event_at)
            row["required_field_proxy"] = _required_field_proxy(
                row, source, event_model, event_model_config
            )
            row["required_field_gaps"] = _required_field_gaps(
                row, source, event_model, event_model_config
            )
            rows.append(row)
    return rows


def _build_source_row(
    *,
    source: Source,
    articles: list[Article],
    event_rows: list[dict[str, Any]],
    errors: list[str],
    freshness_sla: Mapping[str, object],
    tracked_event_models: set[str],
    generated_at: datetime,
) -> dict[str, Any]:
    source_articles = [article for article in articles if article.source == source.name]
    source_errors = [error for error in errors if error.startswith(f"{source.name}:")]
    event_model = _source_event_model(source)
    if not source.enabled:
        source_articles = []
    source_event_rows = [
        row
        for row in event_rows
        if source.enabled and row["source"] == source.name and row["event_model"] == event_model
    ]
    latest_event = _latest_event(source_event_rows)
    latest_event_at = (
        _parse_datetime(str(latest_event.get("event_at") or "")) if latest_event else None
    )
    sla_days = _source_sla_days(source, event_model, freshness_sla)
    age_days = _age_days(generated_at, latest_event_at) if latest_event_at else None
    status = _source_status(
        source=source,
        event_model=event_model,
        tracked_event_models=tracked_event_models,
        article_count=len(source_articles),
        event_count=len(source_event_rows),
        latest_event_at=latest_event_at,
        sla_days=sla_days,
        age_days=age_days,
    )

    return {
        "source": source.name,
        "source_type": source.type,
        "enabled": source.enabled,
        "trust_tier": source.trust_tier,
        "content_type": source.content_type,
        "collection_tier": source.collection_tier,
        "producer_role": source.producer_role,
        "info_purpose": source.info_purpose,
        "tracked": event_model in tracked_event_models,
        "event_model": event_model,
        "freshness_sla_days": sla_days,
        "status": status,
        "article_count": len(source_articles),
        "event_count": len(source_event_rows),
        "latest_event_at": latest_event_at.isoformat() if latest_event_at else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "latest_title": str(latest_event.get("title", "")) if latest_event else "",
        "latest_url": str(latest_event.get("url", "")) if latest_event else "",
        "latest_cryptocurrency": latest_event.get("cryptocurrency", []) if latest_event else [],
        "latest_exchange": latest_event.get("exchange", []) if latest_event else [],
        "latest_regulation": latest_event.get("regulation", []) if latest_event else [],
        "latest_required_field_proxy": (
            latest_event.get("required_field_proxy", {}) if latest_event else {}
        ),
        "errors": source_errors,
    }


def _article_event_models(
    article: Article,
    source: Source,
    tracked_event_models: set[str],
) -> list[str]:
    values: set[str] = set()
    source_event_model = _source_event_model(source)
    if source_event_model in tracked_event_models:
        values.add(source_event_model)
    if _has_regulatory_action_signal(article):
        values.add("regulatory_action")
    if _has_exchange_listing_notice_signal(article):
        values.add("exchange_listing_notice")
    return [event_model for event_model in TRACKED_EVENT_MODEL_ORDER if event_model in values]


def _source_status(
    *,
    source: Source,
    event_model: str,
    tracked_event_models: set[str],
    article_count: int,
    event_count: int,
    latest_event_at: datetime | None,
    sla_days: float | None,
    age_days: float | None,
) -> str:
    if not source.enabled:
        return "skipped_disabled"
    if event_model not in tracked_event_models:
        return "not_tracked"
    if article_count == 0:
        return "missing"
    if event_count == 0:
        return "missing_event"
    if latest_event_at is None or age_days is None:
        return "unknown_event_date"
    if sla_days is not None and age_days > sla_days:
        return "stale"
    return "fresh"


def _tracked_event_models(quality: Mapping[str, object]) -> set[str]:
    outputs = _dict(quality, "quality_outputs")
    raw = outputs.get("tracked_event_models")
    if isinstance(raw, list):
        values = {str(item).strip() for item in raw if str(item).strip()}
        return values & TRACKED_EVENT_MODELS or set(TRACKED_EVENT_MODELS)
    return set(TRACKED_EVENT_MODELS)


def _source_event_model(source: Source) -> str:
    raw = source.config.get("event_model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    content_type = source.content_type.lower()
    source_name = source.name.lower()
    if content_type in {"crypto_liquidity", "crypto_market", "liquidity_snapshot"}:
        return "liquidity_snapshot"
    if content_type in {"onchain", "onchain_metric"}:
        return "onchain_metric"
    if content_type == "analysis" and "glassnode" in source_name:
        return "onchain_metric"
    if content_type in {"regulation", "regulatory_action"}:
        return "regulatory_action"
    if content_type in {"exchange_listing_notice", "listing"}:
        return "exchange_listing_notice"
    return ""


def _source_sla_days(
    source: Source,
    event_model: str,
    freshness_sla: Mapping[str, object],
) -> float | None:
    raw_source_sla = source.config.get("freshness_sla_days")
    parsed_source_sla = _as_float(raw_source_sla)
    if parsed_source_sla is not None:
        return parsed_source_sla

    hours = _as_float(freshness_sla.get(f"{event_model}_hours"))
    if hours is not None:
        return hours / 24
    days = _as_float(freshness_sla.get(f"{event_model}_days"))
    if days is not None:
        return days
    return None


def _latest_event(event_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for row in event_rows:
        event_at = _parse_datetime(str(row.get("event_at") or ""))
        if event_at is not None:
            dated.append((event_at, row))
        else:
            undated.append(row)
    if dated:
        return max(dated, key=lambda item: item[0])[1]
    return undated[0] if undated else None


def _event_datetime(article: Article) -> datetime | None:
    article_time = article.published or article.collected_at
    return _as_utc(article_time) if article_time else None


def _event_quality_summary(
    *,
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_event_models: set[str],
) -> dict[str, int]:
    event_counts = Counter(str(row.get("event_model") or "") for row in events)
    return {
        "crypto_signal_event_count": sum(
            event_counts.get(model, 0) for model in tracked_event_models
        ),
        "official_or_operational_event_count": sum(
            1
            for row in events
            if str(row.get("trust_tier") or "").startswith("T1_")
            or str(row.get("source_type") or "").lower() in {"api", "mcp"}
        ),
        "news_proxy_event_count": sum(
            1 for row in events if str(row.get("content_type") or "").lower() == "news"
        ),
        "complete_canonical_key_count": sum(
            1 for row in events if row.get("canonical_key_status") == "complete"
        ),
        "proxy_canonical_key_count": sum(
            1 for row in events if str(row.get("canonical_key_status") or "").endswith("_proxy")
        ),
        "missing_canonical_key_count": sum(1 for row in events if not row.get("canonical_key")),
        "asset_symbol_present_count": sum(1 for row in events if row.get("asset_symbol")),
        "exchange_present_count": sum(1 for row in events if row.get("exchange")),
        "regulator_present_count": sum(1 for row in events if row.get("regulator")),
        "metric_name_present_count": sum(1 for row in events if row.get("metric_name")),
        "metric_value_present_count": sum(1 for row in events if row.get("metric_value") is not None),
        "event_required_field_gap_count": sum(
            len(row.get("required_field_gaps") or []) for row in events
        ),
        "tracked_source_gap_count": sum(
            1
            for row in source_rows
            if row.get("tracked")
            and row.get("status") in {"missing", "missing_event", "unknown_event_date", "stale"}
        ),
        "missing_event_model_count": sum(
            1 for model in tracked_event_models if event_counts.get(model, 0) == 0
        ),
        "source_backlog_candidate_count": len(_source_backlog_items(quality_config)),
    }


def _daily_review_items(
    *,
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_event_models: set[str],
) -> list[dict[str, Any]]:
    review: list[dict[str, Any]] = []
    for row in events:
        gaps = [str(value) for value in row.get("required_field_gaps") or []]
        if gaps:
            review.append(
                {
                    "reason": "missing_required_fields",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "canonical_key": row.get("canonical_key"),
                    "required_field_gaps": gaps,
                }
            )
        if str(row.get("canonical_key_status") or "").endswith("_proxy"):
            review.append(
                {
                    "reason": "proxy_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "canonical_key_status": row.get("canonical_key_status"),
                }
            )
    for source in source_rows:
        if source.get("tracked") and source.get("status") in {
            "missing",
            "missing_event",
            "unknown_event_date",
            "stale",
        }:
            review.append(
                {
                    "reason": f"source_{source.get('status')}",
                    "source": source.get("source"),
                    "event_model": source.get("event_model"),
                    "age_days": source.get("age_days"),
                }
            )
    event_counts = Counter(str(row.get("event_model") or "") for row in events)
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        if event_model in tracked_event_models and event_counts.get(event_model, 0) == 0:
            review.append({"reason": "missing_event_model", "event_model": event_model})
    for item in _source_backlog_items(quality_config):
        review.append(
            {
                "reason": "source_backlog_pending",
                "source": item.get("name") or item.get("id"),
                "signal_type": item.get("signal_type"),
                "activation_gate": item.get("activation_gate"),
            }
        )
    return review[:50]


def _source_backlog_items(quality_config: Mapping[str, object]) -> list[Mapping[str, object]]:
    backlog = _dict(quality_config, "source_backlog")
    candidates = backlog.get("operational_candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, Mapping)]


def _required_field_proxy(
    row: Mapping[str, Any],
    source: Source,
    event_model: str,
    event_model_config: Mapping[str, object],
) -> dict[str, bool]:
    event_config = _dict(event_model_config, event_model)
    raw_fields = event_config.get("required_fields")
    if not isinstance(raw_fields, list):
        raw_fields = _default_required_fields(event_model)
    proxy = {str(field): _field_present(row, str(field)) for field in raw_fields if str(field).strip()}
    if event_model == "liquidity_snapshot" and not proxy.get("exchange"):
        proxy["exchange"] = bool(source.content_type == "price")
    return proxy


def _required_field_gaps(
    row: Mapping[str, Any],
    source: Source,
    event_model: str,
    event_model_config: Mapping[str, object],
) -> list[str]:
    return [
        field
        for field, present in _required_field_proxy(row, source, event_model, event_model_config).items()
        if not present
    ]


def _default_required_fields(event_model: str) -> list[str]:
    if event_model == "exchange_listing_notice":
        return ["exchange", "asset_symbol", "project_id", "source_url"]
    if event_model == "regulatory_action":
        return ["regulator", "jurisdiction", "project_id", "source_url"]
    if event_model == "onchain_metric":
        return ["chain", "metric_name", "metric_value"]
    if event_model == "liquidity_snapshot":
        return ["exchange", "asset_pair", "liquidity_metric"]
    return ["source_url"]


def _field_present(row: Mapping[str, Any], field: str) -> bool:
    aliases = {
        "exchange": ("exchange",),
        "asset_symbol": ("asset_symbol", "cryptocurrency"),
        "project_id": ("project_id", "cryptocurrency", "crypto_general"),
        "source_url": ("source_url", "url"),
        "regulator": ("regulator", "regulation"),
        "jurisdiction": ("jurisdiction",),
        "chain": ("chain", "technology", "cryptocurrency"),
        "metric_name": ("metric_name", "market", "technology"),
        "metric_value": ("metric_value",),
        "asset_pair": ("asset_pair", "asset_symbol"),
        "liquidity_metric": ("liquidity_metric", "market"),
    }
    for alias in aliases.get(field.lower(), (field.lower(),)):
        value = row.get(alias)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return True
    return False


def _canonical_key(row: Mapping[str, Any]) -> tuple[str, str]:
    event_model = str(row.get("event_model") or "")
    project_id = _slug(row.get("project_id") or "")
    chain = _slug(row.get("chain") or "")
    cryptocurrency = row.get("cryptocurrency")
    exchanges = row.get("exchange")
    asset = _slug(
        row.get("asset_symbol")
        or _first(cryptocurrency if isinstance(cryptocurrency, list) else [])
    )
    exchange = _slug(_first(exchanges if isinstance(exchanges, list) else []))
    asset_pair = _slug(row.get("asset_pair") or "")
    regulator = _slug(row.get("regulator") or "")
    jurisdiction = _slug(row.get("jurisdiction") or "")
    metric_name = _slug(row.get("metric_name") or "")
    source = _slug(row.get("source") or "")
    title = _slug(row.get("title") or "")

    if project_id:
        return f"crypto_project:{project_id}", "complete"
    if chain and asset:
        return f"crypto_project:{chain}:{asset}", "complete"
    if event_model == "exchange_listing_notice":
        if exchange and asset:
            return f"exchange_listing:{exchange}:{asset}", "complete"
        if asset:
            return f"crypto_asset:{asset}", "asset_proxy"
    if event_model == "regulatory_action":
        if regulator and jurisdiction and asset:
            return f"reg_action:{regulator}:{jurisdiction}:{asset}", "complete"
        if regulator and jurisdiction:
            return f"reg_action:{regulator}:{jurisdiction}", "regulator_proxy"
    if event_model == "onchain_metric" and metric_name:
        return f"onchain_metric:{chain or source}:{metric_name}:{asset or 'market'}", "metric_proxy"
    if event_model == "liquidity_snapshot":
        if exchange and asset_pair:
            return f"liquidity:{exchange}:{asset_pair}", "complete"
        if exchange and asset:
            return f"liquidity:{exchange}:{asset}", "asset_proxy"
    if source and title:
        return f"crypto_source:{source}:{_digest(title)}", "source_proxy"
    return "", "missing"


def _event_key(row: Mapping[str, Any], event_at: datetime | None) -> str:
    observed = _as_utc(event_at).strftime("%Y%m%d%H") if event_at else "undated"
    basis = row.get("canonical_key") or row.get("source_url") or row.get("title") or ""
    return f"{row.get('event_model')}:{_digest(basis)}:{observed}"


def _asset_symbol(article: Article) -> str:
    return _first(_matches(article, "Cryptocurrency") or _matches(article, "CryptoGeneral"))


def _project_id(article: Article) -> str:
    match = re.search(r"\bproject[_-]?id\s*[:=]\s*([A-Za-z0-9_-]+)", _article_text(article), re.I)
    return _slug(match.group(1)) if match else _slug(_asset_symbol(article))


def _regulator(article: Article) -> str:
    return _first(_matches(article, "Regulation"))


def _jurisdiction(article: Article) -> str:
    text = _article_text(article).lower()
    for token in ("sec", "cftc", "us", "eu", "uk", "korea", "japan", "singapore"):
        if token in text:
            return token.upper()
    return ""


def _chain(article: Article) -> str:
    return _first(_matches(article, "Technology") or _matches(article, "Cryptocurrency"))


def _metric_name(article: Article) -> str:
    text = _article_text(article).lower()
    for token in ("tvl", "liquidity", "volume", "hashrate", "dominance"):
        if token in text:
            return token
    return _first(_matches(article, "Market") or _matches(article, "Technology"))


def _metric_value(article: Article) -> float | None:
    text = _article_text(article)
    direct_match = re.search(
        r"(?:tvl|liquidity|volume|hashrate|dominance)\s*[:=]?\s*"
        r"[$₩€£]?\s*(\d[\d,]*(?:\.\d+)?)\s*"
        r"(t|tn|trillion|b|bn|billion|m|mn|million|k|thousand|%|percent)?",
        text,
        re.I,
    )
    if direct_match:
        return _scaled_metric_number(direct_match.group(1), direct_match.group(2))
    if not _has_metric_signal(article):
        return None
    for match in METRIC_VALUE_RE.finditer(text):
        window_start = max(0, match.start() - 48)
        window_end = min(len(text), match.end() + 48)
        if METRIC_SIGNAL_RE.search(text[window_start:window_end]):
            return _scaled_metric_number(match.group(1), match.group(2))
    return None


def _asset_pair(article: Article) -> str:
    match = re.search(r"\b([A-Z0-9]{2,10})/(USDT|USD|BTC|ETH|KRW)\b", _article_text(article))
    return match.group(0) if match else _asset_symbol(article)


def _liquidity_metric(article: Article) -> str:
    return _metric_name(article)


def _article_text(article: Article) -> str:
    return f"{article.title} {article.summary} {article.link}"


def _has_listing_signal(article: Article) -> bool:
    haystack = f"{article.title}\n{article.summary}".lower()
    return any(
        token in haystack
        for token in ("listing", "delisting", "listed", "상장", "상폐", "거래지원")
    )


def _has_exchange_listing_notice_signal(article: Article) -> bool:
    if not _has_listing_signal(article):
        return False
    exchange_matches = {value.casefold() for value in _matches(article, "Exchange")}
    if any(value not in GENERIC_EXCHANGE_TERMS for value in exchange_matches):
        return True
    haystack = f"{article.title}\n{article.summary}".casefold()
    if "public listing" in haystack or "ipo" in haystack or "stock listing" in haystack:
        return False
    return bool(exchange_matches and _matches(article, "Cryptocurrency"))


def _has_regulatory_action_signal(article: Article) -> bool:
    if not _matches(article, "Regulation"):
        return False
    haystack = f"{article.title}\n{article.summary}".casefold()
    for token in REGULATORY_ACTION_TERMS:
        normalized = token.casefold()
        if normalized.isascii() and normalized.replace(" ", "").isalpha():
            if re.search(rf"\b{re.escape(normalized)}\b", haystack):
                return True
        elif normalized in haystack:
            return True
    return False


def _has_metric_signal(article: Article) -> bool:
    haystack = f"{article.title}\n{article.summary}".lower()
    return any(
        token in haystack
        for token in (
            "tvl",
            "liquidity",
            "유동성",
            "volume",
            "거래량",
            "hashrate",
            "해시레이트",
            "dominance",
            "도미넌스",
        )
    )


def _scaled_metric_number(raw_number: str, raw_unit: str | None) -> float:
    value = float(raw_number.replace(",", ""))
    unit = (raw_unit or "").casefold()
    multipliers = {
        "k": 1_000,
        "thousand": 1_000,
        "m": 1_000_000,
        "mn": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "bn": 1_000_000_000,
        "billion": 1_000_000_000,
        "t": 1_000_000_000_000,
        "tn": 1_000_000_000_000,
        "trillion": 1_000_000_000_000,
    }
    return value * multipliers.get(unit, 1)


def _has_jurisdiction_signal(article: Article) -> bool:
    haystack = f"{article.title}\n{article.summary}".lower()
    return any(
        token in haystack
        for token in ("sec", "cftc", "미국", "금융위", "금융위원회", "eu", "홍콩", "싱가포르")
    )


def _matches(article: Article, entity_name: str) -> list[str]:
    values = article.matched_entities.get(entity_name, [])
    return [str(value) for value in values]


def _first(values: list[str]) -> str:
    return values[0] if values else ""


def _dict(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    raw = value.get(key)
    if isinstance(raw, Mapping):
        return {str(k): v for k, v in raw.items()}
    return {}


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _age_days(generated_at: datetime, event_at: datetime) -> float:
    return max(0.0, (_as_utc(generated_at) - _as_utc(event_at)).total_seconds() / 86400)


def _slug(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9가-힣]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:120]


def _digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
