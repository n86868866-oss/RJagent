from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from app.backend.config import Settings


class MinerUProtocolError(RuntimeError):
    """Raised when the MinerU health response is invalid."""


class MinerUServiceError(RuntimeError):
    """Raised when the MinerU service cannot complete a parsing request."""

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True, slots=True)
class MinerUParseResult:
    files: dict[str, bytes]
    payload: Any | None
    content_type: str


class MinerUClient:
    """Shared HTTP connection for the MinerU parsing service."""

    def __init__(self, http_client: httpx.AsyncClient, mode: str, backend: str) -> None:
        self.http_client = http_client
        self.mode = mode
        self.backend = backend

    @property
    def parse_url(self) -> str:
        return str(self.http_client.base_url).rstrip("/") + "/file_parse"

    @classmethod
    def from_settings(cls, settings: Settings) -> "MinerUClient":
        if settings.mineru_mode == "cloud_api":
            base_url = settings.mineru_api_base
            assert base_url is not None
            assert settings.mineru_api_token is not None
            headers = {
                "Authorization": f"Bearer {settings.mineru_api_token.get_secret_value()}"
            }
        else:
            base_url = settings.mineru_base_url
            headers = {}

        return cls(
            http_client=httpx.AsyncClient(
                base_url=base_url.rstrip("/") + "/",
                headers=headers,
                timeout=settings.mineru_timeout_seconds,
                trust_env=False,
            ),
            mode=settings.mineru_mode,
            backend=settings.mineru_backend,
        )

    async def probe(self) -> None:
        """Call MinerU's documented lightweight GET /health endpoint."""

        response = await self.http_client.get("health")
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as error:
            raise MinerUProtocolError("MinerU health endpoint returned non-JSON content.") from error

        if not isinstance(payload, dict):
            raise MinerUProtocolError("MinerU health endpoint returned an invalid JSON object.")

    async def parse_pdf(self, file_path: Path, *, start_page_id: int | None = None, end_page_id: int | None = None) -> MinerUParseResult:
        """Parse one PDF through MinerU's HTTP API."""

        data: dict[str, str] = {
            "backend": self.backend,
            "parse_method": "auto",
            "return_md": "true",
            "return_middle_json": "true",
            "return_content_list": "true",
            "response_format_zip": "true",
            "return_original_file": "false",
        }
        if start_page_id is not None:
            data["start_page_id"] = str(start_page_id)
        if end_page_id is not None:
            data["end_page_id"] = str(end_page_id)

        payload = await asyncio.to_thread(file_path.read_bytes)
        files = {"files": (file_path.name, payload, "application/pdf"),}

        try:
            response = await self.http_client.post("file_parse", data=data, files=files)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise MinerUServiceError("MinerU解析请求超时") from error
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            response_body = self.summarize_error_body(error.response)
            raise MinerUServiceError(f"MinerU解析请求返回HTTP {status_code}", status_code=status_code, response_body=response_body) from error
        except httpx.HTTPError as error:
            raise MinerUServiceError("MinerU解析请求失败") from error

        return self.parse_response(response)

    @staticmethod
    def summarize_error_body(response: httpx.Response, *, max_chars: int = 500) -> str | None:
        text = response.text.strip()
        if not text:
            return None
        return " ".join(text.split())[:max_chars]

    @staticmethod
    def parse_response(response: httpx.Response) -> MinerUParseResult:
        content_type = response.headers.get("content-type", "")
        content = response.content

        if content.startswith(b"PK\x03\x04") or "zip" in content_type.lower():
            return MinerUParseResult(
                files=MinerUClient.read_zip_files(content),
                payload=None,
                content_type=content_type,
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise MinerUProtocolError("MinerU parsing endpoint returned neither ZIP nor JSON content.") from error

        return MinerUParseResult(
            files={"mineru_response.json": json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")},
            payload=payload,
            content_type=content_type,
        )

    @staticmethod
    def read_zip_files(content: bytes) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                files[member.filename] = archive.read(member)
        if not files:
            raise MinerUProtocolError("MinerU parsing ZIP response did not contain files.")
        return files

    async def close(self) -> None:
        await self.http_client.aclose()
