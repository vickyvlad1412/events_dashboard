CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    icon TEXT
);

INSERT OR IGNORE INTO categories (name, icon) VALUES
    ('f1', '🏎'),
    ('football', '⚽'),
    ('dota', '🎮'),
    ('anime', '📺'),
    ('movie', '🎬');

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title TEXT NOT NULL,
    subtitle TEXT,
    event_datetime_utc TEXT NOT NULL,     -- ISO 8601 in UTC, e.g. 2026-10-04T14:00:00
    source_timezone TEXT,                  -- optional note, e.g. "CET"
    venue TEXT,
    priority_tier TEXT NOT NULL DEFAULT 'C'
        CHECK (priority_tier IN ('A','B','C','D')),
    live_preference TEXT NOT NULL DEFAULT 'ANYTIME'
        CHECK (live_preference IN ('LIVE','HIGHLIGHTS','VOD','ANYTIME','CINEMA')),
    status TEXT NOT NULL DEFAULT 'UPCOMING'
        CHECK (status IN ('UPCOMING','LIVE','COMPLETED','WATCHED','MISSED','CATCHUP_REQUIRED')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS followed_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,   -- 'team' | 'player' | 'anime' | 'movie'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    watched_at TEXT NOT NULL DEFAULT (datetime('now')),
    watched_mode TEXT   -- 'LIVE' | 'HIGHLIGHTS' | 'VOD' | 'CINEMA'
);