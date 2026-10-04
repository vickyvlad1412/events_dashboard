from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import APP_TIMEZONE, CATEGORIES, EVENT_STATUSES, WATCH_MODES
from app.scheduler import start_background_sync, sync_new_follow, sync_status
from app.services import dashboard_service, event_service, follow_service

router = APIRouter(prefix="/api")


class FollowRequest(BaseModel):
    category: str
    entity_type: str
    query: str = ""
    external_id: str | None = None


class StatusRequest(BaseModel):
    status: str
    watched_mode: str | None = None


def _require_follow_type(category: str, entity_type: str) -> None:
    if not follow_service.is_supported(category, entity_type):
        raise HTTPException(status_code=400, detail=f"Can't follow {entity_type!r} in {category!r}.")


def _category_or_none(category: str | None) -> str | None:
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category {category!r}.")
    return category or None


@router.get("/suggest")
def suggest(category: str, type: str, q: str = ""):
    _require_follow_type(category, type)
    try:
        return {"query": follow_service.clean_query(q), "results": follow_service.suggest(category, type, q)}
    except (requests.RequestException, RuntimeError) as exc:
        print(f"[api] suggestions failed for {category}/{type} {q!r}: {exc}")
        raise HTTPException(status_code=503, detail="Suggestions are unavailable right now.")


@router.get("/follows")
def list_follows(category: str | None = None):
    return {"follows": event_service.list_follows(category_name=_category_or_none(category))}


@router.post("/follows")
def create_follow(body: FollowRequest):
    _require_follow_type(body.category, body.entity_type)
    if not body.external_id and len(follow_service.clean_query(body.query)) < follow_service.MIN_QUERY_LENGTH:
        raise HTTPException(status_code=400, detail="Type at least 2 characters or pick a suggestion.")
    result = follow_service.follow(body.category, body.entity_type, body.query, body.external_id)
    if result["status"] == "added":
        sync_new_follow(body.category, result["follow_id"])
    if result["status"] == "error":
        raise HTTPException(status_code=503, detail="Couldn't reach the data source. Try again in a bit.")
    return result


@router.delete("/follows/{follow_id}")
def delete_follow(follow_id: int):
    removed = follow_service.unfollow(follow_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Not following that.")
    return {"removed": removed}


@router.get("/search")
def search(q: str = ""):
    return dashboard_service.search(q)


@router.get("/events")
def events(range: str = "7d", category: str | None = None):
    if range not in dashboard_service.RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown range {range!r}.")
    start, end = dashboard_service.range_bounds(range)
    return {
        "range": range,
        "events": dashboard_service.events_between(start, end, _category_or_none(category), include_watched=False),
    }


@router.get("/overview")
def overview(days: int = 7):
    days = min(max(days, 1), 365)
    return {
        **dashboard_service.overview(days),
        "next_event": dashboard_service.next_event(),
        "featured": dashboard_service.featured_event(),
    }


@router.get("/calendar")
def calendar(year: int | None = None, month: int | None = None):
    now_local = datetime.now(APP_TIMEZONE)
    year = year or now_local.year
    month = month or now_local.month
    if not 1 <= month <= 12 or not 1970 <= year <= 2100:
        raise HTTPException(status_code=400, detail="Invalid year or month.")
    return {"year": year, "month": month, "days": dashboard_service.month_dots(year, month)}


@router.post("/events/{event_id}/status")
def update_status(event_id: int, body: StatusRequest):
    if body.status not in EVENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unknown status {body.status!r}.")
    if body.watched_mode is not None and body.watched_mode not in WATCH_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown watch mode {body.watched_mode!r}.")
    if not event_service.get_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found.")
    event_service.mark_status(event_id, body.status, body.watched_mode)
    return {"event": event_service.get_event(event_id)}


@router.get("/sync")
def sync_state():
    return sync_status()


@router.post("/sync")
def start_sync():
    started = start_background_sync()
    return {"started": started, **sync_status()}


@router.post("/events/{event_id}/unwatch")
def unwatch(event_id: int):
    if not event_service.get_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found.")
    event_service.unmark_watched(event_id)
    return {"event": event_service.get_event(event_id)}
