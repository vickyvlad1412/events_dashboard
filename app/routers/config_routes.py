from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.services import event_service, follow_service
from app.scheduler import sync_new_follow
from app.templating import templates

router = APIRouter()

FOLLOW_SECTIONS = [
    ("football", "team", "Football teams", "Add a team", "Search teams, e.g. Liverpool"),
    ("dota", "team", "Dota 2 teams", "Add a team", "Search teams, e.g. Team Spirit"),
    ("dota", "player", "Dota 2 players", "Add a player", "Search players, e.g. Yatoro"),
    ("anime", "anime", "Anime", "Add an anime", "Search anime, e.g. Chainsaw Man"),
    ("movie", "movie", "Movies", "Add a movie", "Search movies, e.g. Avatar"),
]


@router.get("/interests")
def settings_page(request: Request):
    return templates.TemplateResponse(
        "interests.html",
        {"request": request, "settings": event_service.list_interest_settings()},
    )


@router.get("/following")
def following_page(
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
        if follow_status == "ambiguous" and follow_service.is_supported(follow_category, follow_type):
            try:
                suggestions = follow_service.suggest(follow_category, follow_type, follow_query)
            except Exception as exc:
                print(f"[following] couldn't reload suggestions: {exc}")
                follow_status = "error"
        section = next(
            (s for s in FOLLOW_SECTIONS if (s[0], s[1]) == (follow_category, follow_type)), None
        )
        feedback = {
            "status": follow_status,
            "type_label": section[2] if section else "",
            "name": follow_name,
            "query": follow_query,
            "category": follow_category,
            "entity_type": follow_type,
            "suggestions": suggestions,
        }

    return templates.TemplateResponse(
        "following.html",
        {
            "request": request,
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
def follow_from_form(
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
    return RedirectResponse(url=f"/following?{urlencode(query)}", status_code=303)


@router.post("/interests/unfollow/{follow_id}")
def unfollow_from_form(follow_id: int):
    removed = follow_service.unfollow(follow_id)
    query = {"follow_status": "removed", "follow_name": removed["name"]} if removed else {}
    return RedirectResponse(url=f"/following?{urlencode(query)}" if query else "/following", status_code=303)
