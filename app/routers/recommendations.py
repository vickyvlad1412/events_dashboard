from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.services import event_service, follow_service, media_service
from app.scheduler import sync_new_follow
from app.templating import templates

import requests

router = APIRouter()

SEASONS = ["winter", "spring", "summer", "fall"]
MEDIA_PAGES = {"anime": ("anilist", "/anime/"), "movie": ("tmdb", "/movies/")}


def _current_season() -> tuple[int, str]:
    now = datetime.now(timezone.utc)
    return now.year, SEASONS[(now.month - 1) // 3]


def _next_season(year: int, season: str) -> tuple[int, str]:
    index = SEASONS.index(season)
    return (year + 1, SEASONS[0]) if index == len(SEASONS) - 1 else (year, SEASONS[index + 1])


def _followed_ids(category: str) -> set[str]:
    follows = event_service.list_follows(category_name=category)
    return {f["external_id"] for f in follows if f["external_id"]} | {f["name"] for f in follows}


def _safe_redirect(path: str, fallback: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else fallback


def _season_block(year: int, season: str, sort: str, label: str) -> dict:
    try:
        items = media_service.seasonal_anime(year, season, sort)
        error = None
    except requests.exceptions.RequestException:
        items, error = [], "Couldn't reach AniList right now. Try refreshing in a bit."
    return {"title": f"{season.title()} {year}", "label": label, "entries": items, "error": error}


@router.get("/anime/recommendations")
def anime_recommendations(request: Request):
    year, season = _current_season()
    next_year, next_season = _next_season(year, season)
    return templates.TemplateResponse(
        "anime_recommendations.html",
        {
            "request": request,
            "sections": [
                _season_block(year, season, "SCORE_DESC", "Airing now · highest rated"),
                _season_block(next_year, next_season, "POPULARITY_DESC", "Next season · most anticipated"),
            ],
            "followed": _followed_ids("anime"),
        },
    )


@router.get("/movies")
def movies_page(request: Request):
    sections = []
    for title, label, fetch in (
        ("Now Showing", "In cinemas in Malaysia", media_service.now_showing),
        ("Upcoming Releases", "Coming to cinemas in Malaysia", media_service.upcoming_movies),
    ):
        try:
            sections.append({"title": title, "label": label, "entries": fetch(), "error": None})
        except requests.exceptions.RequestException:
            sections.append({"title": title, "label": label, "entries": [], "error": "Couldn't reach TMDB right now."})
    return templates.TemplateResponse(
        "movies.html",
        {"request": request, "sections": sections, "followed": _followed_ids("movie")},
    )


def _media_page(request: Request, category: str, external_id: str, details: dict | None):
    if details is None:
        raise HTTPException(status_code=404, detail="Not found")
    source, _ = MEDIA_PAGES[category]
    follow = next(
        (f for f in event_service.list_follows(category_name=category) if f["external_id"] == external_id), None
    )
    pattern = f"{external_id}-%" if category == "anime" else external_id
    return templates.TemplateResponse(
        "media_detail.html",
        {
            "request": request,
            "category": category,
            "media": details,
            "external_id": external_id,
            "follow": follow,
            "tracked": event_service.list_external_events(source, pattern),
            "followed_banner": request.query_params.get("followed"),
        },
    )


@router.get("/anime/{media_id}")
def anime_page(request: Request, media_id: int):
    return _media_page(request, "anime", str(media_id), media_service.anime_details(str(media_id)))


@router.get("/movies/{movie_id}")
def movie_page(request: Request, movie_id: int):
    return _media_page(request, "movie", str(movie_id), media_service.movie_details(str(movie_id)))


@router.post("/discover/follow")
def follow_media(category: str = Form(...), external_id: str = Form(...), redirect_to: str = Form("/")):
    if category not in MEDIA_PAGES:
        raise HTTPException(status_code=400, detail="Unsupported category")
    result = follow_service.follow(category, category, external_id=external_id)
    if result["status"] == "added":
        sync_new_follow(category, result["follow_id"])
    target = _safe_redirect(redirect_to, MEDIA_PAGES[category][1] + external_id)
    joiner = "&" if "?" in target else "?"
    return RedirectResponse(url=f"{target}{joiner}followed={result['status']}", status_code=303)


@router.post("/discover/unfollow")
def unfollow_media(category: str = Form(...), external_id: str = Form(...), redirect_to: str = Form("/")):
    for follow in event_service.list_follows(category_name=category):
        if follow["external_id"] == external_id:
            follow_service.unfollow(follow["id"])
    return RedirectResponse(url=_safe_redirect(redirect_to, MEDIA_PAGES.get(category, ("", "/"))[1] + external_id), status_code=303)


@router.post("/anime/follow")
def follow_anime(title: str = Form(""), external_id: str | None = Form(None)):
    result = follow_service.follow("anime", "anime", title, external_id or None)
    if result["status"] == "added":
        sync_new_follow("anime", result["follow_id"])
    return RedirectResponse(url="/anime/recommendations", status_code=303)
