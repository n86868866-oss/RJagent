from __future__ import annotations

import json
from datetime import datetime, timezone

from app.backend.infrastructure.stores.sqlite import SQLiteDatabase


class MetadataStore:
    """Metadata persistence entry point.

    Business CRUD methods will be added with the paper, chat, and preference modules.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    async def initialize(self) -> None:
        await self.database.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                paper_name TEXT NOT NULL,
                paper_name_key TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                status TEXT NOT NULL,
                authors TEXT NOT NULL DEFAULT '[]',
                affiliations TEXT NOT NULL DEFAULT '[]',
                journal TEXT,
                publisher TEXT,
                doi TEXT,
                publication_year INTEGER,
                source TEXT,
                abstract TEXT,
                parsed_file_paths TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.ensure_paper_metadata_columns()
        await self.database.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_chunks (
                chunk_id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                section_title TEXT,
                section_index INTEGER,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
            )
            """
        )
        await self.database.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id
            ON paper_chunks(paper_id, chunk_index)
            """
        )
        await self.database.connection.commit()

    async def ensure_paper_metadata_columns(self) -> None:
        cursor = await self.database.connection.execute("PRAGMA table_info(papers)")
        rows = await cursor.fetchall()
        existing = {row["name"] for row in rows}
        columns = {
            "authors": "TEXT NOT NULL DEFAULT '[]'",
            "affiliations": "TEXT NOT NULL DEFAULT '[]'",
            "journal": "TEXT",
            "publisher": "TEXT",
            "doi": "TEXT",
            "publication_year": "INTEGER",
            "source": "TEXT",
            "abstract": "TEXT",
        }
        for name, definition in columns.items():
            if name in existing:
                continue
            await self.database.connection.execute(f"ALTER TABLE papers ADD COLUMN {name} {definition}")

    async def ping(self) -> None:
        await self.database.ping()

    async def paper_name_exists(self, paper_name_key: str) -> bool:
        cursor = await self.database.connection.execute(
            "SELECT 1 FROM papers WHERE paper_name_key = ? LIMIT 1",
            (paper_name_key,),
        )
        row = await cursor.fetchone()
        return row is not None

    async def create_parsed_paper(
        self,
        *,
        paper_id: str,
        paper_name: str,
        paper_name_key: str,
        filename: str,
        file_size_bytes: int,
        status: str,
        authors: list[str],
        affiliations: list[str],
        journal: str | None,
        publisher: str | None,
        doi: str | None,
        publication_year: int | None,
        source: str | None,
        abstract: str | None,
        parsed_file_paths: dict[str, str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.database.connection.execute(
            """
            INSERT INTO papers (
                paper_id,
                paper_name,
                paper_name_key,
                filename,
                file_size_bytes,
                status,
                authors,
                affiliations,
                journal,
                publisher,
                doi,
                publication_year,
                source,
                abstract,
                parsed_file_paths,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                paper_name,
                paper_name_key,
                filename,
                file_size_bytes,
                status,
                json.dumps(authors, ensure_ascii=False),
                json.dumps(affiliations, ensure_ascii=False),
                journal,
                publisher,
                doi,
                publication_year,
                source,
                abstract,
                json.dumps(parsed_file_paths, ensure_ascii=False),
                now,
                now,
            ),
        )
        await self.database.connection.commit()
