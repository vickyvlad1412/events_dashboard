import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}

REQUESTS_PER_MINUTE = 10

_request_lock = threading.Lock()
_recent_requests: deque[float] = deque()


def _get(path: str, params: dict) -> list[dict]:
    with _request_lock:
        now = time.monotonic()
        while _recent_requests and now - _recent_requests[0] >= 60:
            _recent_requests.popleft()
        if len(_recent_requests) >= REQUESTS_PER_MINUTE:
            time.sleep(60 - (now - _recent_requests[0]) + 0.5)
            _recent_requests.popleft()
        _recent_requests.append(time.monotonic())
    resp = requests.get(f"{API_FOOTBALL_BASE_URL}{path}", headers=HEADERS, params=params, timeout=10)
    return _get_response(resp)


PREMIER_LEAGUE_ID = 39
CHAMPIONS_LEAGUE_ID = 2
INTERNATIONAL_TOURNAMENT_IDS = {1, 4, 6, 9}

CATALOG_SEASONS = {
    39: 2024, 140: 2024, 135: 2024, 78: 2024, 61: 2024, 88: 2024, 94: 2024, 40: 2024,
    179: 2024, 71: 2024, 253: 2024, 307: 2024, 2: 2024,
    1: 2022, 4: 2024, 9: 2024, 6: 2023,
}


def fetch_league_teams(league_id: int, season: int) -> list[dict]:
    return [_catalog_team(item["team"]) for item in _get("/teams", {"league": league_id, "season": season})]


def search_teams(query: str) -> list[dict]:
    return [_catalog_team(item["team"]) for item in _get("/teams", {"search": query})]


def _catalog_team(team: dict) -> dict:
    detail = "National team" if team.get("national") else team.get("country")
    return {
        "external_id": str(team["id"]),
        "name": team["name"],
        "detail": detail,
        "image_url": team.get("logo"),
    }


def fetch_fixture_window() -> list[dict]:
    today = datetime.now(timezone.utc).date()
    fixtures = []
    for offset in (-1, 0, 1):
        fixtures.extend(_get("/fixtures", {"date": (today + timedelta(days=offset)).isoformat(), "timezone": "UTC"}))
    return fixtures


def select_fixtures(
    fixtures: list[dict], team_ids: set[int], extra_league_ids: set[int] = frozenset()
) -> list[dict]:
    selected = [
        item for item in fixtures if _is_followed(item, team_ids) or item["league"]["id"] in extra_league_ids
    ]
    return _parse_fixtures(selected, team_ids)


def fetch_team_fixtures(team_ids: set[int], extra_league_ids: set[int] = frozenset()) -> list[dict]:
    return select_fixtures(fetch_fixture_window(), team_ids, extra_league_ids)


def teams_from_fixtures(fixtures: list[dict]) -> list[dict]:
    teams = {}
    for item in fixtures:
        country = (item.get("league") or {}).get("country")
        for side in ("home", "away"):
            team = item["teams"][side]
            teams[team["id"]] = {
                "external_id": str(team["id"]),
                "name": team["name"],
                "detail": country if country and country != "World" else None,
                "image_url": team.get("logo"),
            }
    return list(teams.values())


def _is_followed(item: dict, team_ids: set[int]) -> bool:
    return bool({item["teams"]["home"]["id"], item["teams"]["away"]["id"]} & team_ids)


def _get_response(resp: requests.Response) -> list[dict]:
    resp.raise_for_status()
    body = resp.json()
    errors = body.get("errors")
    if errors:
        raise RuntimeError(f"API-Football error: {errors}")
    return body.get("response", [])


def _priority(item: dict, team_ids: set[int]) -> str:
    if not _is_followed(item, team_ids):
        return "C"
    return "A" if item["league"]["id"] == PREMIER_LEAGUE_ID else "B"


def _image(item: dict, team_ids: set[int]) -> str | None:
    for side in ("home", "away"):
        team = item["teams"][side]
        if team["id"] in team_ids and team.get("logo"):
            return team["logo"]
    return (item.get("league") or {}).get("logo")


def _parse_fixtures(fixtures: list[dict], team_ids: set[int]) -> list[dict]:
    now = datetime.now(timezone.utc)
    events = []
    for item in fixtures:
        fixture = item["fixture"]
        teams = item["teams"]
        league = item["league"]

        start = datetime.fromisoformat(fixture["date"].replace("Z", "+00:00"))
        if start < now:
            continue

        home = teams["home"]["name"]
        away = teams["away"]["name"]
        venue = (fixture.get("venue") or {}).get("name")
        competition = league.get("name")

        events.append(
            {
                "category": "football",
                "title": f"{home} vs {away}",
                "subtitle": competition,
                "event_datetime_utc": start,
                "venue": venue,
                "priority_tier": _priority(item, team_ids),
                "live_preference": "LIVE",
                "external_source": "api-football",
                "external_id": str(fixture["id"]),
                "image_url": _image(item, team_ids),
            }
        )
    return events
