import os
from datetime import datetime, timezone

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w342"


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"{TMDB_BASE_URL}{path}", params={"api_key": TMDB_API_KEY, **(params or {})}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _is_upcoming(movie: dict) -> bool:
    return (movie.get("release_date") or "") >= _today()


def _poster(movie: dict) -> str | None:
    return f"{TMDB_IMAGE_URL}{movie['poster_path']}" if movie.get("poster_path") else None


def _summary(movie: dict) -> dict:
    release = movie.get("release_date") or ""
    detail = f"Releases {datetime.strptime(release, '%Y-%m-%d'):%d %b %Y}" if release else "Release date TBA"
    return {
        "external_id": str(movie["id"]),
        "name": movie["title"],
        "detail": detail,
        "image_url": _poster(movie),
    }


def _event(movie: dict) -> dict:
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
        "image_url": _poster(movie),
    }


def search_upcoming_movies(query: str, limit: int = 8) -> list[dict]:
    results = _get("/search/movie", {"query": query}).get("results", [])
    return [_summary(movie) for movie in results if _is_upcoming(movie)][:limit]


def get_movie(movie_id: str) -> dict | None:
    try:
        return _summary(_get(f"/movie/{movie_id}"))
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise


def fetch_movie_event(movie_id: str) -> dict | None:
    movie = _get(f"/movie/{movie_id}")
    return _event(movie) if movie.get("release_date") else None


def fetch_upcoming_movie(title: str) -> dict | None:
    results = _get("/search/movie", {"query": title}).get("results", [])
    movie = next((m for m in results if _is_upcoming(m)), None)
    return _event(movie) if movie else None
