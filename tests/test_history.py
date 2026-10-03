from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_connection
from app.services import event_service, history_service

pytestmark = pytest.mark.usefixtures("temp_db")


def _event(external_id, days_from_now, tier="A", category="f1", **overrides):
    event_service.upsert_external_event(
        {
            "category": category,
            "title": f"Event {external_id}",
            "event_datetime_utc": datetime.now(timezone.utc) + timedelta(days=days_from_now),
            "priority_tier": tier,
            "external_source": "test",
            "external_id": external_id,
            **overrides,
        }
    )
    with get_connection() as conn:
        return conn.execute("SELECT id FROM events WHERE external_id = ?", (external_id,)).fetchone()["id"]


def _status(event_id):
    with get_connection() as conn:
        return conn.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()["status"]


def _set_watched_at(event_id, days_ago):
    with get_connection() as conn:
        conn.execute(
            "UPDATE watch_history SET watched_at = datetime('now', ?) WHERE event_id = ?",
            (f"-{days_ago} days", event_id),
        )


def test_mark_watched_records_mode_once():
    event_id = _event("e1", 1)

    event_service.mark_status(event_id, "WATCHED", "LIVE")
    event_service.mark_status(event_id, "WATCHED", "VOD")

    history = history_service.list_history("all")
    assert [(h["event_id"], h["watched_mode"]) for h in history] == [(event_id, "LIVE")]


@pytest.mark.parametrize(
    "days, tier, start_status, expected",
    [
        (1, "A", None, "UPCOMING"),
        (-1, "A", "MISSED", "MISSED"),
        (-1, "C", "COMPLETED", "COMPLETED"),
        (-1, "B", "CATCHUP_REQUIRED", "CATCHUP_REQUIRED"),
    ],
)
def test_unmark_restores_previous_status(days, tier, start_status, expected):
    overrides = {"status": start_status} if start_status else {}
    event_id = _event("e1", days, tier, **overrides)

    event_service.mark_status(event_id, "WATCHED", "VOD")
    event_service.unmark_watched(event_id)

    assert _status(event_id) == expected
    assert history_service.list_history("all") == []


def test_unmark_watched_live_event_that_has_since_passed():
    event_id = _event("e1", 1)
    event_service.mark_status(event_id, "WATCHED", "LIVE")
    with get_connection() as conn:
        conn.execute(
            "UPDATE events SET event_datetime_utc = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), event_id),
        )

    event_service.unmark_watched(event_id)

    assert _status(event_id) == "MISSED"


def test_history_filters_by_period_and_category():
    recent_f1 = _event("recent_f1", -1)
    old_f1 = _event("old_f1", -60)
    recent_movie = _event("recent_movie", -2, "B", "movie")
    for event_id in (recent_f1, old_f1, recent_movie):
        event_service.mark_status(event_id, "WATCHED", "VOD")
    _set_watched_at(old_f1, 60)

    assert {h["event_id"] for h in history_service.list_history("30d")} == {recent_f1, recent_movie}
    assert {h["event_id"] for h in history_service.list_history("90d", "f1")} == {recent_f1, old_f1}
    assert [h["event_id"] for h in history_service.list_history("all", "movie")] == [recent_movie]


def test_watch_stats():
    watched_live = _event("w1", -1)
    watched_vod = _event("w2", -2)
    _event("missed", -3, "A", status="MISSED")
    _event("low_tier_completed", -3, "C", status="COMPLETED")
    _event("future", 3)
    movie = _event("m1", -1, "B", "movie")
    event_service.mark_status(watched_live, "WATCHED", "LIVE")
    event_service.mark_status(watched_vod, "WATCHED", "VOD")
    event_service.mark_status(movie, "WATCHED", "CINEMA")

    stats = history_service.watch_stats("30d")

    assert stats["total"] == 3
    assert {r["name"]: r["count"] for r in stats["by_category"]} == {"f1": 2, "movie": 1}
    assert {r["mode"]: r["count"] for r in stats["by_mode"]} == {"LIVE": 1, "VOD": 1, "CINEMA": 1}
    assert {r["name"]: (r["watched"], r["missed"], r["rate"]) for r in stats["completion"]} == {
        "f1": (2, 1, 67),
        "movie": (1, 0, 100),
    }
    assert len(stats["monthly"]) == history_service.MONTHS_SHOWN
    assert stats["monthly"][-1]["count"] == 3
    assert stats["monthly"][-1]["percent"] == 100


def test_watch_stats_by_category_and_empty():
    assert history_service.watch_stats("7d")["total"] == 0
    assert history_service.watch_stats("7d")["completion"] == []

    event_id = _event("w1", -1)
    event_service.mark_status(event_id, "WATCHED", "LIVE")

    assert history_service.watch_stats("7d", "movie")["total"] == 0
    assert history_service.watch_stats("7d", "f1")["total"] == 1


def test_unknown_period_falls_back_to_30_days():
    event_id = _event("w1", -1)
    event_service.mark_status(event_id, "WATCHED", "LIVE")
    _set_watched_at(event_id, 45)

    assert history_service.list_history("bogus") == []
