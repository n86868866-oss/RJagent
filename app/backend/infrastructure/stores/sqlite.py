from __future__ import annotations

from pathlib import Path
from typing import Any


class SQLiteDatabase:
    """Own the shared aiosqlite connection used by metadata stores."""

    def __init__(self, connection: Any, path: Path) -> None:
        self.connection = connection
        self.path = path

    @classmethod
    async def connect(cls, path: Path, *, busy_timeout_ms: int, enable_wal: bool) -> "SQLiteDatabase":
        try:
            import aiosqlite
        except ImportError as error:  # pragma: no cover - environment failure
            raise RuntimeError("aiosqlite is required. Install the packages from requirements.txt.") from error

        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(path)
        connection.row_factory = aiosqlite.Row

        await connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        await connection.execute("PRAGMA foreign_keys = ON")
        if enable_wal:
            await connection.execute("PRAGMA journal_mode = WAL")
        await connection.commit()

        database = cls(connection=connection, path=path)
        try:
            await database.initialize_schema_version_table()
        except Exception:
            await connection.close()
            raise
        return database

    async def initialize_schema_version_table(self) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)
            """
        )
        cursor = await self.connection.execute("SELECT COUNT(*) AS count FROM schema_version")
        row = await cursor.fetchone()
        if row["count"] == 0:
            await self.connection.execute("INSERT INTO schema_version(version) VALUES (?)", (1,))
        await self.connection.commit()

    async def ping(self) -> None:
        cursor = await self.connection.execute("SELECT 1 AS ok")
        row = await cursor.fetchone()
        if row is None or row["ok"] != 1:
            raise RuntimeError("SQLite health query returned an invalid result.")

    async def close(self) -> None:
        await self.connection.close()
