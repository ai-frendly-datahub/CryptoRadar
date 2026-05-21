from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryptoradar.models import Article, CategoryConfig
from cryptoradar.reporter import (
    _inject_crypto_quality_panel,
    _render_crypto_quality_panel,
    generate_index_html,
    generate_report,
)


@pytest.fixture()
def fixed_now():
    return datetime(2024, 3, 15, 9, 30, tzinfo=UTC)


@pytest.fixture()
def patch_datetime(monkeypatch, fixed_now):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr("radar_core.report_utils.datetime", FixedDateTime)


@pytest.fixture()
def report_articles(fixed_now):
    return [
        Article(
            title="Bitcoin Surge",
            link="https://example.com/btc1",
            summary="Bitcoin hits new high.",
            published=fixed_now,
            source="CryptoNews",
            category="crypto",
            matched_entities={"Bitcoin": ["bitcoin"]},
            collected_at=fixed_now,
        ),
    ]


@pytest.fixture()
def report_category():
    return CategoryConfig(
        category_name="crypto",
        display_name="Crypto Radar",
        sources=[],
        entities=[],
    )


@pytest.fixture()
def report_stats():
    return {"sources": 1, "collected": 1, "matched": 1, "window_days": 7}


class TestGenerateReport:
    """Unit tests for generate_report."""

    def test_generate_report_creates_file(
        self, tmp_path, report_category, report_articles, report_stats, patch_datetime
    ):
        """Report file is created at the specified path."""
        output = tmp_path / "reports" / "crypto_report.html"
        result = generate_report(
            category=report_category,
            articles=report_articles,
            output_path=output,
            stats=report_stats,
        )
        assert result == output
        assert output.exists()

    def test_generate_report_html_content(
        self, tmp_path, report_category, report_articles, report_stats, patch_datetime
    ):
        """Generated HTML contains expected content."""
        output = tmp_path / "reports" / "crypto_report.html"
        generate_report(
            category=report_category,
            articles=report_articles,
            output_path=output,
            stats=report_stats,
        )
        html = output.read_text(encoding="utf-8")
        assert "Crypto Radar" in html
        assert "Bitcoin Surge" in html

    def test_generate_report_with_errors(
        self, tmp_path, report_category, report_articles, report_stats, patch_datetime
    ):
        """Error messages appear in the report HTML."""
        output = tmp_path / "reports" / "crypto_report.html"
        generate_report(
            category=report_category,
            articles=report_articles,
            output_path=output,
            stats=report_stats,
            errors=["API rate limited"],
        )
        html = output.read_text(encoding="utf-8")
        assert "API rate limited" in html

    def test_generate_report_injects_crypto_quality_panel(
        self, tmp_path, report_category, report_articles, report_stats, patch_datetime
    ):
        """Crypto quality telemetry appears when provided."""
        output = tmp_path / "reports" / "crypto_report.html"
        generate_report(
            category=report_category,
            articles=report_articles,
            output_path=output,
            stats=report_stats,
            quality_report={
                "summary": {
                    "crypto_signal_event_count": 1,
                    "exchange_listing_notice_events": 1,
                    "event_required_field_gap_count": 2,
                },
                "events": [
                    {
                        "event_model": "exchange_listing_notice",
                        "source": "CoinDesk",
                        "canonical_key": "exchange_listing:coinbase:btc",
                        "canonical_key_status": "complete",
                        "required_field_gaps": [],
                    }
                ],
                "daily_review_items": [],
            },
        )
        html = output.read_text(encoding="utf-8")
        assert 'id="crypto-quality"' in html
        assert "Crypto Quality" in html
        assert "exchange_listing:coinbase:btc" in html
        summaries = sorted(
            (tmp_path / "reports").glob(
                "crypto_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_summary.json"
            )
        )
        assert len(summaries) == 1
        summary = summaries[0].read_text(encoding="utf-8")
        assert '"repo": "CryptoRadar"' in summary
        assert '"ontology_version": "0.1.0"' in summary
        assert '"crypto.exchange_listing_notice"' in summary

    def test_render_quality_panel_distinguishes_official_and_proxy_counts(self):
        html = _render_crypto_quality_panel(
            {
                "summary": {
                    "official_or_operational_event_count": 2,
                    "news_proxy_event_count": 5,
                },
                "events": [],
                "daily_review_items": [
                    {
                        "reason": "source_stale",
                        "source": "Glassnode Insights",
                    }
                ],
            }
        )

        assert "Official events" in html
        assert "News proxies" in html
        assert "source_stale: Glassnode Insights" in html
        assert "No crypto quality events were observed" in html

    def test_inject_quality_panel_appends_when_body_marker_missing(self, tmp_path):
        output = tmp_path / "report.html"
        output.write_text("<html><main>Report</main></html>", encoding="utf-8")

        _inject_crypto_quality_panel(output, {"summary": {}, "events": [], "daily_review_items": []})

        html = output.read_text(encoding="utf-8")
        assert "<main>Report</main></html>" in html
        assert 'id="crypto-quality"' in html


class TestGenerateIndexHtml:
    """Unit tests for generate_index_html."""

    def test_generate_index_html(self, tmp_path):
        """Index HTML is generated listing report files."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir(parents=True)
        (report_dir / "crypto_20240315.html").write_text("<html>crypto</html>", encoding="utf-8")

        index_path = generate_index_html(report_dir)

        assert index_path == report_dir / "index.html"
        assert index_path.exists()
        rendered = index_path.read_text(encoding="utf-8")
        assert "Crypto Radar" in rendered
        assert "crypto_20240315.html" in rendered

    def test_generate_index_html_empty_dir(self, tmp_path):
        """Index is generated even with no reports."""
        report_dir = tmp_path / "empty_reports"
        index_path = generate_index_html(report_dir)

        assert index_path.exists()
        rendered = index_path.read_text(encoding="utf-8")
        assert "Crypto Radar" in rendered
