from __future__ import annotations

import asyncio
import os
import re
import shutil
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
                "qdrant": settings.project_path(settings.qdrant_path),
            }
        )

    async def initialize(self) -> None:
        for path in self.directories.values():
            path.mkdir(parents=True, exist_ok=True)
        await self.check_writable()

    async def check_writable(self) -> None:
        """Create, persist, read, and delete one probe file per directory."""

        await asyncio.gather(*(asyncio.to_thread(self.probe_directory, name, path) for name, path in self.directories.items()))

    @staticmethod
    def probe_directory(name: str, path: Path) -> None:
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
                raise RuntimeError(f"Data directory '{name}' failed its read-after-write probe.")
        finally:
            probe_path.unlink(missing_ok=True)

    async def save_temporary_upload(self, *, paper_id: str, filename: str, payload: bytes) -> Path:
        safe_name = self.safe_filename(filename, fallback=f"{paper_id}.pdf")
        target_dir = self.directories["data"] / "tmp" / "uploads" / paper_id
        target_path = target_dir / safe_name
        await asyncio.to_thread(self.write_bytes, target_path, payload)
        return target_path

    async def promote_uploaded_pdf(self, *, source_path: Path, paper_id: str, filename: str) -> Path:
        safe_name = self.safe_filename(filename, fallback=f"{paper_id}.pdf")
        target_path = self.directories["raw"] / paper_id / safe_name
        await asyncio.to_thread(self.move_file, source_path, target_path)
        return target_path

    async def discard_temporary_upload(self, path: Path) -> None:
        temp_root = self.directories["data"] / "tmp"
        await asyncio.to_thread(self.remove_tree_within, path.parent, temp_root)

    async def remove_paper_artifacts(self, paper_id: str) -> None:
        await asyncio.gather(
            asyncio.to_thread(self.remove_tree_within, self.directories["raw"] / paper_id, self.directories["raw"]),
            asyncio.to_thread(self.remove_tree_within, self.directories["parsed"] / paper_id, self.directories["parsed"]),
        )

    async def save_mineru_parse_files(self, *, paper_id: str, files: dict[str, bytes], normalized_text: str) -> dict[str, str]:
        target_dir = self.directories["parsed"] / paper_id

        saved: dict[str, Path] = {}
        selected_files = {
            "markdown": self.select_file(files, suffix=".md"),
            "content_list": self.select_legacy_content_list(files),
            "middle": self.select_file(files, contains="middle", suffix=".json"),
            "layout_pdf": self.select_file(files, contains="layout", suffix=".pdf"),
            "span_pdf": self.select_file(files, contains="span", suffix=".pdf"),
        }

        canonical_names = {
            "markdown": "mineru.md",
            "content_list": "content_list.json",
            "middle": "middle.json",
            "layout_pdf": "layout.pdf",
            "span_pdf": "span.pdf",
        }
        for key, item in selected_files.items():
            if item is None:
                continue
            saved[key] = target_dir / canonical_names[key]
            await asyncio.to_thread(self.write_bytes, saved[key], item[1])

        image_files = self.select_image_files(files)
        for relative_path, image_payload in image_files.items():
            await asyncio.to_thread(self.write_bytes, target_dir / Path(relative_path), image_payload)
        if image_files:
            saved["images_dir"] = target_dir / "images"

        saved["normalized_text"] = target_dir / "normalized_text.txt"
        await asyncio.to_thread(self.write_text, saved["normalized_text"], normalized_text)

        return {key: str(path) for key, path in saved.items()}

    @staticmethod
    def write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def move_file(source_path: Path, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(target_path))

    @staticmethod
    def remove_tree_within(path: Path, base: Path) -> None:
        resolved_path = path.resolve()
        resolved_base = base.resolve()
        try:
            resolved_path.relative_to(resolved_base)
        except ValueError as error:
            raise RuntimeError(f"Refusing to remove path outside data directory: {resolved_path}") from error
        if resolved_path == resolved_base:
            raise RuntimeError(f"Refusing to remove data directory root: {resolved_path}")
        if resolved_path.exists():
            shutil.rmtree(resolved_path)

    @staticmethod
    def select_file(files: dict[str, bytes], *, suffix: str, contains: str | None = None) -> tuple[str, bytes] | None:
        suffix = suffix.lower()
        contains = contains.lower() if contains else None
        for name, payload in files.items():
            normalized = name.replace("\\", "/").split("/")[-1].lower()
            if not normalized.endswith(suffix):
                continue
            if contains and contains not in normalized:
                continue
            return name, payload
        return None

    @staticmethod
    def select_legacy_content_list(files: dict[str, bytes]) -> tuple[str, bytes] | None:
        for name, payload in files.items():
            normalized = name.replace("\\", "/").split("/")[-1].lower()
            if normalized == "content_list.json" or normalized.endswith("_content_list.json"):
                return name, payload
        return None

    @staticmethod
    def select_image_files(files: dict[str, bytes]) -> dict[str, bytes]:
        selected: dict[str, bytes] = {}
        for name, payload in files.items():
            parts = [part for part in name.replace("\\", "/").split("/") if part]
            if "images" not in parts:
                continue
            image_index = len(parts) - 1 - parts[::-1].index("images")
            relative_parts = parts[image_index:]
            if len(relative_parts) < 2 or any(part in {".", ".."} for part in relative_parts):
                continue
            selected["/".join(relative_parts)] = payload
        return selected

    @staticmethod
    def safe_filename(filename: str, *, fallback: str) -> str:
        name = Path(filename or fallback).name.strip()
        if not name:
            name = fallback
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
        return name or fallback
