from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.config import (
    APP_NAME, APP_TAGLINE, APP_TIMEZONE, APP_TIMEZONE_LABEL, BASE_DIR, CATEGORIES, CATEGORY_META,
    PRIORITY_LABELS, QUICK_LINKS, TIER_CHOICES, TIER_COLORS, WATCH_MODES,
)
from app.services import dashboard_service

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _time12(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _date_short(value: datetime) -> str:
    return f"{value:%a}, {value.day} {value:%b %Y}"


def _date_long(value: datetime) -> str:
    return f"{value:%A}, {value.day} {value:%B %Y}"


def _day_month(value: datetime) -> str:
    return f"{value.day} {value:%b}"


def _sync_status() -> dict:
    from app.scheduler import sync_status

    return sync_status()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(APP_TIMEZONE)


def _date_only(event) -> bool:
    external_id = event.get("external_id") or ""
    return event.get("external_source") == "tmdb" or external_id.endswith(("-premiere", "-catchup"))


def _current_url(request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


templates.env.filters.update(
    time12=_time12, date_short=_date_short, date_long=_date_long, day_month=_day_month
)
templates.env.globals.update(
    app_name=APP_NAME,
    app_tagline=APP_TAGLINE,
    timezone_label=APP_TIMEZONE_LABEL,
    categories=CATEGORIES,
    category_meta=CATEGORY_META,
    category_colors={name: meta["color"] for name, meta in CATEGORY_META.items()},
    timezone_name=APP_TIMEZONE.key,
    tier_colors=TIER_COLORS,
    tier_labels=PRIORITY_LABELS,
    quick_links=QUICK_LINKS,
    watch_modes=WATCH_MODES,
    now_local=lambda: datetime.now(APP_TIMEZONE),
    sidebar_summary=dashboard_service.sidebar_summary,
    current_url=_current_url,
    sync_status=_sync_status,
    tier_choices=TIER_CHOICES,
    from_iso=_from_iso,
    date_only=_date_only,
)
