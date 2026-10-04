import json
import time
from datetime import datetime, timedelta, timezone

import requests

from app.config import MOVIE_REGION
from app.db import get_connection
from app.services.connectors import anilist_connector, tmdb_connector

DETAILS_TTL = timedelta(hours=12)
LIST_TTL_SECONDS = 3600

_list_cache: dict[str, tuple[float, list[dict]]] = {}


def _cached(source: str, external_id: str) -> tuple[dict | None, bool]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM media_cache WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
    if not row:
        return None, False
    fresh = datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - DETAILS_TTL
    return json.loads(row["data_json"]), fresh


def _store(source: str, external_id: str, data: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO media_cache (source, external_id, data_json, fetched_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET data_json = excluded.data_json, fetched_at = excluded.fetched_at
            """,
            (source, external_id, json.dumps(data), datetime.now(timezone.utc).isoformat()),
        )


def _details(source: str, external_id: str, fetch) -> dict | None:
    if not external_id.isdigit():
        return None
    cached, fresh = _cached(source, external_id)
    if cached and fresh:
        return cached
    try:
        data = fetch(external_id)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"[media_service] couldn't fetch {source} {external_id}: {exc}")
        return cached
    if data:
        _store(source, external_id, data)
    return data or cached


def anime_details(media_id: str) -> dict | None:
    return _details("anilist", str(media_id), anilist_connector.get_anime_details)


def movie_details(movie_id: str) -> dict | None:
    return _details("tmdb", str(movie_id), lambda mid: tmdb_connector.get_movie_details(mid, MOVIE_REGION))


def _cached_list(key: str, fetch) -> list[dict]:
    cached = _list_cache.get(key)
    if cached and time.monotonic() - cached[0] < LIST_TTL_SECONDS:
        return cached[1]
    results = fetch()
    _list_cache[key] = (time.monotonic(), results)
    return results


def now_showing() -> list[dict]:
    return _cached_list("now_playing", lambda: tmdb_connector.now_playing(MOVIE_REGION))


def upcoming_movies() -> list[dict]:
    return _cached_list("upcoming", lambda: tmdb_connector.upcoming(MOVIE_REGION))


def seasonal_anime(year: int, season: str, sort: str) -> list[dict]:
    return _cached_list(
        f"anime:{year}:{season}:{sort}",
        lambda: anilist_connector.fetch_top_seasonal_anime(year, season, 10, sort),
    )


def media_id_for_event(event: dict) -> str | None:
    external_id = event.get("external_id") or ""
    if event.get("external_source") == "anilist":
        return external_id.split("-", 1)[0] or None
    if event.get("external_source") == "tmdb":
        return external_id or None
    return None
