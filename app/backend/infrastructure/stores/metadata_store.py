from __future__ import annotations

import json
from datetime import datetime, timezone

from app.backend.infrastructure.stores.sqlite import SQLiteDatabase
from app.backend.services.papers.models import PaperRecordResult, PaperChunk


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
                chunk_index INTEGER NOT NULL,
                paper_id TEXT NOT NULL,
                paper_name TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                section_id TEXT,
                parent_title TEXT,
                section_title TEXT,
                section_level INTEGER,
                section_index INTEGER,
                text TEXT NOT NULL,
                caption TEXT,
                asset_path TEXT,
                source_order INTEGER,
                content_type TEXT NOT NULL DEFAULT 'text',
                created_at TEXT NOT NULL,
                FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
            )
            """
        )
        await self.ensure_paper_chunk_columns()
        await self.database.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id
            ON paper_chunks(paper_id, chunk_index)
            """
        )
        await self.database.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_chunks_section_id
            ON paper_chunks(paper_id, section_id, chunk_index)
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

    async def ensure_paper_chunk_columns(self) -> None:
        cursor = await self.database.connection.execute("PRAGMA table_info(paper_chunks)")
        rows = await cursor.fetchall()
        existing = {row["name"] for row in rows}

        columns = {
            "paper_name": "TEXT NOT NULL",
            "section_id": "TEXT",
            "parent_title": "TEXT",
            "section_level": "INTEGER",
            "source_order": "INTEGER",
            "caption": "TEXT",
            "asset_path": "TEXT",
            "content_type": "TEXT NOT NULL DEFAULT 'text'",
        }

        for name, definition in columns.items():
            if name not in existing:
                await self.database.connection.execute(
                    f"ALTER TABLE paper_chunks ADD COLUMN {name} {definition}"
                )

    async def ping(self) -> None:
        await self.database.ping()

    async def paper_name_exists(self, paper_name_key: str) -> bool:
        cursor = await self.database.connection.execute(
            "SELECT 1 FROM papers WHERE paper_name_key = ? LIMIT 1",
            (paper_name_key,),
        )
        row = await cursor.fetchone()
        return row is not None

    async def create_paper(
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
        paper_chunks: list[PaperChunk]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self.database.connection.execute(
                """
                INSERT INTO papers (paper_id, paper_name, paper_name_key, filename, file_size_bytes, status, authors, affiliations, journal, publisher, doi, publication_year, source, abstract, parsed_file_paths, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            await self.database.connection.executemany(
                """
                INSERT INTO paper_chunks (chunk_id, chunk_index, paper_id, paper_name, page_start, page_end, section_id, parent_title, section_title, section_level, section_index, text, source_order, caption, asset_path, content_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.chunk_index,
                        chunk.paper_id,
                        chunk.metadata.get("paper_name"),
                        chunk.metadata.get("page_start"),
                        chunk.metadata.get("page_end"),
                        chunk.metadata.get("section_id"),
                        chunk.metadata.get("parent_title"),
                        chunk.metadata.get("section_title"),
                        chunk.metadata.get("section_level"),
                        chunk.metadata.get("section_index"),
                        chunk.text,
                        chunk.metadata.get("source_order"),
                        chunk.metadata.get("caption"),
                        chunk.metadata.get("asset_path"),
                        chunk.metadata.get("content_type"),
                        now,
                    )
                    for chunk in paper_chunks
                ],
            )
            await self.database.connection.commit()
        except Exception:
            await self.database.connection.rollback()
            raise

    async def get_paper_by_id(self, paper_id: str) -> PaperRecordResult | None:
        cursor = await self.database.connection.execute(
            "SELECT * FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        record = dict(row)
        record["authors"] = json.loads(record["authors"] or "[]")
        record["affiliations"] = json.loads(record["affiliations"] or "[]")
        record["parsed_file_paths"] = json.loads(record["parsed_file_paths"] or "{}")
        return PaperRecordResult(**record)

    async def delete_paper(self, paper_id: str) -> None:
        await self.database.connection.execute(
            "DELETE FROM paper_chunks WHERE paper_id = ?",
            (paper_id,),
        )
        await self.database.connection.execute(
            "DELETE FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        await self.database.connection.commit()
