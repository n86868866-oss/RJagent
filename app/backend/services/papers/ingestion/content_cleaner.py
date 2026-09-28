from __future__ import annotations


from html import unescape
from io import StringIO
import re
import unicodedata

from lxml import etree, html as lxml_html
import pandas as pd
from pylatexenc.latex2text import LatexNodes2Text


SENTENCE_END_RE = re.compile(r'[.!?\u3002\uff01\uff1f](?:["\u201d\u2019)\]]|\s)*$')
MATH_EXPRESSION_RE = re.compile(r"\$\$(?P<display>.*?)\$\$|\$(?P<inline>(?:\\.|[^$])*)\$", re.DOTALL)
SPACED_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]\s+){2,}[A-Za-z](?![A-Za-z0-9])")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


class ContentCleaner:
    def __init__(self) -> None:
        self.latex_converter = LatexNodes2Text(math_mode="text")

    def clean_item_text(self, item: dict) -> str:
        content_type = str(item.get("type") or "")

        if content_type == "list":
            values = item.get("list_items")
            if not isinstance(values, list):
                return ""
            return "\n".join(self.normalize_paragraph(value) for value in values if isinstance(value, str) and value.strip()).strip()

        if content_type == "code":
            values = [
                self.join_text(item.get("code_caption")),
                item.get("code_body") if isinstance(item.get("code_body"), str) else "",
                self.join_text(item.get("code_footnote")),
            ]
            lines: list[str] = []
            for value in values:
                if not value.strip():
                    continue
                normalized = self.normalize_latex_text(self.strip_inline_html(value))
                lines.extend(line.strip() for line in normalized.splitlines() if line.strip())
            return "\n".join(lines)

        text = item.get("text")
        if not isinstance(text, str):
            return ""
        return self.normalize_paragraph(text)

    def table_to_markdown(self, item: dict) -> str:
        table_body = item.get("table_body")
        if not isinstance(table_body, str) or not table_body.strip():
            raise ValueError("表格正文缺失")

        header_rows = self.table_header_rows(table_body)
        header = list(range(header_rows)) if header_rows > 1 else 0
        frames = pd.read_html(StringIO(table_body), header=header, flavor="lxml")
        if not frames:
            raise ValueError("表格解析失败")

        frame = frames[0].fillna("")
        frame.columns = self.flatten_table_columns(frame.columns)
        return self.normalize_latex_text(frame.to_markdown(index=False))

    def visual_text(self, item: dict, *, caption: str | None = None) -> str:
        resolved_caption = caption if caption is not None else self.visual_caption(item)
        content = item.get("content") if isinstance(item.get("content"), str) else ""
        footnote = self.join_text(item.get("chart_footnote") or item.get("image_footnote"))
        return "\n\n".join(
            value
            for value in (
                self.normalize_paragraph(resolved_caption),
                self.normalize_paragraph(content),
                self.normalize_paragraph(footnote),
            )
            if value
        )

    def visual_caption(self, item: dict) -> str:
        return self.normalize_paragraph(self.join_text(item.get("chart_caption") or item.get("image_caption")))

    def normalize_latex_text(self, text: str) -> str:
        def replace_expression(match: re.Match[str]) -> str:
            expression = match.group("display") if match.group("display") is not None else match.group("inline")
            return self.latex_expression_to_text(expression or "")

        return MATH_EXPRESSION_RE.sub(replace_expression, text)

    def latex_expression_to_text(self, expression: str) -> str:
        expression = re.sub(r"\\operatorname\s*\*", r"\\operatorname", expression)
        expression = re.sub(r"\s*([_^])\s*\{\s*", r"\1{", expression)
        expression = re.sub(r"\{\s+", "{", expression)
        expression = re.sub(r"\s+\}", "}", expression)
        converted = self.latex_converter.latex_to_text(expression)
        converted = unicodedata.normalize("NFKC", converted)
        converted = SPACED_IDENTIFIER_RE.sub(lambda match: re.sub(r"\s+", "", match.group(0)), converted)
        converted = re.sub(r"\s*_\s*", "_", converted)
        converted = re.sub(r"_([A-Za-z0-9]+)\s*=\s*([A-Za-z0-9.]+)\s*\^\s*([A-Za-z0-9]+)", r"_{\1=\2}^\3", converted)
        converted = re.sub(r"([({\[])\s+", r"\1", converted)
        converted = re.sub(r"\s+([,.;:)}\]])", r"\1", converted)
        converted = re.sub(r"\s*([=+\u00b7\u2264\u2265])\s*", r" \1 ", converted)
        converted = re.sub(r"_\{([^{}]+)\}", lambda match: "_{" + re.sub(r"\s*=\s*", "=", match.group(1)) + "}", converted)
        return re.sub(r"\s+", " ", converted).strip()

    def normalize_paragraph(self, text: str) -> str:
        text = self.strip_inline_html(text)
        text = self.normalize_latex_text(text)
        text = re.sub(r"(?<!\.)\.\s*,", ",", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return re.sub(r"[ \t]*\n+[ \t]*", " ", text).strip()

    @staticmethod
    def strip_inline_html(text: str) -> str:
        if not HTML_TAG_RE.search(text):
            return unescape(text)
        try:
            root = lxml_html.fragment_fromstring(text, create_parent="div")
            return unescape(root.text_content())
        except (etree.ParserError, TypeError, ValueError):
            return unescape(HTML_TAG_RE.sub("", text))

    @staticmethod
    def sentence_finished(text: str) -> bool:
        return SENTENCE_END_RE.search(text.rstrip()) is not None

    @staticmethod
    def join_text(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return " ".join(part.strip() for part in value if isinstance(part, str) and part.strip())
        return ""

    @staticmethod
    def table_header_rows(table_body: str) -> int:
        try:
            table = lxml_html.fromstring(table_body)
            rows = table.xpath(".//tr")
            if not rows:
                return 1
            first_cells = rows[0].xpath("./th|./td")
            row_span = max((int(cell.get("rowspan", "1")) for cell in first_cells), default=1)
            has_column_span = any(int(cell.get("colspan", "1")) > 1 for cell in first_cells)
            return min(len(rows), max(row_span, 2 if has_column_span else 1))
        except (TypeError, ValueError, etree.ParserError):
            return 1

    @staticmethod
    def flatten_table_columns(columns: pd.Index) -> list[str]:
        flattened: list[str] = []
        for column in columns:
            values = column if isinstance(column, tuple) else (column,)
            parts: list[str] = []
            for value in values:
                text = str(value).strip()
                if not text or text.lower().startswith("unnamed:") or (parts and parts[-1] == text):
                    continue
                parts.append(text)
            flattened.append(" / ".join(parts) or "column")
        return flattened
