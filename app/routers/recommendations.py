from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.connectors import anilist_connector
from app.services import event_service, follow_service
from app.config import BASE_DIR
from app.scheduler import sync_new_follow

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
        top_anime = anilist_connector.fetch_top_seasonal_anime(year, season)
        fetch_error = None
    except requests.exceptions.RequestException:
        top_anime = []
        fetch_error = "Couldn't reach AniList right now — try refreshing in a bit."
    follows = event_service.list_follows("anime", "anime")
    followed = {f["external_id"] for f in follows if f["external_id"]} | {f["name"] for f in follows}

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
def follow_anime(title: str = Form(""), external_id: str | None = Form(None)):
    result = follow_service.follow("anime", "anime", title, external_id or None)
    if result["status"] == "added":
        sync_new_follow("anime", result["follow_id"])
    return RedirectResponse(url="/anime/recommendations", status_code=303)
