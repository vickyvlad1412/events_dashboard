from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import APP_TIMEZONE, CATEGORIES, PRIORITY_TIERS
from app.db import get_connection
from app.services import event_service

RANGES = {"today": 1, "weekend": None, "7d": 7, "30d": 30}
UPCOMING_STATUSES = ("UPCOMING", "LIVE")
EVENT_COLUMNS = "events.*, categories.name AS category_name, categories.icon AS category_icon"


def range_bounds(name: str) -> tuple[datetime, datetime]:
    if name == "weekend":
        return event_service.weekend_bounds()
    now_local = datetime.now(timezone.utc).astimezone(APP_TIMEZONE)
    days = RANGES.get(name, 7)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=days)).astimezone(timezone.utc)


def events_between(
    start: datetime,
    end: datetime,
    category: str | None = None,
    include_background: bool = True,
    include_watched: bool = True,
) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE event_datetime_utc >= ? AND event_datetime_utc < ?
              AND (? IS NULL OR categories.name = ?)
              AND (? OR priority_tier != 'D')
              AND (? OR status != 'WATCHED')
            ORDER BY event_datetime_utc ASC
            """,
            (start.isoformat(), end.isoformat(), category, category, include_background, include_watched),
        ).fetchall()
    return [_with_countdown(event_service._to_local_dict(row)) for row in rows]


def upcoming(days: int = 7, category: str | None = None, limit: int | None = None) -> list[dict]:
    now = datetime.now(timezone.utc)
    events = [
        e for e in events_between(now, now + timedelta(days=days), category, include_background=False)
        if e["status"] in UPCOMING_STATUSES
    ]
    return events[:limit] if limit else events


def overview(days: int = 7) -> dict:
    events = upcoming(days)
    tiers = Counter(e["priority_tier"] for e in events)
    categories = Counter(e["category_name"] for e in events)
    catchup = event_service.list_catchup_required()
    return {
        "days": days,
        "total": len(events),
        "by_tier": {tier: tiers.get(tier, 0) for tier in PRIORITY_TIERS},
        "by_category": {category: categories.get(category, 0) for category in CATEGORIES},
        "catchup_total": len(catchup),
        "catchup_important": sum(1 for e in catchup if e["priority_tier"] == "A"),
    }


def next_event() -> dict | None:
    events = upcoming(days=3650, limit=1)
    return events[0] if events else None


def featured_event() -> dict | None:
    candidates = [e for e in upcoming(days=30) if e["priority_tier"] == "A"] or upcoming(days=30)
    if not candidates:
        return None
    lead = candidates[0]
    sessions = [lead]
    if lead.get("group_key"):
        sessions = [e for e in upcoming(days=30) if e.get("group_key") == lead["group_key"]]
    return {
        "title": lead.get("group_title") or lead["title"],
        "category_name": lead["category_name"],
        "category_icon": lead["category_icon"],
        "subtitle": lead.get("venue") or lead.get("subtitle"),
        "image_url": lead.get("image_url"),
        "sessions": sessions,
    }


def month_dots(year: int, month: int) -> dict[int, list[str]]:
    return {
        day: sorted({e["category_name"] for e in events}, key=CATEGORIES.index)
        for day, events in event_service.list_events_for_month(year, month).items()
    }


def search(query: str, limit: int = 8) -> dict:
    query = " ".join((query or "").split())
    if len(query) < 2:
        return {"events": [], "follows": []}
    pattern = f"%{query}%"
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE events.title LIKE ? OR events.subtitle LIKE ? OR events.group_title LIKE ? OR events.venue LIKE ?
            ORDER BY (events.event_datetime_utc < ?), ABS(julianday(events.event_datetime_utc) - julianday(?))
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, now_iso, now_iso, limit),
        ).fetchall()
    follows = [
        f for f in event_service.list_follows()
        if query.lower() in f["name"].lower()
    ][:limit]
    return {"events": [_with_countdown(event_service._to_local_dict(row)) for row in rows], "follows": follows}


def _with_countdown(event: dict) -> dict:
    today = datetime.now(timezone.utc).astimezone(APP_TIMEZONE).date()
    days = (event["local_datetime"].date() - today).days
    event["days_until"] = days
    if days == 0:
        event["countdown"] = "Today"
    elif days == 1:
        event["countdown"] = "Tomorrow"
    elif days > 1:
        event["countdown"] = f"{days} days"
    else:
        event["countdown"] = f"{-days} day{'s' if days != -1 else ''} ago"
    return event
