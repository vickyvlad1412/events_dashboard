import re
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.config import CATEGORIES, CATEGORY_META, TIER_RULES
from app.services import dashboard_service, event_service, media_service
from app.templating import templates

router = APIRouter()

RANGE_TITLES = {
    "weekend": ("This Weekend", "Saturday and Sunday"),
    "7d": ("Next 7 Days", "Everything from today through the next week"),
    "30d": ("Next 30 Days", "The month ahead"),
}


def _range_tabs(selected: str, category: str | None) -> list[dict]:
    suffix = f"&category={category}" if category else ""
    return [
        {"label": title, "href": f"/browse?range={key}{suffix}", "active": key == selected}
        for key, (title, _) in RANGE_TITLES.items()
    ]


def _category_tabs(base: str, selected: str | None, extra: str = "") -> list[dict]:
    tabs = [{"label": "All", "href": f"{base}{extra}", "active": selected is None}]
    joiner = "&" if extra else "?"
    for category in CATEGORIES:
        tabs.append({
            "label": CATEGORY_META[category]["label"],
            "href": f"{base}{extra}{joiner}category={category}",
            "active": selected == category,
        })
    return tabs


def _valid_category(category: str | None) -> str | None:
    return category if category in CATEGORIES else None


@router.get("/category/{category}")
def category_page(request: Request, category: str):
    if category not in CATEGORIES:
        raise HTTPException(status_code=404, detail="Unknown category")
    event_service.mark_stale_events_as_missed()
    meta = CATEGORY_META[category]
    events = dashboard_service.category_upcoming(category)
    catchup = [e for e in event_service.list_catchup_required() if e["category_name"] == category]
    follows = event_service.list_follows(category_name=category)
    return templates.TemplateResponse(
        "events_list.html",
        {
            "request": request,
            "page_title": meta["long"],
            "page_subtitle": f"Upcoming {meta['label']} · {meta['horizon_label']}",
            "category": category,
            "groups": dashboard_service.group_by_day(events),
            "follows": follows,
            "catchup_count": len(catchup),
            "catching_up": False,
            "coming_later": dashboard_service.coming_later(category),
            "empty_message": f"No upcoming {meta['label']} events right now.",
        },
    )


def _rule_info(rule_key: str | None) -> dict | None:
    if not rule_key:
        return None
    for category, rules in TIER_RULES.items():
        for key, label, _ in rules:
            if key == rule_key:
                tier = event_service.rule_tiers().get(key)
                return {"key": key, "label": label, "category": category, "tier": tier}
    return None


def _track_time(event: dict) -> str | None:
    offset = (event.get("details") or {}).get("gmt_offset")
    match = re.match(r"^(-)?(\d{2}):(\d{2})", offset or "")
    if not match:
        return None
    sign = -1 if match.group(1) else 1
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3))) * sign
    local = event["local_datetime"].astimezone(timezone(delta))
    hours, minutes = divmod(int(delta.total_seconds()) // 60, 60)
    label = f"UTC{'+' if sign > 0 else '-'}{abs(hours):02d}:{abs(minutes):02d}"
    return f"{local:%a} {local.day} {local:%b}, {local:%I:%M %p}".replace(" 0", " ") + f" ({label})"


@router.get("/events/{event_id}")
def event_page(request: Request, event_id: int):
    event_service.mark_stale_events_as_missed()
    event = event_service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event = dashboard_service.with_countdown(event)
    media = None
    media_id = media_service.media_id_for_event(event)
    if media_id and event["category_name"] == "anime":
        media = media_service.anime_details(media_id)
    elif media_id and event["category_name"] == "movie":
        media = media_service.movie_details(media_id)
    return templates.TemplateResponse(
        "event_detail.html",
        {
            "request": request,
            "event": event,
            "track_time": _track_time(event),
            "rule": _rule_info(event.get("rule_key")),
            "sessions": dashboard_service.group_sessions(event),
            "media": media,
            "media_id": media_id,
        },
    )


@router.get("/browse")
def browse(request: Request, range: str = "7d", category: str | None = None):
    range = range if range in RANGE_TITLES else "7d"
    category = _valid_category(category)
    event_service.mark_stale_events_as_missed()
    start, end = dashboard_service.range_bounds(range)
    events = dashboard_service.events_between(start, end, category, include_watched=False)
    title, subtitle = RANGE_TITLES[range]
    if category:
        subtitle = f"{subtitle} · {CATEGORY_META[category]['label']}"
    return templates.TemplateResponse(
        "events_list.html",
        {
            "request": request,
            "page_title": title,
            "page_subtitle": subtitle,
            "category": None,
            "tabs": _range_tabs(range, category),
            "category_tabs": _category_tabs("/browse", category, f"?range={range}"),
            "groups": dashboard_service.group_by_day(events),
            "catching_up": False,
            "empty_message": "Nothing scheduled in this period.",
        },
    )


@router.get("/catch-up")
def catch_up(request: Request, category: str | None = None):
    category = _valid_category(category)
    event_service.mark_stale_events_as_missed()
    events = [
        e for e in event_service.list_catchup_required()
        if category is None or e["category_name"] == category
    ]
    important = sum(1 for e in events if e["priority_tier"] == "A")
    return templates.TemplateResponse(
        "events_list.html",
        {
            "request": request,
            "page_title": "Catch-Up",
            "page_subtitle": f"{len(events)} to catch up on · {important} important",
            "category": None,
            "tabs": _category_tabs("/catch-up", category),
            "groups": dashboard_service.group_by_day(events),
            "catching_up": True,
            "empty_message": "Nothing to catch up on. 🎉",
        },
    )


@router.get("/search")
def search(request: Request, q: str = ""):
    query = " ".join(q.split())[:100]
    return templates.TemplateResponse(
        "search.html",
        {"request": request, "query": query, "results": dashboard_service.search(query, limit=30)},
    )
