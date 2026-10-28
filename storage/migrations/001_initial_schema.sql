-- Migration 001: Core tables for sessions, moves, custom positions, classifications, and preferences
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    title TEXT NOT NULL,
    initial_fen TEXT NOT NULL,
    original_pgn TEXT,
    white_player TEXT NOT NULL,
    black_player TEXT NOT NULL,
    white_elo INTEGER,
    black_elo INTEGER,
    event TEXT,
    site TEXT,
    date_str TEXT,
    result TEXT NOT NULL,
    time_control TEXT,
    game_type TEXT,
    source TEXT NOT NULL,
    external_id TEXT,
    external_url TEXT,
    player_username TEXT,
    player_color TEXT,
    is_finished INTEGER NOT NULL DEFAULT 0,
    classification_enabled INTEGER NOT NULL DEFAULT 0,
    has_per_game_override INTEGER NOT NULL DEFAULT 0,
    classification_stale INTEGER NOT NULL DEFAULT 0,
    cursor_ply INTEGER NOT NULL DEFAULT 0,
    is_flipped INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_moves (
    session_id TEXT NOT NULL,
    ply INTEGER NOT NULL,
    uci TEXT NOT NULL,
    san TEXT NOT NULL,
    fen_before TEXT NOT NULL,
    fen_after TEXT NOT NULL,
    turn_before TEXT NOT NULL,
    fullmove_number INTEGER NOT NULL,
    is_capture INTEGER NOT NULL DEFAULT 0,
    is_check INTEGER NOT NULL DEFAULT 0,
    is_checkmate INTEGER NOT NULL DEFAULT 0,
    is_castling INTEGER NOT NULL DEFAULT 0,
    is_en_passant INTEGER NOT NULL DEFAULT 0,
    promotion TEXT,
    comment TEXT,
    PRIMARY KEY (session_id, ply),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS move_classifications (
    session_id TEXT NOT NULL,
    ply INTEGER NOT NULL,
    played_uci TEXT NOT NULL,
    played_san TEXT NOT NULL,
    mover_color TEXT NOT NULL,
    quality TEXT NOT NULL,
    badge_symbol TEXT NOT NULL,
    badge_text TEXT NOT NULL,
    eval_before_cp INTEGER,
    eval_before_mate INTEGER,
    eval_before_pov TEXT,
    eval_after_cp INTEGER,
    eval_after_mate INTEGER,
    eval_after_pov TEXT,
    best_move_uci TEXT,
    best_move_san TEXT,
    cp_loss INTEGER NOT NULL,
    win_prob_loss REAL NOT NULL,
    engine_id TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    search_depth INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    explanation TEXT NOT NULL,
    PRIMARY KEY (session_id, ply),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS saved_positions (
    position_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fen TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    pref_key TEXT PRIMARY KEY,
    pref_value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
