from datetime import datetime, timezone

import requests

OPENF1_BASE_URL = "https://api.openf1.org/v1"

QUALIFYING_SESSIONS = {"Qualifying", "Sprint Qualifying", "Sprint Shootout"}


def _session_kind(session: dict) -> str:
    name = session.get("session_name", "")
    if name.startswith("Practice"):
        return "practice"
    if name.startswith("Day"):
        return "testing"
    if name in QUALIFYING_SESSIONS:
        return "qualifying"
    return "race"


def _fetch_meetings(year: int) -> dict[int, dict]:
    try:
        resp = requests.get(f"{OPENF1_BASE_URL}/meetings", params={"year": year}, timeout=10)
        resp.raise_for_status()
        return {meeting["meeting_key"]: meeting for meeting in resp.json()}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        print(f"[f1_connector] couldn't fetch meetings ({exc}); using country names.")
        return {}


def fetch_upcoming_sessions(year: int) -> list[dict]:
    resp = requests.get(f"{OPENF1_BASE_URL}/sessions", params={"year": year}, timeout=10)
    resp.raise_for_status()
    sessions = resp.json()
    meetings = _fetch_meetings(year)

    now = datetime.now(timezone.utc)
    events = []
    for session in sessions:
        start = datetime.fromisoformat(session["date_start"].replace("Z", "+00:00"))
        if start < now or session.get("is_cancelled"):
            continue

        session_type = session.get("session_name", "Session")
        kind = _session_kind(session)
        event_name = "Pre-Season Testing" if kind == "testing" else "GP"
        meeting = meetings.get(session.get("meeting_key"), {})
        fallback_group = f"{session.get('country_name', '')} {'Pre-Season Testing' if kind == 'testing' else 'Grand Prix'}"

        events.append(
            {
                "category": "f1",
                "title": f"{session.get('country_name', '')} {event_name} — {session_type}",
                "subtitle": session.get("circuit_short_name"),
                "event_datetime_utc": start,
                "venue": session.get("location"),
                "priority_tier": "D" if kind == "practice" else "A",
                "live_preference": "LIVE",
                "external_source": "openf1",
                "external_id": str(session["session_key"]),
                "session_kind": kind,
                "group_key": f"openf1-meeting-{session['meeting_key']}" if session.get("meeting_key") else None,
                "group_title": meeting.get("meeting_name") or fallback_group.strip(),
                "image_url": meeting.get("circuit_image"),
            }
        )
    return events
