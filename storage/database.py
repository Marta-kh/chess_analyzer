"""SQLite connection manager and versioned schema migration runner."""
import sqlite3
from pathlib import Path
from typing import List, Optional


class DatabaseManager:
    """
    Manages SQLite connections with foreign keys enabled, WAL journaling,
    transactional context management, and automatic schema migrations.
    """

    def __init__(self, db_path: str = ":memory:", migrations_dir: Optional[Path] = None) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir or (Path(__file__).resolve().parent / "migrations")
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode = WAL;")
            except sqlite3.OperationalError:
                self._conn.execute("PRAGMA journal_mode = DELETE;")
        self.run_migrations()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def run_migrations(self) -> List[str]:
        """Apply any unapplied SQL migrations in lexicographical order within transactions."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
        applied_rows = self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        applied = {r["version"] for r in applied_rows}

        newly_applied: List[str] = []
        if self.migrations_dir.exists():
            sql_files = sorted(self.migrations_dir.glob("*.sql"))
            for sql_file in sql_files:
                ver = sql_file.name
                if ver in applied:
                    continue
                script = sql_file.read_text(encoding="utf-8")
                with self._conn:
                    self._conn.executescript(script)
                    self._conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (ver,))
                newly_applied.append(ver)
        return newly_applied

    def get_applied_migrations(self) -> List[str]:
        rows = self._conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return [r["version"] for r in rows]

    def close(self) -> None:
        self._conn.close()
