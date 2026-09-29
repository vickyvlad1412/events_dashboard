from datetime import datetime, timezone

import requests

OPENF1_BASE_URL = "https://api.openf1.org/v1"


def fetch_upcoming_sessions(year: int) -> list[dict]:
    resp = requests.get(f"{OPENF1_BASE_URL}/sessions", params={"year": year}, timeout=10)
    resp.raise_for_status()
    sessions = resp.json()

    now = datetime.now(timezone.utc)
    events = []
    for session in sessions:
        start = datetime.fromisoformat(session["date_start"].replace("Z", "+00:00"))
        if start < now:
            continue

        session_type = session.get("session_name", "Session")  # "Race", "Qualifying", "Practice 1"...
        priority = "A" if session_type in ("Race", "Qualifying") else "C"

        events.append(
            {
                "category": "f1",
                "title": f"{session.get('country_name', '')} GP — {session_type}",
                "subtitle": session.get("circuit_short_name"),
                "event_datetime_utc": start,
                "venue": session.get("location"),
                "priority_tier": priority,
                "live_preference": "LIVE",
                "external_source": "openf1",
                "external_id": str(session["session_key"]),
            }
        )
    return events