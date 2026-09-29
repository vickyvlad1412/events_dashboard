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