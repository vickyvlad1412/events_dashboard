import os
from datetime import datetime, timezone

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


def fetch_upcoming_movie(title: str) -> dict | None:
    resp = requests.get(
        f"{TMDB_BASE_URL}/search/movie",
        params={"api_key": TMDB_API_KEY, "query": title},
        timeout=10,
    )
    resp.raise_for_status()

    today = datetime.now(timezone.utc).date().isoformat()
    movie = next(
        (m for m in resp.json().get("results", []) if (m.get("release_date") or "") >= today),
        None,
    )
    if not movie:
        return None

    event_dt = datetime.strptime(movie["release_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return {
        "category": "movie",
        "title": movie["title"],
        "subtitle": "Theatrical release",
        "event_datetime_utc": event_dt,
        "venue": None,
        "priority_tier": "B",
        "live_preference": "CINEMA",
        "external_source": "tmdb",
        "external_id": str(movie["id"]),
    }
