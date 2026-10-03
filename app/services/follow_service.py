import os
import time
from datetime import datetime, timedelta, timezone

import requests

from app.db import get_meta, set_meta
from app.services import catalog_service, event_service
from app.services.connectors import anilist_connector, dota_connector, football_connector, tmdb_connector

FOLLOW_TYPES = {
    ("dota", "team"): "Dota team",
    ("dota", "player"): "Dota player",
    ("football", "team"): "Football team",
    ("anime", "anime"): "Anime",
    ("movie", "movie"): "Movie",
}
CATALOG_TYPES = {("dota", "team"), ("dota", "player"), ("football", "team")}
FOOTBALL_ENV_TEAMS = {"LIVERPOOL_TEAM_ID": "Liverpool", "BRAZIL_TEAM_ID": "Brazil"}

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
REMOTE_TEAM_SEARCH_MIN_LENGTH = 3
SUGGEST_CACHE_SECONDS = 600
SUGGEST_CACHE_SIZE = 200
CATALOG_REFRESH_HOURS = {"dota": 24, "football": 24 * 7}

_suggest_cache: dict[tuple, tuple[float, list[dict]]] = {}
_remote_team_searches: set[str] = set()


def is_supported(category: str, entity_type: str) -> bool:
    return (category, entity_type) in FOLLOW_TYPES


def clean_query(query: str) -> str:
    return " ".join((query or "").split())[:MAX_QUERY_LENGTH]


def suggest(category: str, entity_type: str, query: str, limit: int = 8) -> list[dict]:
    query = clean_query(query)
    if not is_supported(category, entity_type) or len(query) < MIN_QUERY_LENGTH:
        return []

    if (category, entity_type) in CATALOG_TYPES:
        return [_catalog_entity(row) for row in catalog_service.search(category, entity_type, query, limit)]

    key = (category, query.lower(), limit)
    cached = _suggest_cache.get(key)
    if cached and time.monotonic() - cached[0] < SUGGEST_CACHE_SECONDS:
        return cached[1]

    results = anilist_connector.search_anime(query, limit) if category == "anime" else (
        tmdb_connector.search_movies(query, limit)
    )
    if len(_suggest_cache) >= SUGGEST_CACHE_SIZE:
        _suggest_cache.pop(min(_suggest_cache, key=lambda k: _suggest_cache[k][0]))
    _suggest_cache[key] = (time.monotonic(), results)
    return results


def resolve(category: str, entity_type: str, query: str = "", external_id: str | None = None) -> dict:
    if not is_supported(category, entity_type):
        return {"status": "not_found", "entity": None, "suggestions": []}

    if external_id:
        entity = _lookup(category, entity_type, str(external_id))
        return {"status": "resolved" if entity else "not_found", "entity": entity, "suggestions": []}

    query = clean_query(query)
    result = _resolve_from_suggestions(category, entity_type, query)
    if result["status"] != "resolved" and _remote_team_search(category, entity_type, query):
        result = _resolve_from_suggestions(category, entity_type, query)
    return result


def _remote_team_search(category: str, entity_type: str, query: str) -> bool:
    key = catalog_service.normalize(query)
    if (category, entity_type) != ("football", "team") or len(key) < REMOTE_TEAM_SEARCH_MIN_LENGTH:
        return False
    if key in _remote_team_searches:
        return False
    teams = football_connector.search_teams(query)
    _remote_team_searches.add(key)
    catalog_service.upsert_entities("football", "team", teams)
    return bool(teams)


def _resolve_from_suggestions(category: str, entity_type: str, query: str) -> dict:
    suggestions = suggest(category, entity_type, query)
    if not suggestions:
        return {"status": "not_found", "entity": None, "suggestions": []}

    wanted = catalog_service.normalize(query)
    exact = [
        s for s in suggestions
        if wanted in (catalog_service.normalize(s["name"]), catalog_service.normalize(s.get("short_name") or ""))
    ]
    if len(exact) == 1:
        return {"status": "resolved", "entity": exact[0], "suggestions": suggestions}
    if len(exact) > 1:
        return {"status": "ambiguous", "entity": None, "suggestions": exact}
    if len(suggestions) == 1:
        return {"status": "resolved", "entity": suggestions[0], "suggestions": suggestions}

    active = [s for s in suggestions if s.get("is_active")]
    if (category, entity_type) in CATALOG_TYPES and len(active) == 1:
        return {"status": "resolved", "entity": active[0], "suggestions": suggestions}
    return {"status": "ambiguous", "entity": None, "suggestions": suggestions}


def follow(category: str, entity_type: str, query: str = "", external_id: str | None = None) -> dict:
    try:
        result = resolve(category, entity_type, query, external_id)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"[follow_service] lookup failed for {category}/{entity_type} {query or external_id!r}: {exc}")
        return {"status": "error", "entity": None, "suggestions": [], "follow_id": None}

    if result["status"] != "resolved":
        return {**result, "follow_id": None}

    entity = result["entity"]
    added = event_service.follow_entity(
        category, entity["name"], entity_type, entity["external_id"], entity.get("image_url")
    )
    follow_id = next(
        (f["id"] for f in event_service.list_follows(entity_type, category) if f["external_id"] == entity["external_id"]),
        None,
    )
    return {**result, "status": "added" if added else "already_following", "follow_id": follow_id}


def unfollow(follow_id: int) -> dict | None:
    existing = event_service.get_follow(follow_id)
    if not existing:
        return None
    event_service.unfollow(follow_id)
    external_id = existing.get("external_id")
    if external_id and existing["category_name"] == "anime":
        event_service.remove_unwatched_external_events("anilist", f"{external_id}-%")
    elif external_id and existing["category_name"] == "movie":
        event_service.remove_unwatched_external_events("tmdb", external_id)
    return existing


def backfill_follow_ids() -> None:
    follows = [f for f in event_service.list_follows() if not f["external_id"]]
    for existing in follows:
        follow_type = (existing["category_name"], existing["entity_type"])
        attempt_key = f"follow_backfill_attempted:{existing['id']}"
        if follow_type not in FOLLOW_TYPES or get_meta(attempt_key):
            continue
        try:
            result = resolve(*follow_type, existing["name"])
        except (requests.RequestException, RuntimeError) as exc:
            print(f"[follow_service] couldn't resolve {existing['name']!r} yet: {exc}")
            continue
        if follow_type not in CATALOG_TYPES:
            set_meta(attempt_key, datetime.now(timezone.utc).isoformat())
        if result["status"] != "resolved":
            print(f"[follow_service] {existing['name']!r} is ambiguous or unknown; keeping it as typed.")
            continue

        entity = result["entity"]
        duplicate = any(
            f["external_id"] == entity["external_id"] and f["id"] != existing["id"]
            for f in event_service.list_follows(existing["entity_type"], existing["category_name"])
        )
        if duplicate:
            event_service.unfollow(existing["id"])
        else:
            event_service.update_follow(existing["id"], entity["name"], entity["external_id"], entity.get("image_url"))


def refresh_catalog_follow_details(category: str, entity_type: str) -> None:
    for existing in event_service.list_follows(entity_type, category):
        if not existing["external_id"]:
            continue
        entity = catalog_service.get_entity(category, entity_type, existing["external_id"])
        if entity and (entity["name"], entity["image_url"]) != (existing["name"], existing["image_url"]):
            event_service.update_follow(existing["id"], entity["name"], existing["external_id"], entity["image_url"])


def seed_football_follows_from_env() -> None:
    if get_meta("football_follows_seeded"):
        return
    for env_var, fallback_name in FOOTBALL_ENV_TEAMS.items():
        team_id = (os.environ.get(env_var) or "").strip()
        if team_id.isdigit():
            entity = catalog_service.get_entity("football", "team", team_id)
            name = entity["name"] if entity else fallback_name
            event_service.follow_entity("football", name, "team", team_id, entity and entity["image_url"])
    set_meta("football_follows_seeded", datetime.now(timezone.utc).isoformat())


def _catalog_is_fresh(category: str, part: str | None = None) -> bool:
    last = get_meta(f"catalog_refreshed_at:{category}" + (f":{part}" if part else ""))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CATALOG_REFRESH_HOURS[category])
    return bool(last) and datetime.fromisoformat(last) > cutoff


def refresh_dota_catalog(force: bool = False) -> None:
    if not force and _catalog_is_fresh("dota"):
        return
    for entity_type in ("team", "player"):
        catalog_service.upsert_entities("dota", entity_type, dota_connector.fetch_catalog(entity_type))
    set_meta("catalog_refreshed_at:dota", datetime.now(timezone.utc).isoformat())


def refresh_football_catalog(force: bool = False) -> None:
    for league_id, season in football_connector.CATALOG_SEASONS.items():
        if not force and _catalog_is_fresh("football", str(league_id)):
            continue
        try:
            catalog_service.upsert_entities("football", "team", football_connector.fetch_league_teams(league_id, season))
        except (requests.RequestException, RuntimeError) as exc:
            print(f"[follow_service] couldn't load teams for league {league_id}: {exc}")
            continue
        set_meta(f"catalog_refreshed_at:football:{league_id}", datetime.now(timezone.utc).isoformat())


def _lookup(category: str, entity_type: str, external_id: str) -> dict | None:
    if (category, entity_type) in CATALOG_TYPES:
        row = catalog_service.get_entity(category, entity_type, external_id)
        return _catalog_entity(row) if row else None
    if category == "anime":
        return anilist_connector.get_anime(external_id) if external_id.isdigit() else None
    return tmdb_connector.get_movie(external_id) if external_id.isdigit() else None


def _catalog_entity(row: dict) -> dict:
    detail = row.get("detail") or (row.get("short_name") if row.get("short_name") != row["name"] else None)
    return {
        "external_id": row["external_id"],
        "name": row["name"],
        "short_name": row.get("short_name"),
        "detail": detail,
        "image_url": row.get("image_url"),
        "is_active": bool(row.get("is_active")),
    }
