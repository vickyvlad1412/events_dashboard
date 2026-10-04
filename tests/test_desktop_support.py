import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import app.config
import app.db
from app import scheduler
from app.db import get_meta, set_meta
from app.services import catalog_service


@pytest.mark.usefixtures("temp_db")
def test_next_sync_time_runs_now_when_never_synced_or_stale():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    assert scheduler.next_sync_time(now) == now

    set_meta(scheduler.LAST_SYNC_KEY, (now - timedelta(hours=7)).isoformat())
    assert scheduler.next_sync_time(now) == now

    set_meta(scheduler.LAST_SYNC_KEY, (now - timedelta(hours=2)).isoformat())
    assert scheduler.next_sync_time(now) == now + timedelta(hours=4)


@pytest.mark.usefixtures("temp_db")
def test_catalog_seed_round_trip_and_never_overwrites(tmp_path):
    catalog_service.upsert_entities("dota", "team", [{"external_id": "Team Spirit", "name": "Team Spirit", "short_name": "Spirit"}])
    catalog_service.upsert_entities("football", "team", [{"external_id": "40", "name": "Liverpool", "image_url": "l.png"}])
    set_meta("catalog_refreshed_at:dota", "2026-10-04T00:00:00+00:00")
    set_meta("last_synced_at", "2026-10-04T00:00:00+00:00")
    seed = tmp_path / "seed" / "catalog_seed.db"

    assert app.db.write_catalog_seed(app.db.DB_PATH, seed) == 2

    fresh = tmp_path / "fresh.db"
    original = app.db.DB_PATH
    app.db.DB_PATH = fresh
    try:
        app.db.init_db()
        app.db.migrate_add_external_columns()
        app.db.migrate_add_watch_history_columns()
        app.db.migrate_add_ui_columns()

        assert app.db.import_catalog_seed(seed) is True
        assert catalog_service.get_entity("dota", "team", "Team Spirit")["short_name"] == "Spirit"
        assert catalog_service.get_entity("football", "team", "40")["image_url"] == "l.png"
        assert get_meta("catalog_refreshed_at:dota") == "2026-10-04T00:00:00+00:00"
        assert get_meta("last_synced_at") is None

        assert app.db.import_catalog_seed(seed) is False
        assert app.db.import_catalog_seed(tmp_path / "missing.db") is False
    finally:
        app.db.DB_PATH = original


@pytest.mark.usefixtures("temp_db")
def test_write_catalog_seed_leaves_source_untouched(tmp_path):
    catalog_service.upsert_entities("dota", "team", [{"external_id": "OG", "name": "OG"}])
    before = sqlite3.connect(app.db.DB_PATH).execute("SELECT COUNT(*) FROM catalog_entities").fetchone()[0]

    app.db.write_catalog_seed(app.db.DB_PATH, tmp_path / "seed.db")
    app.db.write_catalog_seed(app.db.DB_PATH, tmp_path / "seed.db")

    after = sqlite3.connect(app.db.DB_PATH).execute("SELECT COUNT(*) FROM catalog_entities").fetchone()[0]
    assert before == after == 1


def test_data_dir_rules(monkeypatch, tmp_path):
    try:
        monkeypatch.setenv("EVENTS_DASHBOARD_DATA_DIR", str(tmp_path / "custom"))
        assert importlib.reload(app.config).DATA_DIR == tmp_path / "custom"

        monkeypatch.delenv("EVENTS_DASHBOARD_DATA_DIR")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        monkeypatch.setattr(app.config.sys, "frozen", True, raising=False)
        assert importlib.reload(app.config).DATA_DIR == tmp_path / "local" / "MyWatchDashboard"

        monkeypatch.delattr(app.config.sys, "frozen")
        reloaded = importlib.reload(app.config)
        assert reloaded.DATA_DIR == reloaded.BASE_DIR / "data"
        assert reloaded.SCHEMA_PATH.exists()
    finally:
        monkeypatch.undo()
        importlib.reload(app.config)
