from datetime import datetime, timedelta, timezone

import pytest

from app.config import APP_TIMEZONE
from app.services import dashboard_service, event_service

pytestmark = pytest.mark.usefixtures("temp_db")


def _event(external_id, hours_from_now, tier="A", category="f1", **overrides):
    event_service.upsert_external_event({
        "category": category,
        "title": f"Event {external_id}",
        "event_datetime_utc": datetime.now(timezone.utc) + timedelta(hours=hours_from_now),
        "priority_tier": tier,
        "external_source": "test",
        "external_id": external_id,
        **overrides,
    })


def test_overview_counts_window_and_excludes_background_and_past():
    _event("a", 5, "A")
    _event("b", 30, "B", "movie")
    _event("practice", 6, "D")
    _event("far", 24 * 20, "A")
    _event("past", -5, "A", status="MISSED")

    overview = dashboard_service.overview(7)

    assert overview["total"] == 2
    assert overview["by_tier"] == {"A": 1, "B": 1, "C": 0, "D": 0}
    assert overview["by_category"]["f1"] == 1 and overview["by_category"]["movie"] == 1
    assert (overview["catchup_total"], overview["catchup_important"]) == (1, 1)


def test_featured_groups_sessions_of_same_weekend():
    _event("tier-b", 1, "B", "movie")
    _event("quali", 10, "A", group_key="gp-1", group_title="Singapore Grand Prix", venue="Singapore")
    _event("race", 34, "A", group_key="gp-1", group_title="Singapore Grand Prix", venue="Singapore")
    _event("practice", 8, "D", group_key="gp-1", group_title="Singapore Grand Prix")
    _event("next-gp", 24 * 14, "A", group_key="gp-2", group_title="Austin")

    featured = dashboard_service.featured_event()

    assert featured["title"] == "Singapore Grand Prix"
    assert [s["external_id"] for s in featured["sessions"]] == ["quali", "race"]


def test_featured_falls_back_to_non_tier_a_and_none():
    assert dashboard_service.featured_event() is None
    _event("movie", 3, "B", "movie")
    assert dashboard_service.featured_event()["title"] == "Event movie"


def test_next_event_skips_background_and_watched():
    _event("practice", 1, "D")
    _event("watched", 2, "A", status="WATCHED")
    _event("next", 3, "B")
    assert dashboard_service.next_event()["external_id"] == "next"


def test_countdown_labels():
    _event("soon", 0.01)
    _event("future", 24 * 3 + 1)
    by_id = {e["external_id"]: e for e in dashboard_service.upcoming(7)}
    today = datetime.now(timezone.utc).astimezone(APP_TIMEZONE).date()
    assert by_id["soon"]["countdown"] in ("Today", "Tomorrow")
    assert by_id["future"]["days_until"] == (by_id["future"]["local_datetime"].date() - today).days


def test_range_bounds_weekend_contains_today_on_weekends():
    start, end = dashboard_service.range_bounds("weekend")
    assert end - start == timedelta(days=2)
    assert start.astimezone(APP_TIMEZONE).weekday() == 5
    now = datetime.now(timezone.utc)
    if now.astimezone(APP_TIMEZONE).weekday() in (5, 6):
        assert start <= now < end
    else:
        assert now < start


def test_range_bounds_days():
    start, end = dashboard_service.range_bounds("7d")
    assert end - start == timedelta(days=7)
    assert start.astimezone(APP_TIMEZONE).hour == 0


def test_category_counts_match_category_pages_and_movie_horizon():
    _event("movie-soon", 24 * 11, "B", "movie")
    _event("movie-far", 24 * 72, "B", "movie")
    _event("movie-too-far", 24 * 400, "B", "movie")
    _event("f1-in", 24 * 50, "A")
    _event("f1-out", 24 * 72, "A")
    _event("f1-practice", 24 * 2, "D")
    _event("f1-watched", 24 * 3, "A", status="WATCHED")

    counts = dashboard_service.category_counts()

    assert counts["movie"] == 2
    assert counts["f1"] == 2
    for category, count in counts.items():
        assert count == len(dashboard_service.category_upcoming(category))


def test_month_dots_orders_categories():
    _event("m", 1, "B", "movie")
    _event("f", 1, "A", "f1")
    day = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(APP_TIMEZONE)
    assert dashboard_service.month_dots(day.year, day.month)[day.day] == ["f1", "movie"]


def test_search_events_and_follows():
    _event("gp", 10, "A", group_title="Singapore Grand Prix")
    _event("old", -24 * 30, "A", title="Singapore GP 2025")
    event_service.follow_entity("dota", "Team Spirit", "team", "Team Spirit")

    results = dashboard_service.search("singapore")
    assert [e["external_id"] for e in results["events"]] == ["gp", "old"]
    assert dashboard_service.search("spirit")["follows"][0]["name"] == "Team Spirit"
    assert dashboard_service.search("s") == {"events": [], "follows": []}
