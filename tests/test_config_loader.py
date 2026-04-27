from __future__ import annotations

from cryptoradar.config_loader import load_category_config, load_category_quality_config


def test_crypto_category_preserves_source_metadata() -> None:
    category = load_category_config("crypto")

    glassnode = next(source for source in category.sources if source.name == "Glassnode Insights")
    assert glassnode.trust_tier == "T2_institutional"
    assert glassnode.content_type == "analysis"
    assert glassnode.collection_tier == "C1_rss"
    assert glassnode.config["freshness_sla_days"] == 3

    kospi = next(source for source in category.sources if source.name == "KOSPI 종목 리스트")
    assert kospi.type == "financedata"
    assert kospi.content_type == "equity_market_context"
    assert kospi.info_purpose == ["cross_market_context"]
    assert kospi.config["method"] == "StockListing"


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
