"""Small repeatable SQLite initialization and transaction boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from editorial_agent.errors import PersistedDataError

SCHEMA_VERSION = 2
DEFAULT_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "001_initial_domain.sql"
)
STAGE3_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "002_stage3_events.sql"
)


class SQLiteDatabase:
    """Open initialized SQLite connections with foreign keys enabled."""

    def __init__(
        self,
        path: Path,
        *,
        migration_path: Path = DEFAULT_MIGRATION_PATH,
        stage3_migration_path: Path = STAGE3_MIGRATION_PATH,
    ) -> None:
        self.path = path
        self._migration_path = migration_path
        self._stage3_migration_path = stage3_migration_path

    def initialize(self) -> None:
        """Create or verify the one supported schema version."""

        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, SCHEMA_VERSION}:
                raise PersistedDataError("Unsupported database schema version.")
            try:
                if version == 0:
                    migration = self._migration_path.read_text(encoding="utf-8")
                    connection.executescript(migration)
                    connection.execute("PRAGMA user_version = 1")
                    connection.commit()
                    version = 1
                if version == 1:
                    migration = self._stage3_migration_path.read_text(
                        encoding="utf-8"
                    )
                    connection.executescript(migration)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            except (OSError, sqlite3.Error) as exc:
                raise PersistedDataError("Database initialization failed.") from exc

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield one configured connection and close it reliably."""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Yield an explicit transaction and commit or roll back atomically."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
