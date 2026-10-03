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
    d = dict(row)
    utc_dt = datetime.fromisoformat(d["event_datetime_utc"])
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    d["local_datetime"] = utc_dt.astimezone(APP_TIMEZONE)
    return d

def mark_stale_events_as_missed() -> None:
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

def list_interest_settings() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT interest_settings.*, categories.name AS category_name, categories.icon AS category_icon
            FROM interest_settings
            JOIN categories ON categories.id = interest_settings.category_id
            ORDER BY categories.id, interest_settings.id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def set_interest_enabled(setting_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE interest_settings SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, setting_id),
        )


def is_interest_enabled(category_name: str, setting_key: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT interest_settings.enabled
            FROM interest_settings
            JOIN categories ON categories.id = interest_settings.category_id
            WHERE categories.name = ? AND interest_settings.setting_key = ?
            """,
            (category_name, setting_key),
        ).fetchone()
        return bool(row["enabled"]) if row else True

def list_events_for_month(year: int, month: int) -> dict[int, list[dict]]:
    first_day = datetime(year, month, 1, tzinfo=APP_TIMEZONE)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=APP_TIMEZONE)
    else:
        next_month_start = datetime(year, month + 1, 1, tzinfo=APP_TIMEZONE)

    start_utc = first_day.astimezone(timezone.utc).isoformat()
    end_utc = next_month_start.astimezone(timezone.utc).isoformat()

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

    by_day: dict[int, list[dict]] = {}
    for row in rows:
        event = _to_local_dict(row)
        day = event["local_datetime"].day
        by_day.setdefault(day, []).append(event)
    return by_day

def upsert_external_event(event: dict) -> None:
    with get_connection() as conn:
        category = conn.execute(
            "SELECT id FROM categories WHERE name = ?", (event["category"],)
        ).fetchone()
        if category is None:
            raise ValueError(f"Unknown category: {event['category']}")

        existing = conn.execute(
            "SELECT id FROM events WHERE external_source = ? AND external_id = ?",
            (event["external_source"], event["external_id"]),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE events
                SET title = ?, subtitle = ?, event_datetime_utc = ?, venue = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    event["title"],
                    event.get("subtitle"),
                    event["event_datetime_utc"].isoformat(),
                    event.get("venue"),
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO events
                    (category_id, title, subtitle, event_datetime_utc, venue,
                     priority_tier, live_preference, status, external_source, external_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category["id"],
                    event["title"],
                    event.get("subtitle"),
                    event["event_datetime_utc"].isoformat(),
                    event.get("venue"),
                    event.get("priority_tier", "C"),
                    event.get("live_preference", "ANYTIME"),
                    event.get("status", "UPCOMING"),
                    event["external_source"],
                    event["external_id"],
                ),
            )


def has_external_events(external_source: str, external_id_prefix: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM events WHERE external_source = ? AND external_id LIKE ? LIMIT 1",
            (external_source, f"{external_id_prefix}%"),
        ).fetchone()
        return row is not None

def list_followed(entity_type: str) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM followed_entities WHERE entity_type = ?", (entity_type,)
        ).fetchall()
        return [row["name"] for row in rows]


def follow_entity(category_name: str, name: str, entity_type: str) -> None:
    with get_connection() as conn:
        category = conn.execute(
            "SELECT id FROM categories WHERE name = ?", (category_name,)
        ).fetchone()
        conn.execute(
            "INSERT INTO followed_entities (category_id, name, entity_type) VALUES (?, ?, ?)",
            (category["id"], name, entity_type),
        )
