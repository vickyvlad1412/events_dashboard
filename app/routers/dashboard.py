from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services import event_service, collision_service
from app.config import BASE_DIR, WATCH_MODES

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/")
def dashboard(request: Request):
    event_service.mark_stale_events_as_missed()
    upcoming = event_service.list_upcoming(limit=10)
    weekend_events = event_service.list_weekend_events()
    collisions = collision_service.find_collisions(weekend_events)
    catchup = event_service.list_catchup_required()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "upcoming": upcoming,
            "collisions": collisions,
            "catchup": catchup,
            "watch_modes": WATCH_MODES,
        },
    )