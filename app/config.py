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

EVENT_STATUSES = [
    "UPCOMING",
    "LIVE",
    "COMPLETED",
    "WATCHED",
    "MISSED",
    "CATCHUP_REQUIRED",
]

CATEGORIES = ["f1", "football", "dota", "anime", "movie"]