from __future__ import annotations

import yaml

from cryptoradar.config_loader import (
    load_category_config,
    load_category_quality_config,
    load_notification_config,
    load_settings,
)


def test_crypto_category_preserves_source_metadata() -> None:
    category = load_category_config("crypto")

    glassnode = next(source for source in category.sources if source.name == "Glassnode Insights")
    assert glassnode.trust_tier == "T2_institutional"
    assert glassnode.content_type == "analysis"
    assert glassnode.collection_tier == "C1_rss"
    assert glassnode.config["freshness_sla_days"] == 21

    kospi = next(source for source in category.sources if source.name == "KOSPI 종목 리스트")
    assert kospi.type == "financedata"
    assert kospi.enabled is False
    assert kospi.content_type == "equity_market_context"
    assert kospi.info_purpose == ["cross_market_context"]
    assert kospi.config["method"] == "StockListing"

    bloter = next(source for source in category.sources if source.name == "블로터")
    assert bloter.url == "https://www.bloter.net/rss/allArticle.xml"
    assert bloter.config["bypass_crawl_health"] is True
    assert "가상자산" in bloter.config["include_keywords"]
    assert "코인" not in bloter.config["include_keywords"]

    digital_today = next(source for source in category.sources if source.name == "디지털투데이")
    assert digital_today.config["include_keywords"] == bloter.config["include_keywords"]
    assert digital_today.config["timezone"] == "Asia/Seoul"

    coindesk_korea = next(source for source in category.sources if source.name == "코인데스크 코리아")
    assert coindesk_korea.enabled is False

    scoped_global_sources = {
        "CoinTelegraph",
        "CoinDesk",
        "The Block",
        "Decrypt",
        "Bitcoin Magazine",
        "CryptoSlate",
        "BeInCrypto",
    }
    sources_by_name = {source.name: source for source in category.sources}
    for source_name in scoped_global_sources:
        assert sources_by_name[source_name].config["include_keywords"] == bloter.config["include_keywords"]

    hankyung = next(source for source in category.sources if source.name == "한경 블록체인")
    assert hankyung.enabled is False


def test_crypto_quality_config_tracks_operational_event_models() -> None:
    quality_config = load_category_quality_config("crypto")
    data_quality = quality_config["data_quality"]
    assert isinstance(data_quality, dict)
    outputs = data_quality["quality_outputs"]
    assert isinstance(outputs, dict)
    assert outputs["tracked_event_models"] == [
        "exchange_listing_notice",
        "regulatory_action",
        "onchain_metric",
        "liquidity_snapshot",
    ]


def test_notification_config_reads_runtime_yaml(tmp_path) -> None:
    config_path = tmp_path / "notifications.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "enabled": True,
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 2525,
                    "smtp_user": "radar",
                    "smtp_password": "secret",
                    "from_addr": "radar@example.com",
                    "to_addrs": ["ops@example.com"],
                },
                "webhook": {
                    "enabled": True,
                    "url": "https://hooks.example.com/radar",
                    "method": "POST",
                    "headers": {"Authorization": "Bearer token"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_notification_config(config_path)

    assert config.enabled is True
    assert config.channels == ["email", "webhook"]
    assert config.email is not None
    assert config.email.smtp_host == "smtp.example.com"
    assert config.email.smtp_port == 2525
    assert config.email.to_addrs == ["ops@example.com"]
    assert config.webhook is not None
    assert config.webhook.url == "https://hooks.example.com/radar"
    assert config.webhook.headers == {"Authorization": "Bearer token"}


def test_load_settings_resolves_relative_paths(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "database_path": "data/test.duckdb",
                "report_dir": "reports",
                "raw_data_dir": "data/raw",
                "search_db_path": "data/search.db",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.database_path.is_absolute()
    assert settings.database_path.name == "test.duckdb"
    assert settings.report_dir.name == "reports"
