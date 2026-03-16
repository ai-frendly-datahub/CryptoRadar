from __future__ import annotations

from cryptoradar.analyzer import apply_entity_rules
from cryptoradar.models import Article, EntityDefinition


def _make_article(title: str, summary: str = "") -> Article:
    return Article(
        title=title,
        link=f"https://example.com/{hash(title)}",
        summary=summary,
        published=None,
        source="TestSource",
        category="test",
    )


class TestApplyEntityRules:
    """Unit tests for apply_entity_rules keyword matching."""

    def test_keyword_match(self):
        """Keyword in title triggers a match."""
        articles = [_make_article("Bitcoin price surge")]
        entities = [EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"])]

        result = apply_entity_rules(articles, entities)

        assert len(result) == 1
        assert "Bitcoin" in result[0].matched_entities
        assert "bitcoin" in result[0].matched_entities["Bitcoin"]

    def test_no_match(self):
        """No match when keyword is absent."""
        articles = [_make_article("Ethereum update")]
        entities = [EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"])]

        result = apply_entity_rules(articles, entities)

        assert len(result) == 1
        assert result[0].matched_entities == {}

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        articles = [_make_article("BITCOIN Hits New ATH")]
        entities = [EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"])]

        result = apply_entity_rules(articles, entities)

        assert "Bitcoin" in result[0].matched_entities

    def test_multiple_entities(self):
        """Multiple entities can match the same article."""
        articles = [_make_article("Bitcoin and Ethereum rally")]
        entities = [
            EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"]),
            EntityDefinition(name="Ethereum", display_name="Ethereum", keywords=["ethereum"]),
        ]

        result = apply_entity_rules(articles, entities)

        assert "Bitcoin" in result[0].matched_entities
        assert "Ethereum" in result[0].matched_entities

    def test_empty_articles(self):
        """Empty article list returns empty result."""
        entities = [EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"])]

        result = apply_entity_rules([], entities)

        assert result == []

    def test_summary_match(self):
        """Keywords in summary also trigger matches."""
        articles = [_make_article("Market update", summary="Bitcoin dominance rising")]
        entities = [EntityDefinition(name="Bitcoin", display_name="Bitcoin", keywords=["bitcoin"])]

        result = apply_entity_rules(articles, entities)

        assert "Bitcoin" in result[0].matched_entities

    def test_non_ascii_keyword(self):
        """Non-ASCII (Korean) keywords match via substring."""
        articles = [_make_article("비트코인 시세 급등")]
        entities = [
            EntityDefinition(name="비트코인", display_name="비트코인", keywords=["비트코인"])
        ]

        result = apply_entity_rules(articles, entities)

        assert "비트코인" in result[0].matched_entities
