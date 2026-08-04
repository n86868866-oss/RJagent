from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from app.backend.config import Settings


class FileStore:
    """Own application data directories and verify real read/write access."""

    def __init__(self, directories: dict[str, Path]) -> None:
        self.directories = directories

    @classmethod
    def from_settings(cls, settings: Settings) -> "FileStore":
        return cls(
            {
                "data": settings.project_path(settings.data_dir),
                "raw": settings.project_path(settings.raw_pdf_dir),
                "parsed": settings.project_path(settings.parsed_document_dir),
                "assets": settings.project_path(settings.document_asset_dir),
                "qdrant": settings.project_path(settings.qdrant_path),
            }
        )

    async def initialize(self) -> None:
        for path in self.directories.values():
            path.mkdir(parents=True, exist_ok=True)
        await self.check_writable()

    async def check_writable(self) -> None:
        """Create, persist, read, and delete one probe file per directory."""

        await asyncio.gather(
            *(
                asyncio.to_thread(self._probe_directory, name, path)
                for name, path in self.directories.items()
            )
        )

    @staticmethod
    def _probe_directory(name: str, path: Path) -> None:
        if not path.is_dir():
            raise RuntimeError(f"Data directory '{name}' does not exist: {path}")

        probe_path = path / f".health-{uuid4().hex}.tmp"
        payload = b"research-journey-agent-health"

        try:
            with probe_path.open("wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())

            if probe_path.read_bytes() != payload:
                raise RuntimeError(
                    f"Data directory '{name}' failed its read-after-write probe."
                )
        finally:
            probe_path.unlink(missing_ok=True)
