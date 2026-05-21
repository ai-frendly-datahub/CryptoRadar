from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptoradar.config_loader import load_category_config, load_category_quality_config
from cryptoradar.models import Article, Source
from cryptoradar.quality_report import (
    _canonical_key,
    _metric_value,
    _required_field_gaps,
    _source_event_model,
    _source_status,
    build_quality_report,
    write_quality_report,
)


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


def test_public_listing_language_does_not_create_exchange_listing_notice() -> None:
    category = load_category_config("crypto")
    source = next(source for source in category.sources if source.name == "CoinDesk")
    article = Article(
        title="Securitize gears up for public listing",
        link="https://example.com/public-listing",
        summary="A crypto firm prepares for an IPO and public listing.",
        published=datetime(2026, 5, 21, tzinfo=UTC),
        source=source.name,
        category=category.category_name,
        matched_entities={
            "Cryptocurrency": ["crypto"],
            "Exchange": ["listing"],
            "CryptoGeneral": ["crypto"],
        },
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config("crypto"),
        generated_at=datetime(2026, 5, 21, tzinfo=UTC),
    )

    assert report["summary"]["exchange_listing_notice_events"] == 0
    assert report["events"] == []


def test_regulator_mention_without_action_does_not_create_regulatory_action() -> None:
    category = load_category_config("crypto")
    source = next(source for source in category.sources if source.name == "CoinDesk")
    article = Article(
        title="Bitcoin traders watch the SEC calendar",
        link="https://example.com/sec-calendar",
        summary="Analysts mention SEC timing as one market factor without a new decision.",
        published=datetime(2026, 5, 21, tzinfo=UTC),
        source=source.name,
        category=category.category_name,
        matched_entities={
            "Cryptocurrency": ["bitcoin"],
            "Regulation": ["SEC"],
        },
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config("crypto"),
        generated_at=datetime(2026, 5, 21, tzinfo=UTC),
    )

    assert report["summary"]["regulatory_action_events"] == 0
    assert report["events"] == []


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
    assert source_row["freshness_sla_days"] == 21.0
    assert report["summary"]["onchain_metric_events"] == 1
    assert report["summary"]["crypto_signal_event_count"] == 1
    assert report["events"][0]["canonical_key"]


def test_onchain_metric_value_parses_common_units() -> None:
    article = Article(
        title="Ethereum TVL reaches $1.25B after staking inflows",
        link="https://example.com/onchain-metric",
        summary="Glassnode notes liquidity and volume gains in the latest on-chain update.",
        published=datetime(2026, 5, 21, tzinfo=UTC),
        source="Glassnode Insights",
        category="crypto",
        matched_entities={
            "Cryptocurrency": ["ethereum"],
            "Technology": ["on-chain", "staking"],
            "Market": ["volume"],
        },
    )

    assert _metric_value(article) == 1_250_000_000


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


def test_disabled_sources_do_not_count_historical_articles_in_quality_rows() -> None:
    category = load_category_config("crypto")
    disabled_source = next(source for source in category.sources if source.name == "코인데스크 코리아")
    article = Article(
        title="Bitcoin historical item from disabled feed",
        link="https://example.com/disabled-feed",
        summary="Bitcoin item that should not count while source is disabled.",
        published=datetime(2026, 5, 21, tzinfo=UTC),
        source=disabled_source.name,
        category=category.category_name,
        matched_entities={"Cryptocurrency": ["bitcoin"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config("crypto"),
        generated_at=datetime(2026, 5, 21, tzinfo=UTC),
    )

    row = next(row for row in report["sources"] if row["source"] == disabled_source.name)
    assert row["status"] == "skipped_disabled"
    assert row["article_count"] == 0
    assert row["event_count"] == 0


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


def test_quality_report_helper_branches_cover_operational_models() -> None:
    assert _source_event_model(Source(name="Price Feed", type="rss", url="", content_type="price")) == ""
    assert (
        _source_event_model(Source(name="Liquidity", type="rss", url="", content_type="crypto_market"))
        == "liquidity_snapshot"
    )
    assert _source_event_model(Source(name="SEC", type="rss", url="", content_type="regulation")) == "regulatory_action"
    assert (
        _source_event_model(Source(name="Listings", type="rss", url="", content_type="listing"))
        == "exchange_listing_notice"
    )

    assert (
        _source_status(
            source=Source(name="S", type="rss", url=""),
            event_model="exchange_listing_notice",
            tracked_event_models={"exchange_listing_notice"},
            article_count=1,
            event_count=0,
            latest_event_at=None,
            sla_days=None,
            age_days=None,
        )
        == "missing_event"
    )
    assert (
        _source_status(
            source=Source(name="S", type="rss", url=""),
            event_model="exchange_listing_notice",
            tracked_event_models={"exchange_listing_notice"},
            article_count=1,
            event_count=1,
            latest_event_at=None,
            sla_days=None,
            age_days=None,
        )
        == "unknown_event_date"
    )
    assert (
        _source_status(
            source=Source(name="S", type="rss", url=""),
            event_model="exchange_listing_notice",
            tracked_event_models={"exchange_listing_notice"},
            article_count=1,
            event_count=1,
            latest_event_at=datetime(2026, 1, 1, tzinfo=UTC),
            sla_days=1,
            age_days=2,
        )
        == "stale"
    )


def test_canonical_key_and_required_field_edge_cases() -> None:
    assert _canonical_key({"event_model": "exchange_listing_notice", "cryptocurrency": ["BTC"]}) == (
        "crypto_asset:btc",
        "asset_proxy",
    )
    assert _canonical_key(
        {
            "event_model": "regulatory_action",
            "regulator": "SEC",
            "jurisdiction": "US",
        }
    ) == ("reg_action:sec:us", "regulator_proxy")
    assert _canonical_key({"event_model": "unknown", "source": "Feed", "title": "Some Title"})[1] == "source_proxy"
    assert _canonical_key({"event_model": "unknown"}) == ("", "missing")

    row = {"event_model": "liquidity_snapshot", "asset_pair": "BTC-USD", "liquidity_metric": "volume"}
    source = Source(name="Price", type="rss", url="", content_type="price")

    assert _required_field_gaps(row, source, "liquidity_snapshot", {}) == []
