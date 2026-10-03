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
    image_url TEXT,
    group_key TEXT,
    group_title TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS followed_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,   -- 'team' | 'player' | 'anime' | 'movie'
    external_id TEXT,
    image_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS catalog_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    entity_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT,
    detail TEXT,
    image_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category_id, entity_type, external_id)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    watched_at TEXT NOT NULL DEFAULT (datetime('now')),
    watched_mode TEXT,   -- 'LIVE' | 'HIGHLIGHTS' | 'VOD' | 'CINEMA'
    previous_status TEXT
);

CREATE TABLE IF NOT EXISTS interest_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    setting_key TEXT NOT NULL,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(category_id, setting_key)
);

INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'f1_qualifying', 'Qualifying', 1 FROM categories WHERE name = 'f1';
INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'f1_practice', 'Practice sessions', 0 FROM categories WHERE name = 'f1';

INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'football_champions_league', 'Champions League', 1 FROM categories WHERE name = 'football';
INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'football_other_pl', 'Other Premier League matches (not Liverpool)', 0 FROM categories WHERE name = 'football';
INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'football_international_tournaments', 'International tournaments (World Cup, Euro, Copa América, AFCON)', 1 FROM categories WHERE name = 'football';

INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'dota_ti', 'The International', 1 FROM categories WHERE name = 'dota';
UPDATE interest_settings SET setting_key = 'dota_tier1', label = 'Tier 1 Tournaments' WHERE setting_key = 'dota_majors';
INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'dota_tier1', 'Tier 1 Tournaments', 1 FROM categories WHERE name = 'dota';
INSERT OR IGNORE INTO interest_settings (category_id, setting_key, label, enabled)
SELECT id, 'dota_followed_players', 'Matches involving followed players/teams', 1 FROM categories WHERE name = 'dota';
