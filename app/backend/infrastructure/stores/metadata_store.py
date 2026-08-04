from __future__ import annotations

from app.backend.infrastructure.stores.sqlite import SQLiteDatabase


class MetadataStore:
    """Metadata persistence entry point.

    Business CRUD methods will be added with the paper, chat, and preference modules.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    async def ping(self) -> None:
        await self.database.ping()
