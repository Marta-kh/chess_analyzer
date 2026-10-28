-- Migration 003: Persist user-created non-destructive move variants per session
CREATE TABLE IF NOT EXISTS session_variants (
    session_id TEXT NOT NULL,
    variant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    branch_ply INTEGER NOT NULL,
    nodes_json TEXT NOT NULL,
    PRIMARY KEY (session_id, variant_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
