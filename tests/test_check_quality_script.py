from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from cryptoradar.models import Article
from cryptoradar.storage import RadarStorage


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_quality.py"
    spec = importlib.util.spec_from_file_location("cryptoradar_check_quality_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_quality_artifacts_uses_latest_stored_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path
    (project_root / "config" / "categories").mkdir(parents=True)

    (project_root / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "database_path": "data/radar_data.duckdb",
                "report_dir": "reports",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_root / "config" / "categories" / "crypto.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "crypto",
                "display_name": "Crypto Radar",
                "sources": [
                    {
                        "id": "listing_feed",
                        "name": "Listing Feed",
                        "type": "rss",
                        "url": "https://example.com/crypto.xml",
                        "enabled": True,
                        "config": {
                            "event_model": "exchange_listing_notice",
                        },
                    }
                ],
                "entities": [],
                "data_quality": {
                    "quality_outputs": {
                        "tracked_event_models": ["exchange_listing_notice"],
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    article_time = datetime.now(UTC) - timedelta(days=30)
    db_path = project_root / "data" / "radar_data.duckdb"
    with RadarStorage(db_path) as storage:
        storage.upsert_articles(
            [
                Article(
                    title="Exchange lists Bitcoin ETF token",
                    link="https://example.com/coinbase-listing",
                    summary="Coinbase listing coverage for a Bitcoin-related asset.",
                    published=article_time,
                    source="Listing Feed",
                    category="crypto",
                    matched_entities={
                        "Cryptocurrency": ["bitcoin"],
                        "Exchange": ["coinbase", "listing"],
                    },
                )
            ]
        )
        storage.conn.execute(
            "UPDATE articles SET collected_at = ? WHERE link = ?",
            [article_time.replace(tzinfo=None), "https://example.com/coinbase-listing"],
        )

    module = _load_script_module()
    paths, report = module.generate_quality_artifacts(project_root)

    assert Path(paths["latest"]).exists()
    assert Path(paths["dated"]).exists()
    assert report["summary"]["tracked_sources"] == 1
    assert report["summary"]["exchange_listing_notice_events"] == 1

    module.PROJECT_ROOT = project_root
    module.main()
    captured = capsys.readouterr()
    assert "quality_report=" in captured.out
    assert "tracked_sources=1" in captured.out
    assert "crypto_signal_event_count=1" in captured.out
