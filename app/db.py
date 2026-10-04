import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import DB_PATH, SCHEMA_PATH, TIER_RULES


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def migrate_add_external_columns() -> None:
    with get_connection() as conn:
        existing_cols = [row["name"] for row in conn.execute("PRAGMA table_info(events)")]
        if "external_source" not in existing_cols:
            conn.execute("ALTER TABLE events ADD COLUMN external_source TEXT")
        if "external_id" not in existing_cols:
            conn.execute("ALTER TABLE events ADD COLUMN external_id TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_external
            ON events(external_source, external_id)
            WHERE external_id IS NOT NULL
            """
        )


def migrate_add_watch_history_columns() -> None:
    with get_connection() as conn:
        _ensure_columns(conn, "watch_history", {"previous_status": "TEXT"})


def migrate_add_ui_columns() -> None:
    with get_connection() as conn:
        _ensure_columns(conn, "events", {"image_url": "TEXT", "group_key": "TEXT", "group_title": "TEXT"})
        _ensure_columns(conn, "followed_entities", {"external_id": "TEXT", "image_url": "TEXT"})


def migrate_tier_rules() -> None:
    with get_connection() as conn:
        _ensure_columns(
            conn,
            "events",
            {"rule_key": "TEXT", "tier_locked": "INTEGER NOT NULL DEFAULT 0", "details_json": "TEXT"},
        )
        _ensure_columns(conn, "followed_entities", {"status_note": "TEXT"})
        _ensure_columns(conn, "interest_settings", {"tier": "TEXT"})
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media_cache (
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                data_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (source, external_id)
            )
            """
        )
        for category, rules in TIER_RULES.items():
            for key, label, default_tier in rules:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled, tier)
                    SELECT id, ?, ?, 1, ? FROM categories WHERE name = ?
                    """,
                    (key, label, default_tier, category),
                )
                conn.execute(
                    """
                    UPDATE interest_settings
                    SET label = ?, tier = CASE WHEN enabled = 0 THEN 'off' ELSE ? END
                    WHERE setting_key = ? AND tier IS NULL
                    """,
                    (label, default_tier, key),
                )
                conn.execute("UPDATE interest_settings SET label = ? WHERE setting_key = ?", (label, key))


def get_meta(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def import_catalog_seed(seed_path: Path) -> bool:
    if not seed_path.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT COUNT(*) FROM catalog_entities").fetchone()[0]:
            return False
        conn.execute("ATTACH DATABASE ? AS seed", (str(seed_path),))
        conn.execute(
            """
            INSERT OR IGNORE INTO catalog_entities
                (category_id, entity_type, external_id, name, short_name, detail, image_url, is_active, updated_at)
            SELECT categories.id, seed.catalog_entities.entity_type, seed.catalog_entities.external_id,
                   seed.catalog_entities.name, seed.catalog_entities.short_name, seed.catalog_entities.detail,
                   seed.catalog_entities.image_url, seed.catalog_entities.is_active, seed.catalog_entities.updated_at
            FROM seed.catalog_entities
            JOIN categories ON categories.name = seed.catalog_entities.category_name
            """
        )
        conn.execute("INSERT OR IGNORE INTO app_meta (key, value) SELECT key, value FROM seed.app_meta")
        conn.commit()
        conn.execute("DETACH DATABASE seed")
        return True
    finally:
        conn.close()


def write_catalog_seed(source_path: Path, seed_path: Path) -> int:
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    seed = sqlite3.connect(seed_path)
    try:
        seed.executescript(
            """
            CREATE TABLE catalog_entities (
                category_name TEXT NOT NULL, entity_type TEXT NOT NULL, external_id TEXT NOT NULL,
                name TEXT NOT NULL, short_name TEXT, detail TEXT, image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 0, updated_at TEXT
            );
            CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        rows = source.execute(
            """
            SELECT categories.name, entity_type, external_id, catalog_entities.name, short_name, detail,
                   image_url, is_active, updated_at
            FROM catalog_entities JOIN categories ON categories.id = catalog_entities.category_id
            """
        ).fetchall()
        seed.executemany("INSERT INTO catalog_entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        seed.executemany(
            "INSERT INTO app_meta VALUES (?, ?)",
            source.execute("SELECT key, value FROM app_meta WHERE key LIKE 'catalog_refreshed_at:%'").fetchall(),
        )
        seed.commit()
        return len(rows)
    finally:
        source.close()
        seed.close()


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()