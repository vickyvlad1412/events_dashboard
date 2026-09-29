import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import DB_PATH, DATA_DIR


def init_db() -> None:
    """Create the data folder and tables if they don't exist yet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).resolve().parent / "models" / "schema.sql"
    with get_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))


def migrate_add_external_columns() -> None:
    """One-time migration: adds columns needed to dedupe connector-fetched events."""
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


@contextmanager
def get_connection():
    """Yields a sqlite3 connection with dict-like row access, commits on success."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()