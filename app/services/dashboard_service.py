import calendar as cal_module
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import APP_TIMEZONE, CATEGORIES, CATEGORY_META, PRIORITY_TIERS
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


def category_upcoming(category: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=CATEGORY_META[category]["horizon_days"])
    return [
        e for e in events_between(now, end, category, include_watched=False)
        if e["status"] in UPCOMING_STATUSES
    ]


def category_counts() -> dict[str, int]:
    return {category: len(category_upcoming(category)) for category in CATEGORIES}


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


def weekend() -> dict:
    start, end = event_service.weekend_bounds()
    events = events_between(start, end, include_watched=False)
    days = []
    for offset in range(2):
        day = (start + timedelta(days=offset)).astimezone(APP_TIMEZONE).date()
        day_events = [e for e in events if e["local_datetime"].date() == day]
        high_priority = sum(1 for e in day_events if e["priority_tier"] in ("A", "B"))
        days.append({
            "date": datetime(day.year, day.month, day.day, tzinfo=APP_TIMEZONE),
            "is_today": day == datetime.now(timezone.utc).astimezone(APP_TIMEZONE).date(),
            "events": day_events,
            "is_collision": high_priority >= 2,
            "high_priority": high_priority,
        })
    return {
        "days": days,
        "total": len(events),
        "high_priority": sum(1 for e in events if e["priority_tier"] in ("A", "B")),
    }


def sidebar_summary() -> dict:
    week = upcoming(7)
    weekend_start, weekend_end = event_service.weekend_bounds()
    return {
        "anime_episodes": sum(1 for e in week if e["category_name"] == "anime"),
        "movie_releases": sum(1 for e in upcoming(30) if e["category_name"] == "movie"),
        "live_this_weekend": sum(
            1 for e in events_between(weekend_start, weekend_end, include_background=False, include_watched=False)
            if e["live_preference"] == "LIVE" and e["status"] in UPCOMING_STATUSES
        ),
    }


def next_event() -> dict | None:
    events = upcoming(days=3650, limit=1)
    return events[0] if events else None


def _slide(lead: dict, sessions: list[dict]) -> dict:
    return {
        "event_id": lead["id"],
        "title": lead.get("group_title") or lead["title"],
        "category_name": lead["category_name"],
        "category_icon": lead["category_icon"],
        "subtitle": lead.get("venue") or lead.get("subtitle"),
        "image_url": lead.get("image_url"),
        "sessions": sessions,
    }


def featured_events(days: int = 14, limit: int = 8) -> list[dict]:
    window = upcoming(days)
    candidates = [e for e in window if e["priority_tier"] == "A"] or [e for e in window if e["priority_tier"] == "B"]
    slides = []
    seen_groups = set()
    for event in candidates:
        group = event.get("group_key")
        if group and group in seen_groups:
            continue
        if group:
            seen_groups.add(group)
            sessions = [e for e in candidates if e.get("group_key") == group]
        else:
            sessions = [event]
        slides.append(_slide(event, sessions))
        if len(slides) >= limit:
            break
    return slides


def featured_event() -> dict | None:
    slides = featured_events(days=30, limit=1)
    return slides[0] if slides else None


def group_sessions(event: dict) -> list[dict]:
    if not event.get("group_key"):
        return []
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE events.group_key = ?
            ORDER BY event_datetime_utc ASC
            """,
            (event["group_key"],),
        ).fetchall()
    return [_with_countdown(event_service._to_local_dict(row)) for row in rows]


def coming_later(category: str) -> list[dict]:
    if category not in ("anime", "movie"):
        return []
    visible = category_upcoming(category)
    source = "anilist" if category == "anime" else "tmdb"
    horizon_end = (datetime.now(timezone.utc) + timedelta(days=CATEGORY_META[category]["horizon_days"])).isoformat()
    with get_connection() as conn:
        later_rows = conn.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE events.external_source = ? AND events.event_datetime_utc >= ? AND events.status = 'UPCOMING'
            ORDER BY events.event_datetime_utc ASC
            """,
            (source, horizon_end),
        ).fetchall()
        tracked_rows = conn.execute(
            "SELECT external_id FROM events WHERE external_source = ? AND status NOT IN ('WATCHED', 'COMPLETED')",
            (source,),
        ).fetchall()

    def media_id(external_id: str) -> str:
        return external_id.split("-", 1)[0] if category == "anime" else external_id

    later_events = [_with_countdown(event_service._to_local_dict(row)) for row in later_rows]
    tracked = {media_id(row["external_id"]) for row in tracked_rows}
    items = [
        {
            "name": event["title"],
            "image_url": event.get("image_url"),
            "note": f"{event['subtitle']} · {event['local_datetime']:%d %b %Y}" if event.get("subtitle") else f"{event['local_datetime']:%d %b %Y}",
            "media_id": media_id(event["external_id"]),
            "date": event["local_datetime"],
        }
        for event in later_events
    ]
    listed = {item["media_id"] for item in items} | {media_id(e["external_id"]) for e in visible if e.get("external_id")}
    listed_names = {e["title"].lower() for e in visible + later_events}
    for follow in event_service.list_follows(category_name=category):
        external_id = follow.get("external_id")
        if not external_id and follow["name"].lower() in listed_names:
            continue
        if external_id in listed or (external_id in tracked and not follow.get("status_note")):
            continue
        items.append({
            "name": follow["name"],
            "image_url": follow.get("image_url"),
            "note": follow.get("status_note") or "Date TBD",
            "media_id": external_id,
            "date": None,
        })
    return items


def mini_calendar(year: int, month: int) -> dict:
    now_local = datetime.now(timezone.utc).astimezone(APP_TIMEZONE)
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    return {
        "year": year,
        "month": month,
        "month_name": cal_module.month_name[month],
        "weekday_names": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "weeks": cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month),
        "today": now_local.day if (now_local.year, now_local.month) == (year, month) else None,
        "dots": month_dots(year, month),
        "prev": f"{prev_year}-{prev_month:02d}",
        "next": f"{next_year}-{next_month:02d}",
    }


def group_by_day(events: list[dict]) -> list[dict]:
    groups = []
    for event in events:
        day = event["local_datetime"].date()
        if not groups or groups[-1]["day"] != day:
            groups.append({"day": day, "date": event["local_datetime"], "events": []})
        groups[-1]["events"].append(event)
    return groups


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


def with_countdown(event: dict) -> dict:
    return _with_countdown(event)


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
