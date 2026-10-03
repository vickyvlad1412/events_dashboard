from datetime import datetime, timedelta, timezone

import pytest

from app.config import APP_TIMEZONE
from app.services import event_service

pytestmark = pytest.mark.usefixtures("temp_db")


def _external_event(external_id, when, tier="A", **overrides):
    return {
        "category": "f1",
        "title": f"Session {external_id}",
        "event_datetime_utc": when,
        "priority_tier": tier,
        "external_source": "test",
        "external_id": external_id,
        **overrides,
    }


def _next_saturday_noon_utc():
    now_local = datetime.now(timezone.utc).astimezone(APP_TIMEZONE)
    saturday = now_local + timedelta(days=(5 - now_local.weekday()) % 7)
    return saturday.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def test_create_and_list_upcoming():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    event_service.create_event("f1", "Test GP", future, priority_tier="A")

    results = event_service.list_upcoming()
    assert len(results) == 1
    assert results[0]["title"] == "Test GP"


def test_tier_d_hidden_from_upcoming():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    event_service.upsert_external_event(_external_event("race", future, "A"))
    event_service.upsert_external_event(_external_event("practice", future, "D"))

    assert [e["external_id"] for e in event_service.list_upcoming()] == ["race"]


def test_only_a_and_b_go_to_catchup():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    for tier in "ABCD":
        event_service.upsert_external_event(_external_event(tier, past, tier))

    event_service.mark_stale_events_as_missed()

    assert sorted(e["external_id"] for e in event_service.list_catchup_required()) == ["A", "B"]


def test_catchup_required_low_tier_hidden():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    event_service.upsert_external_event(_external_event("c", past, "C", status="CATCHUP_REQUIRED"))

    assert event_service.list_catchup_required() == []


def test_watched_removed_from_weekend():
    saturday = _next_saturday_noon_utc()
    event_service.upsert_external_event(_external_event("watched", saturday))
    event_service.upsert_external_event(_external_event("pending", saturday))
    watched_id = next(e["id"] for e in event_service.list_weekend_events() if e["external_id"] == "watched")

    event_service.mark_status(watched_id, "WATCHED")

    assert [e["external_id"] for e in event_service.list_weekend_events()] == ["pending"]


def test_upsert_updates_tier_but_keeps_status():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    event_service.upsert_external_event(_external_event("s1", future, "C"))
    event_id = event_service.list_upcoming()[0]["id"]
    event_service.mark_status(event_id, "LIVE")

    event_service.upsert_external_event(_external_event("s1", future, "A", status="UPCOMING"))

    event = event_service.list_upcoming()[0]
    assert (event["priority_tier"], event["status"]) == ("A", "LIVE")


def test_remove_upcoming_external_events_keeps_watched():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    event_service.upsert_external_event(_external_event("keep", future))
    event_service.upsert_external_event(_external_event("drop", future))
    keep_id = next(e["id"] for e in event_service.list_upcoming() if e["external_id"] == "keep")
    event_service.mark_status(keep_id, "WATCHED")

    event_service.remove_upcoming_external_events("test", ["keep", "drop"])

    assert event_service.has_external_events("test", "keep")
    assert not event_service.has_external_events("test", "drop")


def test_follow_entity_ignores_duplicates():
    event_service.follow_entity("movie", "Jailer 2", "movie")
    event_service.follow_entity("movie", "  jailer 2 ", "movie")
    event_service.follow_entity("anime", "Jailer 2", "anime")

    assert event_service.list_followed("movie") == ["Jailer 2"]
    assert event_service.list_followed("anime") == ["Jailer 2"]
