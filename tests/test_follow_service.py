from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.db import get_meta
from app.services import catalog_service, event_service, follow_service

pytestmark = pytest.mark.usefixtures("temp_db")

DOTA_TEAMS = [
    {"external_id": "Team Spirit", "name": "Team Spirit", "short_name": "Spirit"},
    {"external_id": "Spirit Academy", "name": "Spirit Academy"},
    {"external_id": "Team Liquid", "name": "Team Liquid", "short_name": "Liquid"},
    {"external_id": "OG", "name": "OG"},
    {"external_id": "Nigma Galaxy", "name": "Nigma Galaxy"},
]


@pytest.fixture
def dota_catalog():
    catalog_service.upsert_entities("dota", "team", DOTA_TEAMS)
    catalog_service.mark_active("dota", "team", {"Team Spirit", "OG"})


@pytest.fixture(autouse=True)
def clear_suggest_cache(monkeypatch):
    monkeypatch.setattr(follow_service, "_suggest_cache", {})


@pytest.mark.parametrize(
    "query, expected_first",
    [("spirit", "Team Spirit"), ("Spirit", "Team Spirit"), ("team spi", "Team Spirit"), ("liq", "Team Liquid"),
     ("og", "OG"), ("nigmagalaxy", "Nigma Galaxy"), ("NIGMA", "Nigma Galaxy")],
)
def test_catalog_search_ranking(dota_catalog, query, expected_first):
    assert catalog_service.search("dota", "team", query)[0]["name"] == expected_first


def test_catalog_search_short_and_unknown_queries(dota_catalog):
    assert catalog_service.search("dota", "team", "s") == []
    assert catalog_service.search("dota", "team", "zzzz") == []


def test_catalog_upsert_keeps_active_flag_and_short_name(dota_catalog):
    catalog_service.upsert_entities("dota", "team", [{"external_id": "Team Spirit", "name": "Team Spirit"}])
    entity = catalog_service.get_entity("dota", "team", "Team Spirit")
    assert (entity["is_active"], entity["short_name"]) == (1, "Spirit")


def test_resolve_prefers_exact_short_name(dota_catalog):
    result = follow_service.resolve("dota", "team", "spirit")
    assert (result["status"], result["entity"]["name"]) == ("resolved", "Team Spirit")


def test_resolve_ambiguous_without_exact_or_single_active(dota_catalog):
    catalog_service.mark_active("dota", "team", {"Spirit Academy"})
    result = follow_service.resolve("dota", "team", "spir")
    assert result["status"] == "ambiguous"
    assert [s["name"] for s in result["suggestions"]][:2] == ["Team Spirit", "Spirit Academy"]


def test_resolve_single_active_candidate_wins(dota_catalog):
    result = follow_service.resolve("dota", "team", "spir")
    assert (result["status"], result["entity"]["name"]) == ("resolved", "Team Spirit")


def test_resolve_not_found_and_unsupported(dota_catalog):
    assert follow_service.resolve("dota", "team", "zzzz")["status"] == "not_found"
    assert follow_service.resolve("f1", "team", "Ferrari")["status"] == "not_found"


def test_follow_dedupes_on_canonical_entity(dota_catalog):
    first = follow_service.follow("dota", "team", "spirit")
    second = follow_service.follow("dota", "team", "Team Spirit")
    third = follow_service.follow("dota", "team", external_id="Team Spirit")

    assert [first["status"], second["status"], third["status"]] == ["added", "already_following", "already_following"]
    assert event_service.list_followed("team", "dota") == ["Team Spirit"]
    assert first["follow_id"] == second["follow_id"]


def test_follow_with_unknown_external_id(dota_catalog):
    assert follow_service.follow("dota", "team", external_id="Made Up Team")["status"] == "not_found"
    assert event_service.list_follows() == []


def test_follow_reports_api_errors(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(follow_service.anilist_connector, "search_anime", fail)
    assert follow_service.follow("anime", "anime", "frieren")["status"] == "error"


def test_anime_suggestions_are_cached(monkeypatch):
    calls = []

    def search(query, limit):
        calls.append(query)
        return [{"external_id": "1", "name": "Frieren", "detail": "TV", "image_url": None}]

    monkeypatch.setattr(follow_service.anilist_connector, "search_anime", search)
    follow_service.suggest("anime", "anime", "frieren")
    follow_service.suggest("anime", "anime", "  Frieren ")

    assert calls == ["frieren"]


def test_anime_exact_title_resolves(monkeypatch):
    results = [
        {"external_id": "1", "name": "Frieren: Beyond Journey's End", "detail": "TV", "image_url": None},
        {"external_id": "2", "name": "Chainsaw Man", "detail": "TV", "image_url": None},
    ]
    monkeypatch.setattr(follow_service.anilist_connector, "search_anime", lambda q, limit: results)

    assert follow_service.resolve("anime", "anime", "chainsaw man")["entity"]["external_id"] == "2"
    assert follow_service.resolve("anime", "anime", "frieren man")["status"] == "ambiguous"


def test_unfollow_anime_removes_unwatched_events_only(monkeypatch):
    event_service.follow_entity("anime", "Chainsaw Man", "anime", "127230")
    follow_id = event_service.list_follows("anime")[0]["id"]
    now = datetime.now(timezone.utc)
    for external_id, status, offset in [
        ("127230-ep5", "UPCOMING", 2), ("127230-ep4", "MISSED", -5), ("127230-ep3", "WATCHED", -12),
        ("1272300-ep1", "UPCOMING", 3),
    ]:
        event_service.upsert_external_event({
            "category": "anime", "title": external_id, "event_datetime_utc": now + timedelta(days=offset),
            "external_source": "anilist", "external_id": external_id, "status": status,
        })

    follow_service.unfollow(follow_id)

    assert event_service.list_follows() == []
    assert event_service.has_external_events("anilist", "127230-ep3")
    assert not event_service.has_external_events("anilist", "127230-ep4")
    assert not event_service.has_external_events("anilist", "127230-ep5")
    assert event_service.has_external_events("anilist", "1272300-ep1")


def test_unfollow_unknown_id():
    assert follow_service.unfollow(999) is None


def test_backfill_resolves_legacy_follows_and_drops_duplicates(dota_catalog):
    event_service.follow_entity("dota", "Team Spirit", "team", "Team Spirit")
    event_service.follow_entity("dota", "spirit", "team")
    event_service.follow_entity("dota", "og", "team")
    event_service.follow_entity("dota", "zzzz", "team")

    follow_service.backfill_follow_ids()
    follow_service.backfill_follow_ids()

    follows = {f["name"]: f["external_id"] for f in event_service.list_follows("team", "dota")}
    assert follows == {"OG": "OG", "Team Spirit": "Team Spirit", "zzzz": None}


def test_seed_football_follows_once(monkeypatch):
    monkeypatch.setenv("LIVERPOOL_TEAM_ID", "40")
    monkeypatch.setenv("BRAZIL_TEAM_ID", "not-a-number")
    catalog_service.upsert_entities("football", "team", [{"external_id": "40", "name": "Liverpool", "image_url": "l.png"}])

    follow_service.seed_football_follows_from_env()
    follows = event_service.list_follows("team", "football")
    assert [(f["name"], f["external_id"], f["image_url"]) for f in follows] == [("Liverpool", "40", "l.png")]

    event_service.unfollow(follows[0]["id"])
    follow_service.seed_football_follows_from_env()
    assert event_service.list_follows("team", "football") == []
    assert get_meta("football_follows_seeded")


def test_football_remote_search_only_when_no_local_match(monkeypatch):
    monkeypatch.setattr(follow_service, "_remote_team_searches", set())
    calls = []

    def search_teams(query):
        calls.append(query)
        return [
            {"external_id": "40", "name": "Liverpool", "detail": "England", "image_url": None},
            {"external_id": "1847", "name": "Liverpool W", "detail": "England", "image_url": None},
        ]

    monkeypatch.setattr(follow_service.football_connector, "search_teams", search_teams)
    catalog_service.upsert_entities("football", "team", [{"external_id": "1847", "name": "Liverpool W"},
                                                         {"external_id": "2358", "name": "Liverpool Montevideo"}])

    first = follow_service.resolve("football", "team", "liverpool")
    second = follow_service.resolve("football", "team", "Liverpool")
    local = follow_service.resolve("football", "team", "liverpool montevideo")

    assert (first["status"], first["entity"]["external_id"]) == ("resolved", "40")
    assert second["entity"]["external_id"] == "40"
    assert local["entity"]["external_id"] == "2358"
    assert calls == ["liverpool"]


def test_football_remote_search_failure_can_retry(monkeypatch):
    monkeypatch.setattr(follow_service, "_remote_team_searches", set())
    catalog_service.upsert_entities("football", "team", [{"external_id": "1", "name": "Arsenal W"},
                                                         {"external_id": "2", "name": "Arsenal Tula"}])

    def fail(query):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(follow_service.football_connector, "search_teams", fail)
    assert follow_service.follow("football", "team", "arsenal")["status"] == "error"
    monkeypatch.setattr(follow_service.football_connector, "search_teams",
                        lambda q: [{"external_id": "42", "name": "Arsenal", "detail": "England", "image_url": None}])
    assert follow_service.follow("football", "team", "arsenal")["status"] == "added"


def test_refresh_football_catalog_tolerates_partial_failures(monkeypatch):
    def league_teams(league_id, season):
        if league_id == 39:
            raise requests.ConnectionError("down")
        return [{"external_id": f"{league_id}-1", "name": f"Team {league_id}"}]

    monkeypatch.setattr(follow_service.football_connector, "fetch_league_teams", league_teams)
    follow_service.refresh_football_catalog(force=True)

    assert catalog_service.count("football", "team") == len(follow_service.football_connector.CATALOG_SEASONS) - 1
    assert get_meta("catalog_refreshed_at:football:140")
    assert get_meta("catalog_refreshed_at:football:39") is None

    retried = []
    monkeypatch.setattr(follow_service.football_connector, "fetch_league_teams",
                        lambda league_id, season: retried.append(league_id) or [])
    follow_service.refresh_football_catalog()
    assert retried == [39]


def test_refresh_catalog_follow_details_updates_names():
    event_service.follow_entity("football", "Brazil", "team", "6")
    catalog_service.upsert_entities("football", "team", [{"external_id": "6", "name": "Brazil", "image_url": "b.png"}])

    follow_service.refresh_catalog_follow_details("football", "team")

    assert event_service.list_follows("team", "football")[0]["image_url"] == "b.png"
