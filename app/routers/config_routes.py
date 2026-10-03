from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import event_service, follow_service
from app.config import BASE_DIR
from app.scheduler import sync_new_follow

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

FOLLOW_SECTIONS = [
    ("movie", "movie", "🎬 Movies I'm following", "Add a movie", "e.g. Avatar: Fire and Ash"),
    ("anime", "anime", "📺 Anime I'm following", "Add an anime", "e.g. Chainsaw Man"),
    ("football", "team", "⚽ Football teams I'm following", "Add a team", "e.g. Liverpool"),
    ("dota", "team", "🎮 Dota teams I'm following", "Add a team", "e.g. Team Spirit"),
    ("dota", "player", "🎮 Dota players I'm following", "Add a player", "e.g. Yatoro"),
]


@router.get("/interests")
def my_interests(
    request: Request,
    follow_status: str = "",
    follow_name: str = "",
    follow_category: str = "",
    follow_type: str = "",
    follow_query: str = "",
):
    feedback = None
    if follow_status:
        suggestions = []
        if follow_status == "ambiguous":
            suggestions = follow_service.suggest(follow_category, follow_type, follow_query)
        feedback = {
            "status": follow_status,
            "name": follow_name,
            "query": follow_query,
            "category": follow_category,
            "entity_type": follow_type,
            "suggestions": suggestions,
        }

    return templates.TemplateResponse(
        "interests.html",
        {
            "request": request,
            "settings": event_service.list_interest_settings(),
            "sections": [
                {
                    "category": category,
                    "entity_type": entity_type,
                    "heading": heading,
                    "label": label,
                    "placeholder": placeholder,
                    "follows": event_service.list_follows(entity_type, category),
                }
                for category, entity_type, heading, label, placeholder in FOLLOW_SECTIONS
            ],
            "feedback": feedback,
        },
    )


@router.post("/interests/toggle")
def toggle_interest(setting_id: int = Form(...), enabled: str = Form(...)):
    event_service.set_interest_enabled(setting_id, enabled == "true")
    return RedirectResponse(url="/interests", status_code=303)


@router.post("/interests/follow")
def follow_from_interests(
    category: str = Form(...),
    title: str = Form(""),
    entity_type: str | None = Form(None),
    external_id: str | None = Form(None),
):
    entity_type = entity_type or category
    result = follow_service.follow(category, entity_type, title, external_id or None)
    if result["status"] == "added":
        sync_new_follow(category, result["follow_id"])

    query = {
        "follow_status": result["status"],
        "follow_name": (result["entity"] or {}).get("name", ""),
        "follow_category": category,
        "follow_type": entity_type,
        "follow_query": follow_service.clean_query(title),
    }
    return RedirectResponse(url=f"/interests?{urlencode(query)}", status_code=303)


@router.post("/interests/unfollow/{follow_id}")
def unfollow_from_interests(follow_id: int):
    removed = follow_service.unfollow(follow_id)
    query = {"follow_status": "removed", "follow_name": removed["name"]} if removed else {}
    return RedirectResponse(url=f"/interests?{urlencode(query)}" if query else "/interests", status_code=303)
