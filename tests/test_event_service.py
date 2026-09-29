from datetime import datetime, timezone

from app.services import event_service

def test_create_and_list_upcoming (tmp_path, monkeypatch):
    # Point to the DB at a temp file so tests never touch your real data
    test_db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", test_db)
    from app.db import init_db
    init_db()

    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    event_service.create_event("f1", "Test GP", future, priority_tier="A")

    results = event_service.list_upcoming()
    assert len(results) == 1
    assert results[0]["title"] == "Test GP"