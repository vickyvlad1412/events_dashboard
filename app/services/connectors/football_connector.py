import os
from datetime import datetime, timedelta, timezone

import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}


PREMIER_LEAGUE_ID = 39
CHAMPIONS_LEAGUE_ID = 2
INTERNATIONAL_TOURNAMENT_IDS = {1, 4, 6, 9}


def fetch_team_fixtures(team_ids: set[int], extra_league_ids: set[int] = frozenset()) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    fixtures = []
    for offset in (-1, 0, 1):
        resp = requests.get(
            f"{API_FOOTBALL_BASE_URL}/fixtures",
            headers=HEADERS,
            params={"date": (today + timedelta(days=offset)).isoformat(), "timezone": "UTC"},
            timeout=10,
        )
        fixtures.extend(
            item
            for item in _get_response(resp)
            if _is_followed(item, team_ids) or item["league"]["id"] in extra_league_ids
        )
    return _parse_fixtures(fixtures, team_ids)


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
            }
        )
    return events
