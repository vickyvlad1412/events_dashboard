import threading
from datetime import datetime, timedelta, timezone

import pytest

import app.db
from app import scheduler
from app.db import get_connection
from app.services import dashboard_service, event_service
from app.services.connectors import anilist_connector, football_connector

pytestmark = pytest.mark.usefixtures("temp_db")


def _setting_id(key):
    with get_connection() as conn:
        return conn.execute("SELECT id FROM interest_settings WHERE setting_key = ?", (key,)).fetchone()["id"]


def _event(external_id, hours, rule_key, tier="A", category="f1", source="test", **overrides):
    event_service.upsert_external_event({
        "category": category,
        "title": f"Event {external_id}",
        "event_datetime_utc": datetime.now(timezone.utc) + timedelta(hours=hours),
        "priority_tier": tier,
        "external_source": source,
        "external_id": external_id,
        "rule_key": rule_key,
        **overrides,
    })
    with get_connection() as conn:
        return conn.execute("SELECT * FROM events WHERE external_id = ?", (external_id,)).fetchone()


def _row(external_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM events WHERE external_id = ?", (external_id,)).fetchone()


def test_default_rules_and_migration_is_idempotent():
    app.db.migrate_tier_rules()
    rules = event_service.rule_tiers()
    assert rules["f1_race"] == "A"
    assert rules["f1_practice"] is None
    assert rules["football_other_pl"] is None
    assert rules["football_followed_pl"] == "A"
    assert rules["dota_tier1"] == "C"
    assert rules["anime_episodes"] == "B"


def test_migration_maps_disabled_toggles_to_off():
    with get_connection() as conn:
        conn.execute("UPDATE interest_settings SET tier = NULL, enabled = 0 WHERE setting_key = 'dota_ti'")
        conn.execute("UPDATE interest_settings SET tier = NULL, enabled = 1 WHERE setting_key = 'dota_tier1'")
    app.db.migrate_tier_rules()
    rules = event_service.rule_tiers()
    assert rules["dota_ti"] is None
    assert rules["dota_tier1"] == "C"


def test_changing_a_rule_retiers_existing_events_but_not_locked_or_watched():
    _event("race", 5, "f1_race")
    _event("locked", 6, "f1_race")
    _event("watched", -5, "f1_race", status="WATCHED")
    locked_id = _row("locked")["id"]
    event_service.set_event_tier(locked_id, "B")

    event_service.set_rule_tier(_setting_id("f1_race"), "D")

    assert _row("race")["priority_tier"] == "D"
    assert _row("locked")["priority_tier"] == "B"
    assert _row("watched")["priority_tier"] == "A"


def test_turning_a_rule_off_removes_upcoming_and_clears_catchup():
    _event("soon", 5, "f1_race")
    _event("missed", -5, "f1_race", status="MISSED")
    _event("seen", -6, "f1_race", status="WATCHED")
    _event("other", 5, "f1_qualifying")

    change = event_service.set_rule_tier(_setting_id("f1_race"), "off")

    assert change["previous"] == "A" and change["tier"] == "off"
    assert _row("soon") is None
    assert _row("missed")["status"] == "COMPLETED"
    assert _row("seen")["status"] == "WATCHED"
    assert _row("other") is not None
    assert event_service.rule_tiers()["f1_race"] is None


def test_locked_tier_survives_sync_and_can_reset_to_rule():
    event_id = _event("race", 5, "f1_race")["id"]
    event_service.set_event_tier(event_id, "D")
    _event("race", 5, "f1_race", tier="A")
    assert (_row("race")["priority_tier"], _row("race")["tier_locked"]) == ("D", 1)

    event_service.set_event_tier(event_id, None)
    assert (_row("race")["priority_tier"], _row("race")["tier_locked"]) == ("A", 0)


def test_details_are_stored_and_kept_when_missing():
    _event("match", 5, "dota_tier1", details={"best_of": "Bo3"})
    _event("match", 5, "dota_tier1")
    assert event_service.get_event(_row("match")["id"])["details"] == {"best_of": "Bo3"}


@pytest.mark.parametrize(
    "followed, league_id, overrides, expected",
    [
        (True, football_connector.PREMIER_LEAGUE_ID, {}, "football_followed_pl"),
        (True, football_connector.CHAMPIONS_LEAGUE_ID, {}, "football_followed_other"),
        (True, football_connector.CHAMPIONS_LEAGUE_ID, {"football_followed_other": None}, "football_champions_league"),
        (False, football_connector.CHAMPIONS_LEAGUE_ID, {}, "football_champions_league"),
        (False, football_connector.PREMIER_LEAGUE_ID, {}, None),
        (False, football_connector.PREMIER_LEAGUE_ID, {"football_other_pl": "C"}, "football_other_pl"),
        (False, 999, {}, None),
    ],
)
def test_football_rule(followed, league_id, overrides, expected):
    rules = {**event_service.rule_tiers(), **overrides}
    assert scheduler._football_rule({"followed": followed, "league_id": league_id}, rules) == expected


@pytest.mark.parametrize(
    "media, note",
    [
        ({"startDate": {"year": 2027, "month": 1}}, "Expected Jan 2027"),
        ({"startDate": {"year": 2027}, "season": "WINTER", "seasonYear": 2027}, "Expected Winter 2027"),
        ({"startDate": {"year": 2027}}, "Expected 2027"),
        ({"startDate": {}}, "Date TBD"),
    ],
)
def test_anime_expected_notes(media, note):
    assert anilist_connector._expected_note(media) == note


def test_anime_premiere_with_full_date_becomes_event():
    media = {
        "id": 5, "title": {"english": "New Show", "romaji": None}, "status": "NOT_YET_RELEASED",
        "startDate": {"year": 2027, "month": 1, "day": 9}, "nextAiringEpisode": None,
    }
    event = anilist_connector._event_for(media)
    assert (event["external_id"], event["subtitle"]) == ("5-premiere", "Premiere")


def test_coming_later_lists_tbd_follows_and_far_releases():
    event_service.follow_entity("movie", "Avatar 4", "movie", "100")
    event_service.follow_entity("movie", "Untitled Film", "movie", "200")
    event_service.follow_entity("movie", "Soon Film", "movie", "300")
    for follow in event_service.list_follows("movie"):
        if follow["external_id"] == "200":
            event_service.set_follow_note(follow["id"], "In Production · release date TBD")
    _event("100", 24 * 900, "movie_releases", "B", "movie", "tmdb", title="Avatar 4")
    _event("300", 24 * 20, "movie_releases", "B", "movie", "tmdb", title="Soon Film")

    later = dashboard_service.coming_later("movie")

    assert [(item["name"], item["date"] is None) for item in later] == [("Avatar 4", False), ("Untitled Film", True)]
    assert later[1]["note"] == "In Production · release date TBD"
    assert dashboard_service.coming_later("f1") == []


def test_featured_events_one_slide_per_weekend_within_14_days():
    _event("q", 10, "f1_race", group_key="gp-1", group_title="Singapore Grand Prix")
    _event("r", 34, "f1_race", group_key="gp-1", group_title="Singapore Grand Prix")
    _event("m", 50, "football_followed_pl", category="football")
    _event("far", 24 * 20, "f1_race")

    slides = dashboard_service.featured_events(14)

    assert [s["title"] for s in slides] == ["Singapore Grand Prix", "Event m"]
    assert len(slides[0]["sessions"]) == 2


def test_failed_sources_are_reported_and_only_they_retry(monkeypatch):
    calls = []

    def fake(name, fail=False):
        def run(*args):
            calls.append(name)
            if fail:
                raise RuntimeError("Live F1 session in progress")
        return run

    monkeypatch.setattr(scheduler, "_sync_f1", fake("f1", fail=True))
    monkeypatch.setattr(scheduler, "_sync_football", fake("football"))
    monkeypatch.setattr(scheduler, "sync_dota", fake("dota"))
    monkeypatch.setattr(scheduler.follow_service, "backfill_follow_ids", fake("follow backfill"))
    monkeypatch.setattr(scheduler, "_sync_movies", fake("movies"))
    monkeypatch.setattr(scheduler, "_sync_anime", fake("anime"))

    assert scheduler.sync_all_sources() == ["f1"]
    assert calls == list(scheduler.SOURCES)
    assert app.db.get_meta(scheduler.LAST_SYNC_KEY)

    calls.clear()
    app.db.set_meta(scheduler.LAST_SYNC_KEY, "2026-01-01T00:00:00+00:00")
    assert scheduler.sync_all_sources(("f1",)) == ["f1"]
    assert calls == ["f1"]
    assert app.db.get_meta(scheduler.LAST_SYNC_KEY) == "2026-01-01T00:00:00+00:00"


def test_only_one_sync_runs_at_a_time(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_sync(only=None):
        started.set()
        release.wait(5)

    monkeypatch.setattr(scheduler, "sync_all_sources", slow_sync)
    first = threading.Thread(target=scheduler.run_sync)
    first.start()
    started.wait(5)
    try:
        assert scheduler.sync_status()["running"] is True
        assert scheduler.run_sync() is False
        assert scheduler.start_background_sync() is False
    finally:
        release.set()
        first.join(5)
    assert scheduler.sync_status()["running"] is False
