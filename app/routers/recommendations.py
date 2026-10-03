from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.connectors import jikan_connector
from app.services import event_service
from app.config import BASE_DIR

import requests

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _current_season() -> tuple[int, str]:
    now = datetime.now(timezone.utc)
    month_to_season = {
        1: "winter", 2: "winter", 3: "winter",
        4: "spring", 5: "spring", 6: "spring",
        7: "summer", 8: "summer", 9: "summer",
        10: "fall", 11: "fall", 12: "fall",
    }
    return now.year, month_to_season[now.month]


@router.get("/anime/recommendations")
def anime_recommendations(request: Request):
    year, season = _current_season()
    try:
        top_anime = jikan_connector.fetch_top_seasonal_anime(year, season)
        fetch_error = None
    except requests.exceptions.RequestException:
        top_anime = []
        fetch_error = "Couldn't reach Jikan right now — try refreshing in a bit."
    followed = set(event_service.list_followed("anime"))

    return templates.TemplateResponse(
        "anime_recommendations.html",
        {
            "request": request,
            "top_anime": top_anime,
            "followed": followed,
            "season_label": f"{season.title()} {year}",
            "fetch_error": fetch_error,
        },
    )


@router.post("/anime/follow")
def follow_anime(title: str = Form(...)):
    event_service.follow_entity("anime", title, "anime")

    event = jikan_connector.fetch_next_episode(title)
    if event:
        event_service.upsert_external_event(event)

    return RedirectResponse(url="/anime/recommendations", status_code=303)
