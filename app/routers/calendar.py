import calendar as cal_module
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services import event_service
from app.config import BASE_DIR, APP_TIMEZONE

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/calendar")
def calendar_view(request: Request, year: int | None = None, month: int | None = None):
    now_local = datetime.now(APP_TIMEZONE)
    year = year or now_local.year
    month = month or now_local.month

    month_calendar = cal_module.Calendar(firstweekday=6)  # use 0 for Monday-first
    weeks = month_calendar.monthdayscalendar(year, month)

    events_by_day = event_service.list_events_for_month(year, month)

    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)

    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "weeks": weeks,
            "events_by_day": events_by_day,
            "month_name": cal_module.month_name[month],
            "year": year,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )