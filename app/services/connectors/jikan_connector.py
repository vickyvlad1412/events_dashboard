from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

JIKAN_BASE_URL = "https://api.jikan.moe/v4"

WEEKDAYS = {
    "Mondays": 0, "Tuesdays": 1, "Wednesdays": 2, "Thursdays": 3,
    "Fridays": 4, "Saturdays": 5, "Sundays": 6,
}


def _search_anime(title: str) -> dict | None:
    resp = requests.get(f"{JIKAN_BASE_URL}/anime", params={"q": title, "limit": 1}, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("data", [])
    return results[0] if results else None


def fetch_next_episode(anime_title: str) -> dict | None:
    anime = _search_anime(anime_title)
    if not anime or anime.get("status") != "Currently Airing":
        return None

    broadcast = anime.get("broadcast") or {}
    day_name = broadcast.get("day")
    time_str = broadcast.get("time")
    tz_name = broadcast.get("timezone") or "Asia/Tokyo"

    if not (day_name and time_str and day_name in WEEKDAYS):
        return None

    target_weekday = WEEKDAYS[day_name]
    hour, minute = map(int, time_str.split(":"))
    tz = ZoneInfo(tz_name)

    now_local = datetime.now(tz)
    days_ahead = (target_weekday - now_local.weekday()) % 7
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(
        days=days_ahead
    )
    if candidate < now_local:
        candidate += timedelta(days=7)

    event_dt = candidate.astimezone(timezone.utc)

    return {
        "category": "anime",
        "title": anime["title"],
        "subtitle": "Next episode (estimated from weekly broadcast slot)",
        "event_datetime_utc": event_dt,
        "venue": None,
        "priority_tier": "C",
        "live_preference": "ANYTIME",
        "external_source": "jikan",
        "external_id": f"{anime['mal_id']}-{candidate.date().isoformat()}",
    }


def fetch_top_seasonal_anime(year: int, season: str, limit: int = 10) -> list[dict]:
    resp = requests.get(f"{JIKAN_BASE_URL}/seasons/{year}/{season}", timeout=10)
    resp.raise_for_status()
    anime_list = resp.json().get("data", [])

    ranked = sorted(anime_list, key=lambda a: a.get("score") or 0, reverse=True)
    return [
        {
            "mal_id": a["mal_id"],
            "title": a["title"],
            "score": a.get("score"),
            "synopsis": a.get("synopsis"),
            "mal_url": a.get("url"),
            "image_url": (a.get("images") or {}).get("jpg", {}).get("image_url"),
        }
        for a in ranked[:limit]
    ]
