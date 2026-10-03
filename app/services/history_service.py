from datetime import datetime, timedelta, timezone

from app.config import APP_TIMEZONE
from app.db import get_connection

PERIODS = {
    "7d": ("Last 7 days", 7),
    "30d": ("Last 30 days", 30),
    "90d": ("Last 90 days", 90),
    "365d": ("Last 12 months", 365),
    "all": ("All time", None),
}

MONTHS_SHOWN = 6


def _since(period: str) -> datetime | None:
    days = PERIODS.get(period, PERIODS["30d"])[1]
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


def _watched_at_filter(since: datetime | None) -> str:
    return since.strftime("%Y-%m-%d %H:%M:%S") if since else ""


def _local_offset_modifier() -> str:
    minutes = int(datetime.now(APP_TIMEZONE).utcoffset().total_seconds() // 60)
    return f"{minutes:+d} minutes"


def _to_local(utc_text: str) -> datetime:
    dt = datetime.fromisoformat(utc_text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(APP_TIMEZONE)


def list_history(period: str = "30d", category: str | None = None) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT watch_history.id AS history_id, watch_history.watched_at, watch_history.watched_mode,
                   events.id AS event_id, events.title, events.subtitle, events.event_datetime_utc,
                   events.priority_tier, categories.name AS category_name, categories.icon AS category_icon
            FROM watch_history
            JOIN events ON events.id = watch_history.event_id
            JOIN categories ON categories.id = events.category_id
            WHERE watch_history.watched_at >= ?
              AND (? IS NULL OR categories.name = ?)
            ORDER BY watch_history.watched_at DESC
            """,
            (_watched_at_filter(_since(period)), category, category),
        ).fetchall()

    history = []
    for row in rows:
        item = dict(row)
        item["watched_local"] = _to_local(item["watched_at"])
        item["event_local"] = _to_local(item["event_datetime_utc"])
        history.append(item)
    return history


def watch_stats(period: str = "30d", category: str | None = None) -> dict:
    since = _since(period)
    watched_filter = _watched_at_filter(since)
    event_filter = since.isoformat() if since else ""
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        by_category = conn.execute(
            """
            SELECT categories.name, categories.icon, COUNT(*) AS count
            FROM watch_history
            JOIN events ON events.id = watch_history.event_id
            JOIN categories ON categories.id = events.category_id
            WHERE watch_history.watched_at >= ? AND (? IS NULL OR categories.name = ?)
            GROUP BY categories.id
            ORDER BY count DESC
            """,
            (watched_filter, category, category),
        ).fetchall()

        by_mode = conn.execute(
            """
            SELECT COALESCE(watch_history.watched_mode, 'UNKNOWN') AS mode, COUNT(*) AS count
            FROM watch_history
            JOIN events ON events.id = watch_history.event_id
            JOIN categories ON categories.id = events.category_id
            WHERE watch_history.watched_at >= ? AND (? IS NULL OR categories.name = ?)
            GROUP BY mode
            ORDER BY count DESC
            """,
            (watched_filter, category, category),
        ).fetchall()

        completion = conn.execute(
            """
            SELECT categories.name, categories.icon,
                   SUM(events.status = 'WATCHED') AS watched,
                   SUM(events.status IN ('MISSED', 'CATCHUP_REQUIRED')) AS missed
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE events.priority_tier IN ('A', 'B')
              AND events.event_datetime_utc >= ? AND events.event_datetime_utc < ?
              AND events.status IN ('WATCHED', 'MISSED', 'CATCHUP_REQUIRED')
              AND (? IS NULL OR categories.name = ?)
            GROUP BY categories.id
            ORDER BY categories.id
            """,
            (event_filter, now_iso, category, category),
        ).fetchall()

        monthly = conn.execute(
            """
            SELECT strftime('%Y-%m', watch_history.watched_at, ?) AS month, COUNT(*) AS count
            FROM watch_history
            JOIN events ON events.id = watch_history.event_id
            JOIN categories ON categories.id = events.category_id
            WHERE (? IS NULL OR categories.name = ?)
            GROUP BY month
            """,
            (_local_offset_modifier(), category, category),
        ).fetchall()

    total = sum(row["count"] for row in by_category)
    return {
        "total": total,
        "by_category": [dict(row) for row in by_category],
        "by_mode": [dict(row) for row in by_mode],
        "completion": [
            {
                **dict(row),
                "rate": round(100 * row["watched"] / (row["watched"] + row["missed"])),
            }
            for row in completion
        ],
        "monthly": _last_months({row["month"]: row["count"] for row in monthly}),
    }


def _last_months(counts: dict[str, int]) -> list[dict]:
    month = datetime.now(APP_TIMEZONE).replace(day=1)
    months = []
    for _ in range(MONTHS_SHOWN):
        key = month.strftime("%Y-%m")
        months.append({"label": month.strftime("%b %Y"), "count": counts.get(key, 0)})
        month = (month - timedelta(days=1)).replace(day=1)
    peak = max((m["count"] for m in months), default=0) or 1
    for m in months:
        m["percent"] = round(100 * m["count"] / peak)
    return list(reversed(months))
