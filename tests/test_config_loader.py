from __future__ import annotations

from cryptoradar.config_loader import load_category_config, load_category_quality_config


def test_crypto_category_preserves_source_metadata() -> None:
    category = load_category_config("crypto")

    glassnode = next(source for source in category.sources if source.name == "Glassnode Insights")
    assert glassnode.trust_tier == "T2_institutional"
    assert glassnode.content_type == "analysis"
    assert glassnode.collection_tier == "C1_rss"
    assert glassnode.config["freshness_sla_days"] == 10

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

    digital_today = next(source for source in category.sources if source.name == "디지털투데이")
    assert digital_today.config["include_keywords"] == bloter.config["include_keywords"]

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
