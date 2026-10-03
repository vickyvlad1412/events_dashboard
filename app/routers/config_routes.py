from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import event_service
from app.config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/interests")
def my_interests(request: Request):
    settings = event_service.list_interest_settings()
    followed_movies = event_service.list_followed("movie")
    followed_anime = event_service.list_followed("anime")

    return templates.TemplateResponse(
        "interests.html",
        {
            "request": request,
            "settings": settings,
            "followed_movies": followed_movies,
            "followed_anime": followed_anime,
        },
    )


@router.post("/interests/toggle")
def toggle_interest(setting_id: int = Form(...), enabled: str = Form(...)):
    event_service.set_interest_enabled(setting_id, enabled == "true")
    return RedirectResponse(url="/interests", status_code=303)


@router.post("/interests/follow")
def follow_from_interests(category: str = Form(...), title: str = Form(...)):
    event_service.follow_entity(category, title, category)
    return RedirectResponse(url="/interests", status_code=303)