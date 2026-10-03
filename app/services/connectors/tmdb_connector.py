import os
from datetime import datetime, timedelta, timezone

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w342"
RECENT_RELEASE_DAYS = 183
MAX_SEARCH_PAGES = 2


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"{TMDB_BASE_URL}{path}", params={"api_key": TMDB_API_KEY, **(params or {})}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _earliest_release() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=RECENT_RELEASE_DAYS)).isoformat()


def _in_window(movie: dict) -> bool:
    return (movie.get("release_date") or "") >= _earliest_release()


def _search(query: str, limit: int) -> list[dict]:
    matches = []
    for page in range(1, MAX_SEARCH_PAGES + 1):
        body = _get("/search/movie", {"query": query, "page": page})
        matches += [movie for movie in body.get("results", []) if _in_window(movie)]
        if len(matches) >= limit or page >= body.get("total_pages", 1):
            break
    return matches[:limit]


def _poster(movie: dict) -> str | None:
    return f"{TMDB_IMAGE_URL}{movie['poster_path']}" if movie.get("poster_path") else None


def _summary(movie: dict) -> dict:
    release = movie.get("release_date") or ""
    if release:
        verb = "Releases" if release >= _today() else "Released"
        detail = f"{verb} {datetime.strptime(release, '%Y-%m-%d'):%d %b %Y}"
    else:
        detail = "Release date TBA"
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


def search_movies(query: str, limit: int = 8) -> list[dict]:
    return [_summary(movie) for movie in _search(query, limit)]


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


def fetch_movie_by_title(title: str) -> dict | None:
    matches = _search(title, 1)
    return _event(matches[0]) if matches else None
