from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptoradar.config_loader import load_category_config, load_category_quality_config
from cryptoradar.models import Article
from cryptoradar.quality_report import build_quality_report, write_quality_report


def test_quality_report_tracks_listing_and_regulatory_proxy_events() -> None:
    category = load_category_config("crypto")
    source = next(source for source in category.sources if source.name == "CoinDesk")
    now = datetime(2026, 4, 13, tzinfo=UTC)
    article = Article(
        title="Coinbase lists Bitcoin ETF token after SEC approval",
        link="https://example.com/coinbase-listing",
        summary="SEC approval and Coinbase listing coverage for a Bitcoin-related asset.",
        published=now - timedelta(hours=6),
        source=source.name,
        category=category.category_name,
        matched_entities={
            "Cryptocurrency": ["bitcoin"],
            "Exchange": ["coinbase", "listing"],
            "Regulation": ["SEC"],
            "CryptoGeneral": ["asset"],
        },
        collected_at=now - timedelta(hours=6),
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config("crypto"),
        generated_at=now,
    )

    summary = report["summary"]
    assert summary["exchange_listing_notice_events"] == 1
    assert summary["exchange_listing_notice_configured_sources"] == 0
    assert summary["regulatory_action_events"] == 1
    assert summary["onchain_metric_events"] == 0
    assert summary["onchain_metric_configured_sources"] == 1
    assert summary["liquidity_snapshot_events"] == 0
    assert summary["liquidity_snapshot_configured_sources"] == 0
    assert "liquidity_snapshot" in summary["unconfigured_tracked_event_models"]
    assert summary["crypto_signal_event_count"] == 2
    assert summary["asset_symbol_present_count"] == 2
    assert summary["complete_canonical_key_count"] >= 1
    assert summary["daily_review_item_count"] >= 1

    event_models = {event["event_model"] for event in report["events"]}
    assert event_models == {"exchange_listing_notice", "regulatory_action"}
    assert all(event["canonical_key"] for event in report["events"])
    assert all("required_field_gaps" in event for event in report["events"])


def test_quality_report_tracks_operational_analysis_source() -> None:
    category = load_category_config("crypto")
    source = next(source for source in category.sources if source.name == "Glassnode Insights")
    now = datetime(2026, 4, 13, tzinfo=UTC)
    article = Article(
        title="On-chain liquidity and TVL market update",
        link="https://example.com/onchain",
        summary="Bitcoin on-chain liquidity metric and TVL change.",
        published=now - timedelta(hours=3),
        source=source.name,
        category=category.category_name,
        matched_entities={
            "Cryptocurrency": ["bitcoin"],
            "Technology": ["on-chain", "liquidity"],
            "Market": ["volume"],
        },
        collected_at=now - timedelta(hours=3),
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config("crypto"),
        generated_at=now,
    )

    source_row = next(row for row in report["sources"] if row["source"] == source.name)
    assert source_row["event_model"] == "onchain_metric"
    assert source_row["status"] == "fresh"
    assert source_row["freshness_sla_days"] == 10.0
    assert report["summary"]["onchain_metric_events"] == 1
    assert report["summary"]["crypto_signal_event_count"] == 1
    assert report["events"][0]["canonical_key"]


def test_equity_context_sources_do_not_mask_crypto_liquidity_gap() -> None:
    category = load_category_config("crypto")
    report = build_quality_report(
        category=category,
        articles=[],
        quality_config=load_category_quality_config("crypto"),
        generated_at=datetime(2026, 4, 13, tzinfo=UTC),
    )

    equity_sources = {
        "한국 주식테마 MCP",
        "KOSPI 종목 리스트",
        "KOSDAQ 종목 리스트",
    }
    rows = {row["source"]: row for row in report["sources"] if row["source"] in equity_sources}

    assert set(rows) == equity_sources
    assert {row["status"] for row in rows.values()} == {"skipped_disabled"}
    assert report["summary"]["liquidity_snapshot_configured_sources"] == 0
    assert "liquidity_snapshot" in report["summary"]["unconfigured_tracked_event_models"]


def test_write_quality_report_writes_latest_and_dated_files(tmp_path: Path) -> None:
    report = {
        "category": "crypto",
        "generated_at": "2026-04-13T00:00:00+00:00",
        "summary": {},
    }

    paths = write_quality_report(report, output_dir=tmp_path, category_name="crypto")

    assert paths["latest"] == tmp_path / "crypto_quality.json"
    assert paths["dated"] == tmp_path / "crypto_20260413_quality.json"
    assert paths["latest"].exists()
    assert paths["dated"].exists()
