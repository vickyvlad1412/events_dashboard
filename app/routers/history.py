from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import event_service, history_service
from app.config import BASE_DIR, CATEGORIES

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/history")
def watch_history(request: Request, period: str = "30d", category: str = ""):
    period = period if period in history_service.PERIODS else "30d"
    selected_category = category if category in CATEGORIES else None

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "periods": history_service.PERIODS,
            "period": period,
            "categories": CATEGORIES,
            "category": selected_category or "",
            "stats": history_service.watch_stats(period, selected_category),
            "history": history_service.list_history(period, selected_category),
        },
    )


@router.post("/events/{event_id}/unwatch")
def unwatch(event_id: int, period: str = Form("30d"), category: str = Form("")):
    event_service.unmark_watched(event_id)
    query = urlencode({"period": period, "category": category})
    return RedirectResponse(url=f"/history?{query}", status_code=303)
