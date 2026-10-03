import re
from datetime import datetime

from fastapi import APIRouter, Request

from app.config import APP_TIMEZONE
from app.services import dashboard_service, event_service
from app.templating import templates

router = APIRouter()

CALENDAR_PARAM = re.compile(r"^(\d{4})-(\d{2})$")


def _calendar_month(value: str) -> tuple[int, int]:
    match = CALENDAR_PARAM.match(value or "")
    if match and 1970 <= int(match.group(1)) <= 2100 and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)), int(match.group(2))
    now = datetime.now(APP_TIMEZONE)
    return now.year, now.month


@router.get("/")
def dashboard(request: Request, cal: str = ""):
    event_service.mark_stale_events_as_missed()
    year, month = _calendar_month(cal)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "featured": dashboard_service.featured_event(),
            "weekend": dashboard_service.weekend(),
            "overview": dashboard_service.overview(7),
            "category_counts": dashboard_service.category_counts(),
            "catchup": event_service.list_catchup_required(),
            "coming_soon": dashboard_service.upcoming(7),
            "next_event": dashboard_service.next_event(),
            "mini_calendar": dashboard_service.mini_calendar(year, month),
        },
    )
