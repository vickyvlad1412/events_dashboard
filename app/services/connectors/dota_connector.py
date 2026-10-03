import os
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

LPDB_API_KEY = os.environ.get("LPDB_API_KEY")

LIQUIPEDIA_API_URL = "https://liquipedia.net/dota2/api.php"
HEADERS = {"User-Agent": "PersonalEventsDashboard/1.0 (personal project; contact: your-email@example.com)"}


def fetch_upcoming_matches() -> list[dict]:
    if LPDB_API_KEY:
        try:
            return _fetch_from_lpdb()
        except Exception as exc:
            print(f"[dota_connector] LPDB fetch failed ({exc}); falling back to MediaWiki.")

    return _fetch_from_mediawiki()


def _fetch_from_lpdb() -> list[dict]:
    import lpdb_python as lpdb

    session = lpdb.LpdbSession(LPDB_API_KEY)
    # Representative shape — confirm the exact method name/signature for
    # querying matches against lpdb_python's current README before relying
    # on this; it's a young wrapper and may not match exactly.
    raw_matches = session.get_match(
        wiki="dota2", conditions="[[date::>now]]", order="date asc", limit=20
    )

    now = datetime.now(timezone.utc)
    events = []
    for raw in raw_matches:
        match = lpdb.Match(raw)
        start = match.date
        if start < now:
            continue
        events.append(
            {
                "category": "dota",
                "title": f"{match.opponent1} vs {match.opponent2}",
                "subtitle": match.tournament,
                "event_datetime_utc": start,
                "venue": None,
                "priority_tier": "C",
                "live_preference": "LIVE",
                "external_source": "lpdb",
                "external_id": str(match.match_id),
            }
        )
    return events


def _fetch_page_html() -> str:
    resp = requests.get(
        LIQUIPEDIA_API_URL,
        headers=HEADERS,
        params={
            "action": "parse",
            "page": "Liquipedia:Upcoming_and_ongoing_matches",
            "format": "json",
            "prop": "text",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["parse"]["text"]["*"]


def _fetch_from_mediawiki() -> list[dict]:
    html = _fetch_page_html()
    soup = BeautifulSoup(html, "html.parser")

    events = []
    # NOTE: this selector is a starting guess, not guaranteed current.
    # Print `html` (or save it to a file and open it in a browser) and
    # inspect the real structure, then adjust the class names below.
    for match_row in soup.select(".infobox_matches_content"):
        team1 = match_row.select_one(".team-left")
        team2 = match_row.select_one(".team-right")
        timer = match_row.select_one(".timer-object")

        if not (team1 and team2 and timer):
            continue

        timestamp = timer.get("data-timestamp")
        if not timestamp:
            continue

        event_dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        title = f"{team1.get_text(strip=True)} vs {team2.get_text(strip=True)}"

        events.append(
            {
                "category": "dota",
                "title": title,
                "subtitle": None,
                "event_datetime_utc": event_dt,
                "venue": None,
                "priority_tier": "C",
                "live_preference": "LIVE",
                "external_source": "liquipedia",
                "external_id": f"{title}-{timestamp}",
            }
        )
    return events
