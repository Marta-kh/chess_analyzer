-- Migration 002: Engine registry persistence and position evaluation cache
CREATE TABLE IF NOT EXISTS registered_engines (
    engine_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    version_build TEXT NOT NULL,
    binary_path TEXT NOT NULL,
    is_bundled INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    transport_type TEXT NOT NULL DEFAULT 'subprocess',
    visible_variations INTEGER NOT NULL DEFAULT 1,
    threads INTEGER NOT NULL DEFAULT 1,
    hash_mb INTEGER NOT NULL DEFAULT 16,
    max_depth INTEGER DEFAULT 12,
    movetime_ms INTEGER
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key TEXT PRIMARY KEY,
    fen TEXT NOT NULL,
    move_history_hash TEXT NOT NULL,
    engine_id TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    multipv INTEGER NOT NULL,
    search_depth INTEGER NOT NULL,
    variations_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
