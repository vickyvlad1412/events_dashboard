import os
from datetime import datetime, timedelta, timezone

import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w342"
TMDB_BACKDROP_URL = "https://image.tmdb.org/t/p/w1280"
TMDB_PROFILE_URL = "https://image.tmdb.org/t/p/w185"
TMDB_MOVIE_URL = "https://www.themoviedb.org/movie/"
RECENT_RELEASE_DAYS = 183
MAX_SEARCH_PAGES = 2
CAST_SHOWN = 10


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
    release = movie.get("release_date") or ""
    return not release or release >= _earliest_release()


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


def _undated_note(movie: dict) -> str:
    status = movie.get("status")
    if status and status not in ("Released", "Canceled"):
        return f"{status} · release date TBD"
    return "Release date TBD"


def fetch_movie(movie_id: str) -> dict:
    movie = _get(f"/movie/{movie_id}")
    if movie.get("release_date"):
        return {"event": _event(movie), "note": None}
    return {"event": None, "note": _undated_note(movie)}


def fetch_movie_event(movie_id: str) -> dict | None:
    return fetch_movie(movie_id)["event"]


def fetch_movie_by_title(title: str) -> dict | None:
    matches = [movie for movie in _search(title, 8) if movie.get("release_date")]
    return _event(matches[0]) if matches else None


def _listing(movie: dict) -> dict:
    return {
        **_summary(movie),
        "release_date": movie.get("release_date") or None,
        "score": round(movie["vote_average"], 1) if movie.get("vote_average") else None,
        "overview": movie.get("overview"),
    }


def now_playing(region: str) -> list[dict]:
    results = _get("/movie/now_playing", {"region": region}).get("results", [])
    return [_listing(movie) for movie in results]


def upcoming(region: str) -> list[dict]:
    results = _get("/movie/upcoming", {"region": region}).get("results", [])
    today = _today()
    movies = [_listing(movie) for movie in results if (movie.get("release_date") or "") >= today]
    return sorted(movies, key=lambda movie: movie["release_date"] or "9999")


def _release_for_region(movie: dict, region: str) -> tuple[str | None, str | None]:
    for country in (movie.get("release_dates") or {}).get("results", []):
        if country.get("iso_3166_1") != region:
            continue
        dates = sorted(
            country.get("release_dates", []),
            key=lambda item: (item.get("type") not in (3, 2), item.get("release_date") or ""),
        )
        if dates:
            first = dates[0]
            return (first.get("release_date") or "")[:10] or None, first.get("certification") or None
    return None, None


def get_movie_details(movie_id: str, region: str) -> dict | None:
    try:
        movie = _get(f"/movie/{movie_id}", {"append_to_response": "credits,videos,release_dates"})
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise
    credits = movie.get("credits") or {}
    trailer = next(
        (
            video for video in (movie.get("videos") or {}).get("results", [])
            if video.get("site") == "YouTube" and video.get("type") == "Trailer"
        ),
        None,
    )
    local_release, certification = _release_for_region(movie, region)
    return {
        "id": str(movie["id"]),
        "title": movie.get("title"),
        "original_title": movie.get("original_title") if movie.get("original_title") != movie.get("title") else None,
        "tagline": movie.get("tagline") or None,
        "overview": movie.get("overview") or "",
        "status": movie.get("status"),
        "release_date": movie.get("release_date") or None,
        "local_release_date": local_release,
        "certification": certification,
        "runtime": movie.get("runtime") or None,
        "genres": [genre["name"] for genre in movie.get("genres") or []],
        "score": round(movie["vote_average"], 1) if movie.get("vote_average") else None,
        "vote_count": movie.get("vote_count"),
        "languages": [lang.get("english_name") for lang in movie.get("spoken_languages") or [] if lang.get("english_name")],
        "directors": [person["name"] for person in credits.get("crew", []) if person.get("job") == "Director"],
        "cast": [
            {
                "name": person.get("name"),
                "character": person.get("character"),
                "photo_url": f"{TMDB_PROFILE_URL}{person['profile_path']}" if person.get("profile_path") else None,
            }
            for person in credits.get("cast", [])[:CAST_SHOWN]
        ],
        "poster_url": _poster(movie),
        "backdrop_url": f"{TMDB_BACKDROP_URL}{movie['backdrop_path']}" if movie.get("backdrop_path") else None,
        "trailer_url": f"https://www.youtube.com/watch?v={trailer['key']}" if trailer else None,
        "homepage": movie.get("homepage") or None,
        "site_url": f"{TMDB_MOVIE_URL}{movie['id']}",
        "note": None if movie.get("release_date") else _undated_note(movie),
    }
