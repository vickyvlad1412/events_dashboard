from datetime import datetime, timedelta, timezone

from app.services.connectors import f1_connector, football_connector, tmdb_connector


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def _iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_f1_tiers_and_kinds(monkeypatch):
    names = ["Practice 1", "Qualifying", "Sprint Qualifying", "Sprint", "Race", "Day 1"]
    sessions = [
        {"session_key": i, "session_name": name, "date_start": _iso(1), "country_name": "Bahrain"}
        for i, name in enumerate(names)
    ]
    sessions.append({"session_key": 99, "session_name": "Race", "date_start": _iso(2), "is_cancelled": True})
    monkeypatch.setattr(f1_connector.requests, "get", lambda *a, **k: FakeResponse(sessions))

    events = f1_connector.fetch_upcoming_sessions(2026)
    by_name = {e["title"].split(" — ")[1]: e for e in events}

    assert "99" not in [e["external_id"] for e in events]
    assert by_name["Practice 1"]["priority_tier"] == "D"
    assert by_name["Practice 1"]["session_kind"] == "practice"
    for name in ["Qualifying", "Sprint Qualifying", "Sprint", "Race", "Day 1"]:
        assert by_name[name]["priority_tier"] == "A"
    assert by_name["Sprint Qualifying"]["session_kind"] == "qualifying"
    assert by_name["Day 1"]["session_kind"] == "testing"
    assert by_name["Day 1"]["title"] == "Bahrain Pre-Season Testing — Day 1"


def test_tmdb_picks_first_release_in_window(monkeypatch):
    results = [
        {"id": 1, "title": "Ebenezer", "release_date": "1998-10-13"},
        {"id": 2, "title": "Ebenezer", "release_date": ""},
        {"id": 3, "title": "Ebenezer", "release_date": _iso(30)[:10]},
        {"id": 4, "title": "Ebenezer Again", "release_date": _iso(60)[:10]},
    ]
    monkeypatch.setattr(tmdb_connector.requests, "get", lambda *a, **k: FakeResponse({"results": results}))

    assert tmdb_connector.fetch_movie_by_title("Ebenezer")["external_id"] == "3"


def test_tmdb_returns_none_outside_window(monkeypatch):
    results = [{"id": 1, "title": "Dune", "release_date": "2021-09-15"}]
    monkeypatch.setattr(tmdb_connector.requests, "get", lambda *a, **k: FakeResponse({"results": results}))

    assert tmdb_connector.fetch_movie_by_title("Dune") is None


def test_tmdb_search_includes_recent_releases_and_labels_them(monkeypatch):
    results = [
        {"id": 1, "title": "Old", "release_date": _iso(-400)[:10]},
        {"id": 2, "title": "In Cinemas", "release_date": _iso(-20)[:10]},
        {"id": 3, "title": "Edge", "release_date": _iso(-180)[:10]},
        {"id": 4, "title": "Soon", "release_date": _iso(10)[:10]},
        {"id": 5, "title": "No Date", "release_date": ""},
    ]
    monkeypatch.setattr(
        tmdb_connector.requests, "get", lambda *a, **k: FakeResponse({"results": results, "total_pages": 1})
    )

    found = tmdb_connector.search_movies("anything")

    assert [m["external_id"] for m in found] == ["2", "3", "4"]
    assert found[0]["detail"].startswith("Released ")
    assert found[2]["detail"].startswith("Releases ")


def test_tmdb_search_reads_second_page_when_first_is_mostly_old(monkeypatch):
    pages = {
        1: [{"id": i, "title": f"Old {i}", "release_date": "2001-01-01"} for i in range(20)],
        2: [{"id": 99, "title": "New", "release_date": _iso(5)[:10]}],
    }
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse({"results": pages[params["page"]], "total_pages": 5})

    monkeypatch.setattr(tmdb_connector.requests, "get", fake_get)

    assert [m["external_id"] for m in tmdb_connector.search_movies("new")] == ["99"]
    assert calls == [1, 2]


def _fixture(fixture_id, home_id, away_id, league_id):
    return {
        "fixture": {"id": fixture_id, "date": _iso(1), "venue": {"name": "Anfield"}},
        "teams": {"home": {"id": home_id, "name": f"T{home_id}"}, "away": {"id": away_id, "name": f"T{away_id}"}},
        "league": {"id": league_id, "name": f"L{league_id}"},
    }


def test_football_rate_limiter_waits_after_ten_requests(monkeypatch):
    clock = {"now": 1000.0}
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(football_connector, "_recent_requests", football_connector.deque())
    monkeypatch.setattr(football_connector.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(football_connector.time, "sleep", sleep)
    monkeypatch.setattr(
        football_connector.requests, "get", lambda *a, **k: FakeResponse({"errors": [], "response": []})
    )

    for _ in range(10):
        football_connector._get("/teams", {})
        clock["now"] += 1
    assert sleeps == []

    football_connector._get("/teams", {})
    assert len(sleeps) == 1 and 50 < sleeps[0] <= 61


def test_football_followed_and_extra_leagues(monkeypatch):
    fixtures = [
        _fixture(1, 40, 50, football_connector.PREMIER_LEAGUE_ID),
        _fixture(2, 40, 60, football_connector.CHAMPIONS_LEAGUE_ID),
        _fixture(3, 70, 80, football_connector.CHAMPIONS_LEAGUE_ID),
        _fixture(4, 90, 91, 999),
    ]
    monkeypatch.setattr(
        football_connector.requests, "get", lambda *a, **k: FakeResponse({"errors": [], "response": fixtures})
    )

    events = football_connector.fetch_team_fixtures({40}, {football_connector.CHAMPIONS_LEAGUE_ID})
    tiers = {e["external_id"]: e["priority_tier"] for e in events}

    assert tiers == {"1": "A", "2": "B", "3": "C"}
