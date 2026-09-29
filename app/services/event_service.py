from datetime import datetime, timedelta, timezone

from app.db import get_connection
from app.config import APP_TIMEZONE


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_event(
    category_name: str,
    title: str,
    event_datetime_utc: datetime,
    subtitle: str | None = None,
    venue: str | None = None,
    priority_tier: str = "C",
    live_preference: str = "ANYTIME",
    notes: str | None = None,
) -> int:
    with get_connection() as conn:
        category = conn.execute(
            "SELECT id FROM categories WHERE name = ?", (category_name,)
        ).fetchone()
        if category is None:
            raise ValueError(f"Unknown category: {category_name}")

        cursor = conn.execute(
            """
            INSERT INTO events
                (category_id, title, subtitle, event_datetime_utc, venue,
                 priority_tier, live_preference, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category["id"],
                title,
                subtitle,
                event_datetime_utc.isoformat(),
                venue,
                priority_tier,
                live_preference,
                notes,
            ),
        )
        return cursor.lastrowid


def list_upcoming(limit: int = 10) -> list[dict]:
    now_iso = _now_utc().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE event_datetime_utc >= ?
              AND status IN ('UPCOMING', 'LIVE')
            ORDER BY event_datetime_utc ASC
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def list_weekend_events() -> list[dict]:
    """Events from the coming Saturday 00:00 MYT through Sunday 23:59 MYT."""
    now_local = _now_utc().astimezone(APP_TIMEZONE)
    days_until_saturday = (5 - now_local.weekday()) % 7  # Monday=0 ... Saturday=5
    saturday = (now_local + timedelta(days=days_until_saturday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sunday_end = saturday + timedelta(days=2)

    start_utc = saturday.astimezone(timezone.utc).isoformat()
    end_utc = sunday_end.astimezone(timezone.utc).isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE event_datetime_utc >= ? AND event_datetime_utc < ?
            ORDER BY event_datetime_utc ASC
            """,
            (start_utc, end_utc),
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def list_catchup_required() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE status IN ('MISSED', 'CATCHUP_REQUIRED')
            ORDER BY event_datetime_utc DESC
            """
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def mark_status(event_id: int, new_status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE events SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, event_id),
        )
        if new_status == "WATCHED":
            conn.execute(
                "INSERT INTO watch_history (event_id, watched_mode) VALUES (?, ?)",
                (event_id, None),
            )


def _to_local_dict(row) -> dict:
    """Convert a DB row into a plain dict with a MYT-local datetime attached."""
    d = dict(row)
    utc_dt = datetime.fromisoformat(d["event_datetime_utc"])
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    d["local_datetime"] = utc_dt.astimezone(APP_TIMEZONE)
    return d

def mark_stale_events_as_missed() -> None:
    """Any UPCOMING event whose time has already passed becomes MISSED."""
    now_iso = _now_utc().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE events
            SET status = 'MISSED', updated_at = datetime('now')
            WHERE status = 'UPCOMING' AND event_datetime_utc < ?
            """,
            (now_iso,),
        )