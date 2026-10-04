import json
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
              AND priority_tier != 'D'
            ORDER BY event_datetime_utc ASC
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def weekend_bounds() -> tuple[datetime, datetime]:
    now_local = _now_utc().astimezone(APP_TIMEZONE)
    days_until_saturday = (5 - now_local.weekday()) % 7  # Monday=0 ... Saturday=5
    saturday = (now_local + timedelta(days=days_until_saturday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if now_local.weekday() == 6:
        saturday -= timedelta(days=7)
    return saturday.astimezone(timezone.utc), (saturday + timedelta(days=2)).astimezone(timezone.utc)


def list_weekend_events() -> list[dict]:
    start, end = weekend_bounds()
    start_utc = start.isoformat()
    end_utc = end.isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE event_datetime_utc >= ? AND event_datetime_utc < ?
              AND status != 'WATCHED'
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
              AND priority_tier IN ('A', 'B')
            ORDER BY event_datetime_utc DESC
            """
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def get_event(event_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE events.id = ?
            """,
            (event_id,),
        ).fetchone()
        return _to_local_dict(row) if row else None


def mark_status(event_id: int, new_status: str, watched_mode: str | None = None) -> None:
    with get_connection() as conn:
        event = conn.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None or event["status"] == new_status:
            return
        conn.execute(
            "UPDATE events SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, event_id),
        )
        if new_status == "WATCHED":
            conn.execute(
                "INSERT INTO watch_history (event_id, watched_mode, previous_status) VALUES (?, ?, ?)",
                (event_id, watched_mode, event["status"]),
            )


def unmark_watched(event_id: int) -> None:
    with get_connection() as conn:
        event = conn.execute(
            "SELECT status, priority_tier, event_datetime_utc FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None or event["status"] != "WATCHED":
            return
        last_watch = conn.execute(
            "SELECT previous_status FROM watch_history WHERE event_id = ? ORDER BY id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        previous = last_watch["previous_status"] if last_watch else None
        restored = previous if previous in ("MISSED", "CATCHUP_REQUIRED", "COMPLETED") else _default_status(event)
        conn.execute(
            "UPDATE events SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (restored, event_id),
        )
        conn.execute("DELETE FROM watch_history WHERE event_id = ?", (event_id,))


def _default_status(event) -> str:
    start = datetime.fromisoformat(event["event_datetime_utc"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start >= _now_utc():
        return "UPCOMING"
    return "MISSED" if event["priority_tier"] in ("A", "B") else "COMPLETED"


def _to_local_dict(row) -> dict:
    d = dict(row)
    utc_dt = datetime.fromisoformat(d["event_datetime_utc"])
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    d["local_datetime"] = utc_dt.astimezone(APP_TIMEZONE)
    raw_details = d.get("details_json")
    try:
        d["details"] = json.loads(raw_details) if raw_details else {}
    except ValueError:
        d["details"] = {}
    return d

def mark_stale_events_as_missed() -> None:
    now_iso = _now_utc().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE events
            SET status = CASE WHEN priority_tier IN ('A', 'B') THEN 'MISSED' ELSE 'COMPLETED' END,
                updated_at = datetime('now')
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


def rule_tiers() -> dict[str, str | None]:
    with get_connection() as conn:
        rows = conn.execute("SELECT setting_key, tier, enabled FROM interest_settings").fetchall()
    tiers = {}
    for row in rows:
        tier = row["tier"] or ("off" if not row["enabled"] else None)
        tiers[row["setting_key"]] = None if tier == "off" else tier
    return tiers


def set_rule_tier(setting_id: int, tier: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT setting_key, tier FROM interest_settings WHERE id = ?", (setting_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE interest_settings SET tier = ?, enabled = ? WHERE id = ?",
            (tier, 0 if tier == "off" else 1, setting_id),
        )
        key = row["setting_key"]
        if tier == "off":
            conn.execute(
                "DELETE FROM events WHERE rule_key = ? AND tier_locked = 0 AND status = 'UPCOMING'", (key,)
            )
            conn.execute(
                """
                UPDATE events SET status = 'COMPLETED', updated_at = datetime('now')
                WHERE rule_key = ? AND tier_locked = 0 AND status IN ('MISSED', 'CATCHUP_REQUIRED')
                """,
                (key,),
            )
        else:
            conn.execute(
                """
                UPDATE events SET priority_tier = ?, updated_at = datetime('now')
                WHERE rule_key = ? AND tier_locked = 0 AND status NOT IN ('WATCHED', 'COMPLETED')
                """,
                (tier, key),
            )
        return {"setting_key": key, "previous": row["tier"], "tier": tier}


def set_event_tier(event_id: int, tier: str | None) -> None:
    with get_connection() as conn:
        event = conn.execute("SELECT rule_key FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return
        if tier:
            conn.execute(
                "UPDATE events SET priority_tier = ?, tier_locked = 1, updated_at = datetime('now') WHERE id = ?",
                (tier, event_id),
            )
            return
        default = None
        if event["rule_key"]:
            rule = conn.execute(
                "SELECT tier FROM interest_settings WHERE setting_key = ?", (event["rule_key"],)
            ).fetchone()
            default = rule["tier"] if rule and rule["tier"] in ("A", "B", "C", "D") else None
        conn.execute(
            """
            UPDATE events SET tier_locked = 0, priority_tier = COALESCE(?, priority_tier),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (default, event_id),
        )


def set_follow_note(follow_id: int, note: str | None) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE followed_entities SET status_note = ? WHERE id = ?", (note, follow_id))


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
        details = json.dumps(event["details"]) if event.get("details") is not None else None

        if existing:
            conn.execute(
                """
                UPDATE events
                SET title = ?, subtitle = ?, event_datetime_utc = ?, venue = ?,
                    priority_tier = CASE WHEN tier_locked = 1 THEN priority_tier ELSE ? END,
                    live_preference = ?, image_url = ?, group_key = ?, group_title = ?,
                    rule_key = ?, details_json = COALESCE(?, details_json), updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    event["title"],
                    event.get("subtitle"),
                    event["event_datetime_utc"].isoformat(),
                    event.get("venue"),
                    event.get("priority_tier", "C"),
                    event.get("live_preference", "ANYTIME"),
                    event.get("image_url"),
                    event.get("group_key"),
                    event.get("group_title"),
                    event.get("rule_key"),
                    details,
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO events
                    (category_id, title, subtitle, event_datetime_utc, venue,
                     priority_tier, live_preference, status, external_source, external_id,
                     image_url, group_key, group_title, rule_key, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.get("image_url"),
                    event.get("group_key"),
                    event.get("group_title"),
                    event.get("rule_key"),
                    details,
                ),
            )


def list_external_events(external_source: str, external_id_pattern: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT events.*, categories.name AS category_name, categories.icon AS category_icon
            FROM events
            JOIN categories ON categories.id = events.category_id
            WHERE external_source = ? AND external_id LIKE ?
            ORDER BY event_datetime_utc DESC
            """,
            (external_source, external_id_pattern),
        ).fetchall()
        return [_to_local_dict(row) for row in rows]


def has_external_events(external_source: str, external_id_prefix: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM events WHERE external_source = ? AND external_id LIKE ? LIMIT 1",
            (external_source, f"{external_id_prefix}%"),
        ).fetchone()
        return row is not None


def remove_upcoming_external_events(external_source: str, external_ids: list[str]) -> None:
    if not external_ids:
        return
    with get_connection() as conn:
        conn.executemany(
            "DELETE FROM events WHERE external_source = ? AND external_id = ? AND status = 'UPCOMING'",
            [(external_source, external_id) for external_id in external_ids],
        )


def remove_unwatched_external_events(external_source: str, external_id_pattern: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM events
            WHERE external_source = ? AND external_id LIKE ? AND status IN ('UPCOMING', 'CATCHUP_REQUIRED', 'MISSED')
            """,
            (external_source, external_id_pattern),
        )


def list_follows(entity_type: str | None = None, category_name: str | None = None) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT followed_entities.*, categories.name AS category_name, categories.icon AS category_icon
            FROM followed_entities
            JOIN categories ON categories.id = followed_entities.category_id
            WHERE (? IS NULL OR followed_entities.entity_type = ?)
              AND (? IS NULL OR categories.name = ?)
            ORDER BY categories.id, followed_entities.name COLLATE NOCASE
            """,
            (entity_type, entity_type, category_name, category_name),
        ).fetchall()
        return [dict(row) for row in rows]


def list_followed(entity_type: str, category_name: str | None = None) -> list[str]:
    return [follow["name"] for follow in list_follows(entity_type, category_name)]


def get_follow(follow_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT followed_entities.*, categories.name AS category_name
            FROM followed_entities
            JOIN categories ON categories.id = followed_entities.category_id
            WHERE followed_entities.id = ?
            """,
            (follow_id,),
        ).fetchone()
        return dict(row) if row else None


def follow_entity(
    category_name: str,
    name: str,
    entity_type: str,
    external_id: str | None = None,
    image_url: str | None = None,
) -> bool:
    name = name.strip()
    with get_connection() as conn:
        category = conn.execute(
            "SELECT id FROM categories WHERE name = ?", (category_name,)
        ).fetchone()
        if category is None:
            raise ValueError(f"Unknown category: {category_name}")
        already_followed = conn.execute(
            """
            SELECT 1 FROM followed_entities
            WHERE category_id = ? AND entity_type = ?
              AND (name = ? COLLATE NOCASE OR (? IS NOT NULL AND external_id = ?))
            """,
            (category["id"], entity_type, name, external_id, external_id),
        ).fetchone()
        if already_followed:
            return False
        conn.execute(
            """
            INSERT INTO followed_entities (category_id, name, entity_type, external_id, image_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (category["id"], name, entity_type, external_id, image_url),
        )
        return True


def unfollow(follow_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM followed_entities WHERE id = ?", (follow_id,))


def update_follow(follow_id: int, name: str, external_id: str | None, image_url: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE followed_entities SET name = ?, external_id = ?, image_url = ? WHERE id = ?",
            (name, external_id, image_url, follow_id),
        )
