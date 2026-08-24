from __future__ import annotations

from collections import deque
from io import StringIO
import re
import unicodedata

from langchain_core.documents import Document
from lxml import etree, html
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
import pandas as pd
from pylatexenc.latex2text import LatexNodes2Text


SENTENCE_END_RE = re.compile(r'[.!?\u3002\uff01\uff1f](?:["\u201d\u2019)\]]|\s)*$')
MARKDOWN_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)")
DISPLAY_MATH_RE = re.compile(r"^\s*\$\$.*\$\$\s*$", re.DOTALL)
MATH_EXPRESSION_RE = re.compile(r"\$\$(?P<display>.*?)\$\$|\$(?P<inline>(?:\\.|[^$])*)\$", re.DOTALL)
SPACED_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]\s+){2,}[A-Za-z](?![A-Za-z0-9])")
ROMAN_NUMERAL_RE = re.compile(r"^(?=[MDCLXVI]+$)M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
COMMON_TOP_LEVEL_TITLES = {
    "abstract",
    "acknowledgment",
    "acknowledgments",
    "conclusion",
    "conclusions",
    "discussion",
    "evaluation",
    "experiments",
    "introduction",
    "method",
    "methodology",
    "references",
    "related work",
    "results",
}


class MarkdownCleaner:
    def __init__(self) -> None:
        self.parser = MarkdownIt("commonmark", {"html": True})
        self.latex_converter = LatexNodes2Text(math_mode="text")

    def clean(self, markdown_text: str, content_list: list[dict], paper_id: str, paper_name: str) -> tuple[list[Document], list[Document]]:
        lines = markdown_text.splitlines()
        root = SyntaxTreeNode(self.parser.parse(markdown_text))
        tables = deque((order, item) for order, item in enumerate(content_list) if item.get("type") == "table")
        visuals = deque((order, item) for order, item in enumerate(content_list) if item.get("type") in {"image", "chart"})
        caption_keys = self.build_caption_keys(content_list)
        pages_by_title = self.build_section_page_ranges(content_list)

        current_titles: dict[int, str] = {}
        current_heading: dict[str, object] | None = None
        current_text_section: dict[str, object] | None = None
        section_index = -1
        heading_index = -1
        cleaned_blocks: list[tuple[str, str]] = []
        structured_docs: list[Document] = []
        text_docs: list[Document] = []

        for node in root.children:
            raw_text = self.raw_node_text(node, lines)
            plain_text = self.node_text(node).strip()

            if node.type == "heading":
                title = plain_text
                heading_index += 1
                level = self.infer_heading_level(title, current_titles, is_first=heading_index == 0)

                if level == 2 or level == 3:
                    self.append_text_document(text_docs, cleaned_blocks, paper_id, paper_name, current_text_section)
                    cleaned_blocks = []
                    section_index += 1
                    page_start, page_end = pages_by_title.get(self.normalize_title(title), (None, None))
                    current_text_section = {
                        "section_id": f"{paper_id}:section:{section_index}",
                        "section_index": section_index,
                        "section_title": title or "\u672a\u8bc6\u522b\u7ae0\u8282",
                        "parent_title": current_titles.get(level - 1),
                        "section_level": level,
                        "page_start": page_start,
                        "page_end": page_end,
                    }

                current_titles[level] = title
                for stale_level in list(current_titles):
                    if stale_level > level:
                        del current_titles[stale_level]

                current_heading = self.build_heading_context(title, level, current_titles, current_text_section)
                continue

            if self.is_html_table(node, raw_text):
                if not tables:
                    raise ValueError("table_metadata_missing")
                order, item = tables.popleft()
                structured_docs.append(self.build_table_document(item, paper_id, paper_name, order, self.structure_context(current_heading, current_text_section)))
                continue

            if self.is_visual_block(node, raw_text):
                if not visuals:
                    raise ValueError("visual_metadata_missing")
                order, item = visuals.popleft()
                structured_docs.append(self.build_visual_document(item, paper_id, paper_name, order, self.structure_context(current_heading, current_text_section)))
                continue

            if plain_text and self.normalize_title(plain_text) in caption_keys:
                continue

            if current_text_section is None or not raw_text.strip():
                continue

            block_kind = "formula" if self.is_display_formula(raw_text) else node.type
            block_text = self.normalize_paragraph(raw_text) if node.type == "paragraph" else self.normalize_latex_text(raw_text.strip())
            if self.should_merge_paragraph(cleaned_blocks, block_kind, block_text):
                previous = cleaned_blocks[-1][1].rstrip()
                separator = "" if previous.endswith("-") else " "
                previous = previous[:-1] if previous.endswith("-") else previous
                cleaned_blocks[-1] = ("paragraph", previous + separator + block_text.lstrip())
            else:
                cleaned_blocks.append((block_kind, block_text))

        self.append_text_document(text_docs, cleaned_blocks, paper_id, paper_name, current_text_section)
        if tables or visuals:
            raise ValueError("structured_element_count_mismatch")
        return text_docs, structured_docs

    def append_text_document(self, text_docs: list[Document], cleaned_blocks: list[tuple[str, str]], paper_id: str, paper_name: str, section_context: dict[str, object] | None) -> None:
        if section_context is None or not any(text.strip() for _, text in cleaned_blocks):
            return
        text_docs.append(self.build_text_document(cleaned_blocks, paper_id, paper_name, section_context))

    def build_text_document(self, cleaned_blocks: list[tuple[str, str]], paper_id: str, paper_name: str, section_context: dict[str, object]) -> Document:
        texts = "\n\n".join(text for _, text in cleaned_blocks if text.strip()).strip()
        return Document(page_content=texts, metadata={"paper_id": paper_id, "paper_name": paper_name, "content_type": "text", **section_context})

    def build_table_document(self, item: dict, paper_id: str, paper_name: str, order: int, section_context: dict[str, object]) -> Document:
        table_body = item.get("table_body")
        if not isinstance(table_body, str) or not table_body.strip():
            raise ValueError("table_body_missing")

        header_rows = self.table_header_rows(table_body)
        header = list(range(header_rows)) if header_rows > 1 else 0
        frames = pd.read_html(StringIO(table_body), header=header, flavor="lxml")
        if not frames:
            raise ValueError("table_parse_failed")
        frame = frames[0].fillna("")
        frame.columns = self.flatten_table_columns(frame.columns)
        metadata = self.structure_metadata(item, paper_id, paper_name, order, section_context)
        metadata.update({"content_type": "table", "caption": self.normalize_latex_text(self.join_caption(item.get("table_caption")))})
        return Document(page_content=self.normalize_latex_text(frame.to_markdown(index=False)), metadata=metadata)

    def build_visual_document(self, item: dict, paper_id: str, paper_name: str, order: int, section_context: dict[str, object]) -> Document:
        caption = self.normalize_latex_text(self.join_caption(item.get("chart_caption") or item.get("image_caption")))
        content_type = item.get("type") if item.get("type") in {"image", "chart"} else "image"
        metadata = self.structure_metadata(item, paper_id, paper_name, order, section_context)
        metadata.update({"content_type": content_type, "caption": caption})
        return Document(page_content=caption, metadata=metadata)

    def structure_metadata(self, item: dict, paper_id: str, paper_name: str, order: int, section_context: dict[str, object]) -> dict[str, object]:
        metadata: dict[str, object] = {"paper_id": paper_id, "paper_name": paper_name, "source_order": order, "asset_path": item.get("img_path"), **section_context}
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int) and not isinstance(page_idx, bool):
            metadata.update({"page_start": page_idx + 1, "page_end": page_idx + 1})
        return metadata

    @staticmethod
    def structure_context(current_heading: dict[str, object] | None, current_text_section: dict[str, object] | None) -> dict[str, object]:
        return dict(current_heading or current_text_section or {})

    @staticmethod
    def build_heading_context(title: str, level: int, current_titles: dict[int, str], current_text_section: dict[str, object] | None) -> dict[str, object]:
        context = dict(current_text_section or {})
        context.update({"section_title": title or "\u672a\u8bc6\u522b\u7ae0\u8282", "parent_title": current_titles.get(level - 1), "section_level": level})
        return context

    @classmethod
    def infer_heading_level(cls, title: object, current_titles: dict[int, str], *, is_first: bool) -> int:
        if is_first:
            return 1
        if not isinstance(title, str) or not title.strip():
            return 2

        value = title.strip()
        if cls.is_common_top_level_title(value):
            return 2

        alpha_numeric = re.match(r"^([A-Z])\.(\d+(?:\.\d+)*)(?:[.)])?\s+", value)
        if alpha_numeric is not None:
            return 3

        numeric = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+", value)
        if numeric is not None:
            numeric_level = len(numeric.group(1).split("."))
            if numeric_level == 1 and cls.current_level2_is_alpha_appendix(current_titles):
                return 3
            if numeric_level == 1 and cls.current_level2_is_letter_subheading(current_titles):
                return 3
            return min(numeric_level + 1, 3)

        roman = re.match(r"^([IVXLCDM]+)\.?\s+", value)
        if roman is not None and cls.is_roman_numeral(roman.group(1)):
            return 2

        letter_dot = re.match(r"^([A-Z])\.\s+", value)
        if letter_dot is not None:
            return 3 if cls.current_level2_is_roman(current_titles) else 2

        letter_space = re.match(r"^([A-Z])\s+", value)
        if letter_space is not None:
            return 3 if cls.current_level2_is_roman(current_titles) else 2

        return 2

    @classmethod
    def is_common_top_level_title(cls, title: str) -> bool:
        normalized = cls.normalize_title(title).rstrip(":")
        return normalized in COMMON_TOP_LEVEL_TITLES or normalized.startswith("appendix")

    @classmethod
    def current_level2_is_alpha_appendix(cls, current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "").strip()
        return re.match(r"^(appendix\s+)?[A-Z](?:[.:)]|\s)", title, flags=re.IGNORECASE) is not None

    @classmethod
    def current_level2_is_letter_subheading(cls, current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "").strip()
        return re.match(r"^[A-Z](?:[.:)]|\s)", title) is not None and not cls.current_level2_is_roman(current_titles)

    @classmethod
    def current_level2_is_roman(cls, current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "").strip()
        match = re.match(r"^([IVXLCDM]+)\.?\s+", title)
        return match is not None and cls.is_roman_numeral(match.group(1))

    @staticmethod
    def is_roman_numeral(value: str) -> bool:
        return ROMAN_NUMERAL_RE.fullmatch(value.upper()) is not None

    def build_section_page_ranges(self, content_list: list[dict]) -> dict[str, tuple[int | None, int | None]]:
        pages_by_title: dict[str, list[int]] = {}
        current_titles: dict[int, str] = {}
        current_section_title: str | None = None
        heading_index = -1

        for item in content_list:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            text_level = item.get("text_level")
            if isinstance(text, str) and text.strip() and isinstance(text_level, int) and not isinstance(text_level, bool):
                heading_index += 1
                level = self.infer_heading_level(text, current_titles, is_first=heading_index == 0)
                current_titles[level] = text.strip()
                for stale_level in list(current_titles):
                    if stale_level > level:
                        del current_titles[stale_level]
                if level in {2, 3}:
                    current_section_title = self.normalize_title(text)
                    pages_by_title.setdefault(current_section_title, [])

            if current_section_title is None:
                continue
            page_idx = item.get("page_idx")
            if isinstance(page_idx, int) and not isinstance(page_idx, bool):
                pages_by_title[current_section_title].append(page_idx + 1)

        return {title: (min(pages) if pages else None, max(pages) if pages else None) for title, pages in pages_by_title.items()}

    def build_caption_keys(self, content_list: list[dict]) -> set[str]:
        caption_keys: set[str] = set()
        for item in content_list:
            if not isinstance(item, dict):
                continue
            caption = self.join_caption(item.get("image_caption") or item.get("chart_caption") or item.get("table_caption"))
            if caption:
                caption_keys.add(self.normalize_title(caption))
        return caption_keys

    @staticmethod
    def join_caption(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return " ".join(part.strip() for part in value if isinstance(part, str) and part.strip())
        return ""

    @staticmethod
    def table_header_rows(table_body: str) -> int:
        try:
            table = html.fromstring(table_body)
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

    def node_text(self, node: SyntaxTreeNode) -> str:
        if node.type == "text":
            return node.content
        if node.type in {"code_block", "fence"}:
            return node.content
        return "".join(self.node_text(child) for child in node.children)

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
        converted = re.sub(r"\s*([=+·≤≥])\s*", r" \1 ", converted)
        converted = re.sub(r"_\{([^{}]+)\}", lambda match: "_{" + re.sub(r"\s*=\s*", "=", match.group(1)) + "}", converted)
        return re.sub(r"\s+", " ", converted).strip()

    def normalize_paragraph(self, text: str) -> str:
        text = self.normalize_latex_text(text)
        text = re.sub(r"(?<!\.)\.\s*,", ",", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return re.sub(r"[ \t]*\n+[ \t]*", " ", text).strip()

    @classmethod
    def should_merge_paragraph(cls, cleaned_blocks: list[tuple[str, str]], block_kind: str, block_text: str) -> bool:
        if block_kind != "paragraph" or not block_text.strip() or not cleaned_blocks:
            return False
        previous_kind, previous_text = cleaned_blocks[-1]
        return previous_kind == "paragraph" and not cls.sentence_finished(previous_text)

    @staticmethod
    def is_display_formula(text: str) -> bool:
        return DISPLAY_MATH_RE.fullmatch(text) is not None

    @staticmethod
    def is_html_table(node: SyntaxTreeNode, raw_text: str) -> bool:
        return node.type == "html_block" and raw_text.lstrip().lower().startswith("<table")

    @staticmethod
    def is_visual_block(node: SyntaxTreeNode, raw_text: str) -> bool:
        return node.type == "paragraph" and MARKDOWN_IMAGE_RE.match(raw_text) is not None

    @staticmethod
    def sentence_finished(text: str) -> bool:
        return SENTENCE_END_RE.search(text.rstrip()) is not None

    @staticmethod
    def raw_node_text(node: SyntaxTreeNode, lines: list[str]) -> str:
        if node.map is None:
            return ""
        start, end = node.map
        return "\n".join(lines[start:end])

    @staticmethod
    def normalize_title(title: str) -> str:
        return re.sub(r"\s+", " ", title.strip().lower())
