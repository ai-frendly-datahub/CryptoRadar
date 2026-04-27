from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from cryptoradar.collector import (
    RateLimiter,
    _detect_encoding,
    _entry_text,
    _extract_datetime,
    _parse_retry_after,
    _resolve_max_workers,
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

    def test_updated_parsed_fallback(self):
        """Falls back to updated_parsed if published_parsed is missing."""
        entry = {"updated_parsed": time.strptime("2024-07-20 12:00:00", "%Y-%m-%d %H:%M:%S")}
        result = _extract_datetime(entry)
        assert result is not None
        assert result.year == 2024
        assert result.month == 7

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
