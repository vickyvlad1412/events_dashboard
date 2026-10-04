from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.services import event_service
from app.config import (
    CATEGORIES, PRIORITY_TIERS, LIVE_PREFERENCES, APP_TIMEZONE, EVENT_STATUSES, WATCH_MODES,
)
from app.templating import templates

from app.scheduler import start_background_sync

router = APIRouter()


@router.get("/events/new")
def new_event_form(request: Request):
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "categories": CATEGORIES,
            "priority_tiers": PRIORITY_TIERS,
            "live_preferences": LIVE_PREFERENCES,
        },
    )


@router.post("/events/new")
def create_event(
    category: str = Form(...),
    title: str = Form(...),
    subtitle: str = Form(""),
    event_date: str = Form(...),
    event_time: str = Form(...),
    venue: str = Form(""),
    priority_tier: str = Form("C"),
    live_preference: str = Form("ANYTIME"),
    notes: str = Form(""),
):
    local_dt = datetime.strptime(f"{event_date} {event_time}", "%Y-%m-%d %H:%M")
    local_dt = local_dt.replace(tzinfo=APP_TIMEZONE)
    utc_dt = local_dt.astimezone(timezone.utc)

    event_service.create_event(
        category_name=category,
        title=title,
        event_datetime_utc=utc_dt,
        subtitle=subtitle or None,
        venue=venue or None,
        priority_tier=priority_tier,
        live_preference=live_preference,
        notes=notes or None,
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/events/{event_id}/status")
def update_status(
    event_id: int,
    new_status: str = Form(...),
    watched_mode: str | None = Form(None),
    redirect_to: str = Form("/"),
):
    if new_status in EVENT_STATUSES:
        mode = watched_mode if watched_mode in WATCH_MODES else None
        event_service.mark_status(event_id, new_status, mode)
    return RedirectResponse(url=_safe_redirect(redirect_to), status_code=303)


def _safe_redirect(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/"

@router.post("/events/{event_id}/tier")
def update_tier(event_id: int, tier: str = Form(...)):
    if tier in PRIORITY_TIERS:
        event_service.set_event_tier(event_id, tier)
    elif tier == "default":
        event_service.set_event_tier(event_id, None)
    return RedirectResponse(url=f"/events/{event_id}", status_code=303)


@router.post("/sync-now")
def sync_now(redirect_to: str = Form("/")):
    start_background_sync()
    return RedirectResponse(url=_safe_redirect(redirect_to), status_code=303)
