from __future__ import annotations

from dataclasses import dataclass
import re

from langchain_core.documents import Document

from app.backend.services.papers.ingestion.content_cleaner import ContentCleaner


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
AUXILIARY_TYPES = {"header", "footer", "page_number", "aside_text"}
TEXT_TYPES = {"text", "equation", "code", "list"}
VISUAL_TYPES = {"image", "chart"}
FIGURE_CAPTION_RE = re.compile(r"(?:\bfig(?:ure)?\.?\s*\d+|图\s*\d+)", re.IGNORECASE)


@dataclass(slots=True)
class _TextPiece:
    text: str
    page_number: int | None
    block_kind: str
    separator_before: str = "\n\n"


class MinerUDocumentBuilder:
    def __init__(self, cleaner: ContentCleaner | None = None) -> None:
        self.cleaner = cleaner or ContentCleaner()

    def build(self, content_list: list[dict], paper_id: str, paper_name: str) -> tuple[list[Document], list[Document]]:
        current_titles: dict[int, str] = {}
        current_heading: dict[str, object] | None = None
        current_text_section: dict[str, object] | None = None
        section_index = -1
        heading_index = -1
        text_pieces: list[_TextPiece] = []
        text_docs: list[Document] = []
        structured_docs: list[Document] = []

        for item_index, item in enumerate(content_list):
            if not isinstance(item, dict):
                continue

            content_type = str(item.get("type") or "")
            page_number = self.page_number(item)

            if self.is_heading(item):
                title = self.cleaner.clean_item_text(item)
                if not title:
                    continue
                heading_index += 1
                level = self.infer_heading_level(title, current_titles, is_first=heading_index == 0)

                if level in {2, 3}:
                    if current_text_section is not None and text_pieces:
                        previous_context = self.structure_context(current_heading, current_text_section)
                        text_docs.append(self.build_text_document(text_pieces, paper_id, paper_name, previous_context))
                    text_pieces = []
                    section_index += 1
                    current_text_section = {
                        "section_id": f"{paper_id}:section:{section_index}",
                        "section_index": section_index,
                        "section_title": title,
                        "parent_title": current_titles.get(level - 1),
                        "section_level": level,
                    }

                current_titles[level] = title
                for stale_level in list(current_titles):
                    if stale_level > level:
                        del current_titles[stale_level]
                current_heading = self.build_heading_context(title, level, current_titles, current_text_section)
                continue

            section_context = self.structure_context(current_heading, current_text_section)

            if content_type == "page_footnote":
                footnote = self.build_footnote_document(item, paper_id, paper_name, page_number, section_context)
                if footnote is not None:
                    structured_docs.append(footnote)
                continue

            if content_type == "table":
                structured_docs.append(self.build_table_document(item, paper_id, paper_name, page_number, section_context))
                continue

            if content_type in VISUAL_TYPES:
                group_caption = self.find_visual_group_caption(content_list, item_index)
                visual = self.build_visual_document(item, paper_id, paper_name, page_number, section_context, group_caption)
                if visual is not None:
                    structured_docs.append(visual)
                continue

            if content_type in AUXILIARY_TYPES:
                continue

            if content_type not in TEXT_TYPES or current_text_section is None:
                continue

            text = self.cleaner.clean_item_text(item)
            if not text:
                continue
            block_kind = "paragraph" if content_type == "text" else content_type
            self.append_text_piece(text_pieces, text=text, page_number=page_number, block_kind=block_kind)

        if current_text_section is not None and text_pieces:
            final_context = self.structure_context(current_heading, current_text_section)
            text_docs.append(self.build_text_document(text_pieces, paper_id, paper_name, final_context))
        return text_docs, structured_docs

    def append_text_piece(self, pieces: list[_TextPiece], *, text: str, page_number: int | None, block_kind: str) -> None:
        separator = "\n\n"
        if pieces and block_kind == "paragraph" and pieces[-1].block_kind == "paragraph" and not self.cleaner.sentence_finished(pieces[-1].text):
            if pieces[-1].text.endswith("-"):
                pieces[-1].text = pieces[-1].text[:-1]
                separator = ""
            else:
                separator = " "
        pieces.append(_TextPiece(text=text, page_number=page_number, block_kind=block_kind, separator_before=separator))

    @staticmethod
    def build_text_document(pieces: list[_TextPiece], paper_id: str, paper_name: str, section_context: dict[str, object]) -> Document:
        parts: list[str] = []
        page_segments: list[dict[str, int]] = []
        cursor = 0

        for index, piece in enumerate(pieces):
            separator = piece.separator_before if index else ""
            parts.append(separator)
            cursor += len(separator)
            start = cursor
            parts.append(piece.text)
            cursor += len(piece.text)
            if piece.page_number is not None:
                page_segments.append({"start": start, "end": cursor, "page_number": piece.page_number})

        page_numbers = sorted({segment["page_number"] for segment in page_segments})
        metadata: dict[str, object] = {
            "paper_id": paper_id,
            "paper_name": paper_name,
            "content_type": "text",
            "page_numbers": page_numbers,
            "_page_segments": page_segments,
            **section_context,
        }
        return Document(page_content="".join(parts).strip(), metadata=metadata)

    def build_table_document(self, item: dict, paper_id: str, paper_name: str, page_number: int | None, section_context: dict[str, object]) -> Document:
        metadata = self.structure_metadata(item, paper_id, paper_name, page_number, section_context)
        metadata.update({
            "content_type": "table",
            "caption": self.cleaner.normalize_paragraph(self.cleaner.join_text(item.get("table_caption"))),
            "_table_footnote": self.cleaner.normalize_paragraph(self.cleaner.join_text(item.get("table_footnote"))),
        })
        return Document(page_content=self.cleaner.table_to_markdown(item), metadata=metadata)

    def build_visual_document(self, item: dict, paper_id: str, paper_name: str, page_number: int | None, section_context: dict[str, object], group_caption: str) -> Document | None:
        own_caption = self.cleaner.visual_caption(item)
        captions = list(dict.fromkeys(value for value in (own_caption, group_caption) if value))
        caption = "\n\n".join(captions)
        text = self.cleaner.visual_text(item, caption=caption)
        if not text:
            return None
        content_type = str(item.get("type")) if item.get("type") in {"image", "chart"} else "image"
        metadata = self.structure_metadata(item, paper_id, paper_name, page_number, section_context)
        metadata.update({"content_type": content_type, "caption": caption, "image_path": self.image_path(item)})
        return Document(page_content=text, metadata=metadata)

    def find_visual_group_caption(self, content_list: list[dict], item_index: int) -> str:
        item = content_list[item_index]
        page_idx = item.get("page_idx")
        fallback = ""

        for index in range(item_index, len(content_list)):
            candidate = content_list[index]
            if not isinstance(candidate, dict) or candidate.get("type") not in VISUAL_TYPES or candidate.get("page_idx") != page_idx:
                break
            caption = self.cleaner.visual_caption(candidate)
            if caption and not fallback:
                fallback = caption
            if FIGURE_CAPTION_RE.search(caption):
                return caption

        for index in range(item_index - 1, -1, -1):
            candidate = content_list[index]
            if not isinstance(candidate, dict) or candidate.get("type") not in VISUAL_TYPES or candidate.get("page_idx") != page_idx:
                break
            caption = self.cleaner.visual_caption(candidate)
            if caption and not fallback:
                fallback = caption
            if FIGURE_CAPTION_RE.search(caption):
                return caption

        return fallback

    def build_footnote_document(self, item: dict, paper_id: str, paper_name: str, page_number: int | None, section_context: dict[str, object]) -> Document | None:
        text = self.cleaner.clean_item_text(item)
        if not text:
            return None
        metadata = self.structure_metadata(item, paper_id, paper_name, page_number, section_context)
        metadata.update({"content_type": "footnote"})
        return Document(page_content=text, metadata=metadata)

    @staticmethod
    def structure_metadata(item: dict, paper_id: str, paper_name: str, page_number: int | None, section_context: dict[str, object]) -> dict[str, object]:
        page_numbers = [page_number] if page_number is not None else []
        return {
            "paper_id": paper_id,
            "paper_name": paper_name,
            "page_numbers": page_numbers,
            **section_context,
        }

    @staticmethod
    def structure_context(current_heading: dict[str, object] | None, current_text_section: dict[str, object] | None) -> dict[str, object]:
        return dict(current_heading or current_text_section or {})

    @staticmethod
    def build_heading_context(title: str, level: int, current_titles: dict[int, str], current_text_section: dict[str, object] | None) -> dict[str, object]:
        context = dict(current_text_section or {})
        context.update({"section_title": title or "未识别章节", "parent_title": current_titles.get(level - 1), "section_level": level})
        return context

    @staticmethod
    def is_heading(item: dict) -> bool:
        text_level = item.get("text_level")
        return isinstance(text_level, int) and not isinstance(text_level, bool) and text_level > 0

    @staticmethod
    def page_number(item: dict) -> int | None:
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int) and not isinstance(page_idx, bool):
            return page_idx + 1
        return None

    @staticmethod
    def image_path(item: dict) -> str | None:
        value = item.get("img_path")
        if not isinstance(value, str) or not value.strip():
            return None
        parts = [part for part in value.replace("\\", "/").split("/") if part]
        if "images" not in parts or any(part in {".", ".."} for part in parts):
            return None
        image_index = len(parts) - 1 - parts[::-1].index("images")
        return "/".join(parts[image_index:])

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

    @staticmethod
    def normalize_title(title: str) -> str:
        return re.sub(r"\s+", " ", title.strip().lower())
