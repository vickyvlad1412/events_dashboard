import os
from datetime import datetime, timezone

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


def fetch_upcoming_movies(watch_titles: list[str]) -> list[dict]:
    events = []
    for title in watch_titles:
        resp = requests.get(
            f"{TMDB_BASE_URL}/search/movie",
            params={"api_key": TMDB_API_KEY, "query": title},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            continue

        movie = results[0]  # best match
        release_date = movie.get("release_date")
        if not release_date:
            continue

        event_dt = datetime.strptime(release_date, "%Y-%m-%d").replace(
            hour=0, minute=0, tzinfo=timezone.utc
        )
        events.append(
            {
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
        )
    return events