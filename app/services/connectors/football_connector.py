import os
from datetime import datetime, timezone

import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}


def fetch_team_fixtures(team_id: int, next_n: int = 15) -> list[dict]:
    resp = requests.get(
        f"{API_FOOTBALL_BASE_URL}/fixtures",
        headers=HEADERS,
        params={"team": team_id, "next": next_n},
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_fixtures(resp.json().get("response", []))


def fetch_league_fixtures(league_id: int, season: int) -> list[dict]:
    resp = requests.get(
        f"{API_FOOTBALL_BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": league_id, "season": season, "status": "NS"},
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_fixtures(resp.json().get("response", []))


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
