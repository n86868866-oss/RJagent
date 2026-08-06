from __future__ import annotations

import asyncio


class PyMuPDFClient:
    """Stateless adapter for local PyMuPDF operations."""

    @staticmethod
    async def probe() -> None:
        """Create, serialize, reopen, validate, and close a minimal PDF."""

        await asyncio.to_thread(PyMuPDFClient.probe_sync)

    @staticmethod
    def probe_sync() -> None:
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("PyMuPDF is not installed or cannot be imported.") from error

        document = pymupdf.open()
        try:
            document.new_page()
            payload = document.tobytes()
        finally:
            document.close()

        reopened = pymupdf.open(stream=payload, filetype="pdf")
        try:
            if reopened.page_count != 1:
                raise RuntimeError("PyMuPDF health probe reopened an unexpected page count.")
        finally:
            reopened.close()
