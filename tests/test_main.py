from __future__ import annotations

from pathlib import Path

import main
from cryptoradar.models import Article, Source


def test_cli_coercion_helpers_ignore_invalid_values() -> None:
    assert main._to_path(Path("config.yaml")) == Path("config.yaml")
    assert main._to_path("config.yaml") is None
    assert main._to_int("15", 3) == 15
    assert main._to_int(True, 3) == 3
    assert main._to_int("bad", 3) == 3
    assert main._to_optional_int("7") == 7
    assert main._to_optional_int(False) is None
    assert main._to_optional_int("bad") is None
    assert main._to_str_list(["A", 1, "B"]) == ["A", "B"]
    assert main._to_str_list("A") == []


def test_filter_report_articles_applies_source_scope() -> None:
    source = Source(
        name="BroadFeed",
        type="rss",
        url="https://example.com/feed",
        config={"include_keywords": ["bitcoin"]},
    )
    matching = Article(
        title="Bitcoin market update",
        link="https://example.com/1",
        summary="",
        published=None,
        source="BroadFeed",
        category="crypto",
    )
    filtered = Article(
        title="Equity market update",
        link="https://example.com/2",
        summary="",
        published=None,
        source="BroadFeed",
        category="crypto",
    )
    unknown_source = Article(
        title="No source config",
        link="https://example.com/3",
        summary="",
        published=None,
        source="Unknown",
        category="crypto",
    )
    disabled_source = Source(
        name="DisabledFeed",
        type="rss",
        url="https://disabled.example/feed",
        enabled=False,
    )
    disabled_article = Article(
        title="Bitcoin should not appear",
        link="https://example.com/4",
        summary="bitcoin",
        published=None,
        source="DisabledFeed",
        category="crypto",
    )

    result = main._filter_report_articles(
        [matching, filtered, unknown_source, disabled_article],
        [source, disabled_source],
    )

    assert result == [matching, unknown_source]
