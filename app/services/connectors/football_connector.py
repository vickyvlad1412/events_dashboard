import os
from datetime import datetime, timedelta, timezone

import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}


def fetch_team_fixtures(team_ids: set[int]) -> list[dict]:
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
            if {item["teams"]["home"]["id"], item["teams"]["away"]["id"]} & team_ids
        )
    return _parse_fixtures(fixtures)


def _get_response(resp: requests.Response) -> list[dict]:
    resp.raise_for_status()
    body = resp.json()
    errors = body.get("errors")
    if errors:
        raise RuntimeError(f"API-Football error: {errors}")
    return body.get("response", [])


def _parse_fixtures(fixtures: list[dict]) -> list[dict]:
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
                "priority_tier": "A" if competition == "Premier League" else "B",
                "live_preference": "LIVE",
                "external_source": "api-football",
                "external_id": str(fixture["id"]),
            }
        )
    return events
