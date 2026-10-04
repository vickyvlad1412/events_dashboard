from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dashboard.db"

# All events are stored in UTC and displayed in this timezone.
APP_TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")  # MYT, UTC+8

PRIORITY_TIERS = ["A", "B", "C", "D"]
PRIORITY_LABELS = {
    "A": "Must experience",
    "B": "Want to watch",
    "C": "Nice to watch",
    "D": "Background",
}

LIVE_PREFERENCES = ["LIVE", "HIGHLIGHTS", "VOD", "ANYTIME", "CINEMA"]
WATCH_MODES = ["LIVE", "HIGHLIGHTS", "VOD", "CINEMA"]

EVENT_STATUSES = [
    "UPCOMING",
    "LIVE",
    "COMPLETED",
    "WATCHED",
    "MISSED",
    "CATCHUP_REQUIRED",
]

CATEGORIES = ["f1", "football", "dota", "anime", "movie"]

APP_NAME = "My Watch Dashboard"
APP_TAGLINE = "Everything worth watching, in one place."
APP_TIMEZONE_LABEL = "Malaysia Time (MYT)"

CATEGORY_META = {
    "f1": {
        "label": "F1", "long": "Formula 1", "unit": "upcoming sessions", "color": "#a855f7",
        "horizon_days": 60, "horizon_label": "next 60 days",
    },
    "football": {
        "label": "Football", "long": "Football", "unit": "upcoming matches", "color": "#22c55e",
        "horizon_days": 2, "horizon_label": "up to a day ahead",
        "note": "Football matches show up about a day before kick-off.",
    },
    "dota": {
        "label": "Dota 2", "long": "Dota 2", "unit": "upcoming matches", "color": "#f97316",
        "horizon_days": 60, "horizon_label": "next 60 days",
    },
    "anime": {
        "label": "Anime", "long": "Anime", "unit": "upcoming episodes", "color": "#6366f1",
        "horizon_days": 60, "horizon_label": "next 60 days",
    },
    "movie": {
        "label": "Movies", "long": "Movies", "unit": "upcoming releases", "color": "#f59e0b",
        "horizon_days": 365, "horizon_label": "next 12 months",
    },
}

TIER_COLORS = {"A": "#ef4444", "B": "#f97316", "C": "#eab308", "D": "#94a3b8"}

QUICK_LINKS = [
    {"label": "Formula 1", "url": "https://www.formula1.com", "category": "f1"},
    {"label": "Premier League", "url": "https://www.premierleague.com", "category": "football"},
    {"label": "Liquipedia (Dota 2)", "url": "https://liquipedia.net/dota2", "category": "dota"},
    {"label": "AniList", "url": "https://anilist.co", "category": "anime"},
    {"label": "TMDB", "url": "https://www.themoviedb.org", "category": "movie"},
]