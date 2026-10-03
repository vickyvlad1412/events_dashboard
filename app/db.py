import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import DB_PATH, DATA_DIR


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).resolve().parent / "models" / "schema.sql"
    with get_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))


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