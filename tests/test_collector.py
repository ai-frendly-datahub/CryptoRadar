from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests

from cryptoradar.collector import (
    RateLimiter,
    _clean_html_text,
    _collect_single,
    _detect_encoding,
    _entry_text,
    _extract_datetime,
    _fetch_url_with_retry,
    _parse_retry_after,
    _resolve_max_workers,
    article_matches_source_scope,
    collect_sources,
)
from cryptoradar.exceptions import NetworkError, ParseError, SourceError
from cryptoradar.models import Source


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_acquire_no_delay_on_first_call(self):
        """First acquire call should not delay."""
        limiter = RateLimiter(min_interval=0.5)
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_acquire_delays_subsequent_calls(self):
        """Subsequent calls within min_interval should delay."""
        limiter = RateLimiter(min_interval=0.1)
        limiter.acquire()
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        # Should have delayed close to min_interval
        assert elapsed >= 0.08


class TestResolveMaxWorkers:
    """Unit tests for _resolve_max_workers function."""

    def test_default_value(self):
        """Default returns 5 when no env var and no argument."""
        with patch.dict("os.environ", {}, clear=True):
            result = _resolve_max_workers(None)
        assert result == 5

    def test_explicit_value(self):
        """Explicit value is used when provided."""
        result = _resolve_max_workers(3)
        assert result == 3

    def test_max_capped_at_10(self):
        """Values above 10 are capped."""
        result = _resolve_max_workers(20)
        assert result == 10

    def test_min_capped_at_1(self):
        """Values below 1 are raised to 1."""
        result = _resolve_max_workers(0)
        assert result == 1

    def test_env_var_override(self):
        """Environment variable overrides default."""
        with patch.dict("os.environ", {"RADAR_MAX_WORKERS": "7"}):
            result = _resolve_max_workers(None)
        assert result == 7

    def test_invalid_env_var_uses_default(self):
        """Invalid env var falls back to default."""
        with patch.dict("os.environ", {"RADAR_MAX_WORKERS": "invalid"}):
            result = _resolve_max_workers(None)
        assert result == 5


class TestParseRetryAfter:
    """Unit tests for _parse_retry_after function."""

    def test_none_value(self):
        """None input returns None."""
        assert _parse_retry_after(None) is None

    def test_empty_string(self):
        """Empty string returns None."""
        assert _parse_retry_after("") is None
        assert _parse_retry_after("   ") is None

    def test_numeric_string(self):
        """Numeric string returns int."""
        assert _parse_retry_after("60") == 60
        assert _parse_retry_after("120") == 120

    def test_date_string(self):
        """Date string returns the string itself."""
        date_str = "Wed, 21 Oct 2025 07:28:00 GMT"
        assert _parse_retry_after(date_str) == date_str


class TestDetectEncoding:
    """Unit tests for _detect_encoding function."""

    def test_utf8_default(self):
        """Default encoding is UTF-8."""
        response = MagicMock()
        response.headers = {"Content-Type": "text/xml"}
        assert _detect_encoding(response) == "utf-8"

    def test_euc_kr_detection(self):
        """EUC-KR encoding is detected from Content-Type."""
        response = MagicMock()
        response.headers = {"Content-Type": "text/html; charset=euc-kr"}
        assert _detect_encoding(response) == "euc-kr"

    def test_charset_extraction(self):
        """Charset is extracted from Content-Type header."""
        response = MagicMock()
        response.headers = {"Content-Type": "text/html; charset=iso-8859-1"}
        assert _detect_encoding(response) == "iso-8859-1"


class TestExtractDatetime:
    """Unit tests for _extract_datetime function."""

    def test_published_parsed(self):
        """Parses published_parsed struct_time."""
        # Use a mid-year date to avoid timezone edge cases at year boundaries
        entry = {"published_parsed": time.strptime("2024-06-15 12:00:00", "%Y-%m-%d %H:%M:%S")}
        result = _extract_datetime(entry)
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_updated_parsed_fallback(self):
        """Falls back to updated_parsed if published_parsed is missing."""
        entry = {"updated_parsed": time.strptime("2024-07-20 12:00:00", "%Y-%m-%d %H:%M:%S")}
        result = _extract_datetime(entry)
        assert result is not None
        assert result.year == 2024
        assert result.month == 7

    def test_struct_time_is_treated_as_utc(self, monkeypatch):
        """Feedparser struct_time values are GMT and must not be shifted by local TZ."""
        previous_tz = os.environ.get("TZ")
        if hasattr(time, "tzset"):
            monkeypatch.setenv("TZ", "Asia/Seoul")
            time.tzset()
        try:
            entry = {
                "published_parsed": time.strptime(
                    "2024-06-15 12:00:00",
                    "%Y-%m-%d %H:%M:%S",
                )
            }
            result = _extract_datetime(entry)
        finally:
            if hasattr(time, "tzset"):
                if previous_tz is None:
                    monkeypatch.delenv("TZ", raising=False)
                else:
                    monkeypatch.setenv("TZ", previous_tz)
                time.tzset()

        assert result == datetime(2024, 6, 15, 12, 0, tzinfo=UTC)

    def test_naive_struct_time_can_use_source_timezone(self):
        """Timezone-less Korean RSS dates are interpreted as local source time."""
        entry = {
            "published": "2026-05-21 16:25:00",
            "published_parsed": time.strptime("2026-05-21 16:25:00", "%Y-%m-%d %H:%M:%S"),
        }

        result = _extract_datetime(entry, default_timezone=ZoneInfo("Asia/Seoul"))

        assert result == datetime(2026, 5, 21, 7, 25, tzinfo=UTC)

    def test_struct_time_with_explicit_timezone_stays_utc(self):
        """Explicit offsets in RSS dates should not be reinterpreted as local source time."""
        entry = {
            "published": "Thu, 21 May 2026 16:25:00 +0000",
            "published_parsed": time.strptime("2026-05-21 16:25:00", "%Y-%m-%d %H:%M:%S"),
        }

        result = _extract_datetime(entry, default_timezone=ZoneInfo("Asia/Seoul"))

        assert result == datetime(2026, 5, 21, 16, 25, tzinfo=UTC)

    def test_rfc2822_date_string(self):
        """Parses RFC 2822 date string."""
        entry = {"published": "Mon, 01 Jan 2024 12:00:00 +0000"}
        result = _extract_datetime(entry)
        assert result is not None
        assert result.year == 2024

    def test_no_date_returns_none(self):
        """Returns None when no date fields are present."""
        entry = {}
        result = _extract_datetime(entry)
        assert result is None


class TestEntryText:
    """Unit tests for _entry_text function."""

    def test_string_value(self):
        """Returns string value when present."""
        entry = {"title": "Test Title"}
        assert _entry_text(entry, "title") == "Test Title"

    def test_missing_key(self):
        """Returns empty string for missing key."""
        entry = {}
        assert _entry_text(entry, "title") == ""

    def test_non_string_value(self):
        """Returns empty string for non-string values."""
        entry = {"title": 123}
        assert _entry_text(entry, "title") == ""

    def test_none_value(self):
        """Returns empty string for None value."""
        entry = {"title": None}
        assert _entry_text(entry, "title") == ""


def test_clean_html_text_strips_markup_and_collapses_whitespace():
    assert (
        _clean_html_text("<p>Bitcoin&nbsp;<strong>rallies</strong></p>\n<p>again</p>")
        == "Bitcoin rallies again"
    )


class TestSourceModel:
    """Tests for Source model usage in collector."""

    def test_source_creation(self):
        """Source model can be created with required fields."""
        source = Source(
            name="TestSource",
            type="rss",
            url="https://example.com/feed",
        )
        assert source.name == "TestSource"
        assert source.type == "rss"
        assert source.url == "https://example.com/feed"


class TestCollectSources:
    """Tests for source routing before network collection."""

    def test_disabled_non_rss_source_is_skipped(self):
        source = Source(
            name="DART MCP",
            type="mcp",
            url="https://example.com/mcp",
            enabled=False,
        )

        articles, errors = collect_sources([source], category="crypto")

        assert articles == []
        assert errors == []

    def test_enabled_non_rss_source_is_reported_as_cataloged_not_collected(self):
        source = Source(name="DART MCP", type="mcp", url="https://example.com/mcp")

        articles, errors = collect_sources([source], category="crypto")

        assert articles == []
        assert len(errors) == 1
        assert "cataloged but not collected" in errors[0]

    def test_parallel_collection_uses_one_session_per_source(self, tmp_path, monkeypatch):
        """Worker sessions are not shared across RSS sources."""
        created_sessions = []

        class FakeSession:
            def __init__(self):
                self.closed = False
                created_sessions.append(self)

            def close(self):
                self.closed = True

        def fake_collect_single(source, *, category, limit, timeout, session):
            assert session in created_sessions
            return []

        monkeypatch.setattr("cryptoradar.collector._create_session", FakeSession)
        monkeypatch.setattr("cryptoradar.collector._collect_single", fake_collect_single)

        sources = [
            Source(name="A", type="rss", url="https://a.example/feed"),
            Source(name="B", type="rss", url="https://b.example/feed"),
        ]

        articles, errors = collect_sources(
            sources,
            category="crypto",
            max_workers=2,
            health_db_path=str(tmp_path / "health.duckdb"),
        )

        assert articles == []
        assert errors == []
        assert len(created_sessions) == 2
        assert all(session.closed for session in created_sessions)


class TestCollectSingle:
    """Unit tests for single-source RSS parsing."""

    def test_collect_single_parses_rss_feed(self, monkeypatch):
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Bitcoin listing update</title>
            <link>https://example.com/btc</link>
            <description>Bitcoin exchange listing summary with enough text to skip extraction.</description>
            <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
          </item>
        </channel></rss>
        """
        response = MagicMock()
        response.headers = {"Content-Type": "application/rss+xml; charset=utf-8"}
        response.content = rss
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr("cryptoradar.collector.extract_url_content_safe", MagicMock())

        articles = _collect_single(
            Source(name="Feed", type="rss", url="https://example.com/feed"),
            category="crypto",
            limit=5,
            timeout=3,
            session=session,
        )

        assert len(articles) == 1
        assert articles[0].title == "Bitcoin listing update"
        assert articles[0].summary.startswith("Bitcoin exchange listing")
        assert "<" not in articles[0].summary
        assert articles[0].published == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert articles[0].category == "crypto"

    def test_collect_single_rejects_unsupported_source_type(self):
        with pytest.raises(SourceError):
            _collect_single(
                Source(name="API", type="json", url="https://example.com/api"),
                category="crypto",
                limit=5,
                timeout=3,
            )


def test_article_matches_source_scope_filters_broad_business_feed_items():
    source = Source(
        name="블로터",
        type="rss",
        url="https://www.bloter.net/rss/allArticle.xml",
        config={"include_keywords": ["가상자산", "블록체인", "bitcoin", "crypto"]},
    )

    assert not article_matches_source_scope(
        source,
        "[유암코, 성장의 그늘] STX엔진 주총 격돌",
        "방산 전문성과 감사 선임을 둘러싼 주주총회 기사입니다.",
        "https://www.bloter.net/news/articleView.html?idxno=660983",
    )
    assert article_matches_source_scope(
        source,
        "금융위, 가상자산 거래소 공시 기준 점검",
        "블록체인 업계와 crypto market participants are watching the rules.",
        "https://www.bloter.net/news/articleView.html?idxno=1",
    )


def test_article_matches_source_scope_filters_general_ai_items_but_keeps_crypto_context():
    source = Source(
        name="Decrypt",
        type="rss",
        url="https://decrypt.co/feed",
        config={
            "include_keywords": [
                "bitcoin",
                "crypto",
                "stablecoin",
                "ETF",
                "blockchain",
                "token",
            ]
        },
    )

    assert not article_matches_source_scope(
        source,
        "OpenAI launches overseas AI lab in Singapore",
        "The company committed funding to a new artificial intelligence research hub.",
        "https://decrypt.co/openai-lab",
    )
    assert article_matches_source_scope(
        source,
        "Qivalis expands euro stablecoin consortium to 37 banks",
        "The stablecoin initiative adds more banks ahead of launch.",
        "https://decrypt.co/stablecoin-banks",
    )
    assert article_matches_source_scope(
        source,
        "Bitcoin ETF inflows rebound",
        "Asset managers reported stronger ETF demand.",
        "https://decrypt.co/bitcoin-etf",
    )


class TestCollectorExceptions:
    """Tests for collector exception handling."""

    def test_source_error_message(self):
        """SourceError formats message with source name."""
        error = SourceError("TestSource", "Connection failed")
        assert "TestSource" in str(error)
        assert "Connection failed" in str(error)

    def test_network_error(self):
        """NetworkError can be raised with message."""
        error = NetworkError("Timeout occurred")
        assert "Timeout" in str(error)

    def test_parse_error(self):
        """ParseError can be raised with message."""
        error = ParseError("Invalid XML")
        assert "Invalid XML" in str(error)


class TestFetchUrlWithRetry:
    """Unit tests for retry bookkeeping around HTTP fetches."""

    def test_records_success_with_throttler_and_health_store(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        session = MagicMock()
        session.get.return_value = response
        throttler = MagicMock()
        throttler.get_current_delay.return_value = 1.25
        health_store = MagicMock()

        result = _fetch_url_with_retry(
            "https://example.com/feed",
            timeout=3,
            session=session,
            source_name="SourceA",
            throttler=throttler,
            health_store=health_store,
            max_attempts=1,
        )

        assert result is response
        throttler.acquire.assert_called_once_with("SourceA")
        throttler.record_success.assert_called_once_with("SourceA")
        health_store.record_success.assert_called_once_with("SourceA", 1.25)

    def test_records_retry_after_for_rate_limit_failure(self):
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "60"}
        error = requests.exceptions.HTTPError("rate limited", response=response)
        session = MagicMock()
        session.get.side_effect = error
        throttler = MagicMock()
        throttler.get_current_delay.return_value = 2.0
        health_store = MagicMock()

        with pytest.raises(requests.exceptions.HTTPError):
            _fetch_url_with_retry(
                "https://example.com/feed",
                timeout=3,
                session=session,
                source_name="SourceA",
                throttler=throttler,
                health_store=health_store,
                max_attempts=1,
            )

        throttler.record_failure.assert_called_once_with("SourceA", retry_after=60)
        health_store.record_failure.assert_called_once_with("SourceA", "rate limited", 2.0)
