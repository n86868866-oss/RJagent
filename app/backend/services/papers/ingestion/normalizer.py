from __future__ import annotations

import json
import re
import unicodedata
from html import unescape
from typing import Any

from langchain_core.documents import Document

from app.backend.services.papers.models import PaperDocumentMetadata, TextBlock


DEFAULT_SECTION_TITLE = "未识别章节"


def extract_paper_name(result: Any) -> str | None:
    for candidate in markdown_heading_candidates(result):
        cleaned = clean_title(candidate)
        if is_valid_title(cleaned):
            return cleaned

    content = load_content_list(result)
    if content is not None:
        for candidate in title_candidates_from_content(content):
            cleaned = clean_title(candidate)
            if is_valid_title(cleaned):
                return cleaned

    for candidate in markdown_line_candidates(result):
        cleaned = clean_title(candidate)
        if is_valid_title(cleaned):
            return cleaned

    return None


def normalize_paper_name_key(paper_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", paper_name)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def build_text_blocks(result: Any) -> list[TextBlock]:
    content = load_content_list(result)
    if content is not None:
        blocks = blocks_from_content_list(content)
        if blocks:
            return blocks

    blocks = blocks_from_markdown(result)
    if blocks:
        return blocks

    return []


def extract_document_metadata(result: Any, *, paper_name: str) -> PaperDocumentMetadata:
    content = load_content_list(result)
    records = metadata_records_from_content(content) if content is not None else metadata_records_from_markdown(result)
    full_text = "\n".join(record["text"] for record in records)

    source = extract_source(records)
    citation = extract_citation(records)
    journal = extract_journal(records, citation)
    doi = extract_doi(full_text)

    return PaperDocumentMetadata(
        paper_name=paper_name,
        authors=extract_authors(records, paper_name=paper_name),
        affiliations=extract_affiliations(records, paper_name=paper_name),
        journal=journal,
        publisher=extract_publisher(full_text, source=citation or source, journal=journal, doi=doi),
        doi=doi,
        publication_year=extract_publication_year(records, source=citation or source, journal=journal),
        source=source,
        abstract=extract_abstract(records),
    )


def join_block_text(blocks: list[TextBlock]) -> str:
    return "\n\n".join(block.text for block in blocks if block.text.strip())

def build_metadata_documents(*, paper_id: str, paper_name: str, textblocks: list[TextBlock]) -> list[Document]:
    metadata_docs: list[Document] = []

    current_section_index: int | None = None
    current_section_title: str | None = None
    current_texts: list[str] = []
    current_pages: list[int] = []

    def flush_current_section():
        nonlocal current_section_index, current_section_title
        nonlocal current_texts, current_pages

        section_texts = "\n\n".join(text for text in current_texts if text.strip()).strip()
        if not section_texts:
            return

        metadata_docs.append(
            Document(
                page_content=section_texts,
                metadata={
                    "paper_id": paper_id,
                    "paper_name": paper_name,
                    "section_index": current_section_index or 0,
                    "section_title": current_section_title or "未识别章节",
                    "page_numbers": sorted(set(current_pages)),
                }
            )
        )

    for block in textblocks:
        section_index = block.metadata.get("section_index") or 0
        section_title = block.metadata.get("section_title") or "未识别章节"

        if current_section_index is None:
            current_section_index = section_index
            current_section_title = section_title

        if section_index != current_section_index or section_title != current_section_title:
            flush_current_section()
            current_section_index = section_index
            current_section_title = section_title
            current_texts = []
            current_pages = []

        current_texts.append(block.text)

        pages = block.metadata.get("page_numbers", [])
        if isinstance(pages, list):
            current_pages.extend(page for page in pages if isinstance(page, int) and not isinstance(page, bool))

    flush_current_section()
    return metadata_docs


def can_merge_by_index(content_docs: list[Document], markdown_docs: list[Document]) -> bool:
    if len(content_docs) != len(markdown_docs):
        return False

    if not content_docs:
        return False

    matched = 0
    for content_doc, markdown_doc in zip(content_docs, markdown_docs):
        content_title = normalize_title(content_doc.metadata.get("section_title"))
        markdown_title = normalize_title(markdown_doc_title(markdown_doc))

        if not content_title or not markdown_title:
            continue

        if content_title == markdown_title:
            matched += 1
        elif content_title in markdown_title or markdown_title in content_title:
            matched += 1

    return matched >= max(1, int(len(content_docs) * 0.6))


def markdown_doc_title(doc: Document) -> str | None:
    for key in ("h3", "h2", "h1"):
        value = doc.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def normalize_title(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    value = value.strip().lstrip("#").strip().lower()
    return re.sub(r"\s+", " ", value)


def load_content_list(result: Any) -> Any | None:
    item = select_legacy_content_list(result.files)
    if item is not None:
        try:
            return json.loads(item[1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    if isinstance(result.payload, dict):
        for key in ("content_list", "content", "data"):
            value = result.payload.get(key)
            if isinstance(value, (list, dict)):
                return value
    return None


def select_legacy_content_list(files: dict[str, bytes]) -> tuple[str, bytes] | None:
    for name, payload in files.items():
        normalized = name.replace("\\", "/").split("/")[-1].lower()
        if normalized == "content_list.json" or normalized.endswith("_content_list.json"):
            return name, payload
    return None


def markdown_heading_candidates(result: Any) -> list[str]:
    markdown = read_markdown(result)
    if not markdown:
        return []

    candidates: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidates.append(stripped.lstrip("#").strip())
    return candidates


def markdown_line_candidates(result: Any) -> list[str]:
    markdown = read_markdown(result)
    if not markdown:
        return []

    candidates: list[str] = []
    for line in markdown.splitlines():
        stripped = clean_title(line)
        if stripped:
            candidates.append(stripped)
        if len(candidates) >= 20:
            break
    return candidates


def title_candidates_from_content(content: Any) -> list[str]:
    candidates: list[str] = []
    for item in walk_dicts(content):
        text = text_from_item(item)
        if not text:
            continue
        block_type = block_type_from_item(item)
        if "title" in block_type or item.get("text_level") is not None:
            candidates.append(text)
    return candidates


def blocks_from_content_list(content: Any) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    section_title = DEFAULT_SECTION_TITLE
    section_index = 0
    order = 0

    for item in walk_dicts(content):
        text = normalize_text(text_from_item(item))
        if not text:
            continue

        block_type = block_type_from_item(item)
        if "title" in block_type or item.get("text_level") is not None:
            section_title = text
            section_index += 1

        page = page_number_from_item(item)
        blocks.append(
            TextBlock(
                text=text,
                metadata={
                    "page_numbers": [page] if page is not None else [],
                    "section_title": section_title,
                    "section_index": section_index,
                    "block_type": block_type or "text",
                    "order": order,
                },
            )
        )
        order += 1

    return blocks


def metadata_records_from_content(content: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for order, item in enumerate(walk_dicts(content)):
        text = clean_metadata_text(text_from_item(item))
        if not text:
            continue
        records.append(
            {
                "text": text,
                "page": page_number_from_item(item),
                "type": block_type_from_item(item),
                "text_level": item.get("text_level"),
                "order": order,
            }
        )
    return records


def metadata_records_from_markdown(result: Any) -> list[dict[str, Any]]:
    markdown = read_markdown(result)
    if not markdown:
        return []

    records: list[dict[str, Any]] = []
    for order, line in enumerate(markdown.splitlines()):
        text = clean_metadata_text(line)
        if not text:
            continue
        records.append(
            {
                "text": clean_title(text) if text.startswith("#") else text,
                "page": None,
                "type": "markdown",
                "text_level": 1 if text.startswith("#") else None,
                "order": order,
            }
        )
    return records


def extract_authors(records: list[dict[str, Any]], *, paper_name: str) -> list[str]:
    title_index = first_title_index(records, paper_name)
    candidates = records[title_index + 1 : title_index + 8] if title_index is not None else records[:8]
    lines: list[str] = []
    authors: list[str] = []
    for record in candidates:
        text = record["text"]
        lowered = text.lower()
        if lowered.startswith("abstract") or is_metadata_heading(text):
            break
        if looks_like_affiliation(text):
            author = author_from_affiliation_line(text)
            if author:
                authors.append(author)
            continue
        if strong_source_signal(text):
            break
        lines.append(text)

    authors.extend(split_authors(" ".join(lines)))
    citation = extract_citation(records)
    if citation:
        authors.extend(authors_from_citation(citation, paper_name=paper_name))
    return dedupe_strings(authors)


def extract_affiliations(records: list[dict[str, Any]], *, paper_name: str) -> list[str]:
    title_index = first_title_index(records, paper_name)
    candidates = records[title_index + 1 : title_index + 16] if title_index is not None else records[:16]
    affiliations: list[str] = []

    for record in candidates:
        text = record["text"]
        lowered = text.lower()
        if lowered.startswith("abstract") or is_metadata_heading(text) or strong_source_signal(text):
            break
        if looks_like_affiliation(text):
            affiliations.append(clean_affiliation(text))

    for record in records[:80]:
        text = record["text"]
        lowered = text.lower()
        if str(record.get("type") or "") != "page_footnote":
            continue
        if "corresponding" in lowered or "equal contribution" in lowered:
            continue
        if looks_like_affiliation(text):
            affiliations.append(clean_affiliation(text))

    return dedupe_strings(value for value in affiliations if value)


def extract_abstract(records: list[dict[str, Any]]) -> str | None:
    for index, record in enumerate(records):
        text = record["text"]
        lowered = text.lower()
        if not (lowered == "abstract" or lowered.startswith("abstract:")):
            continue

        parts: list[str] = []
        remainder = re.sub(r"^abstract\s*[-—:]*", "", text, flags=re.IGNORECASE).strip()
        if remainder:
            parts.append(remainder)

        for next_record in records[index + 1 :]:
            next_text = next_record["text"]
            if is_stop_heading(next_record, next_text):
                break
            parts.append(next_text)
            if len(" ".join(parts)) >= 3000:
                break

        abstract = normalize_text(" ".join(parts))
        return abstract or None
    return None


def extract_doi(text: str) -> str | None:
    match = re.search(r"\b10\.\d{4,9}/[^\s<>{}\"']+", text, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(0).rstrip(".,;:)]}")


def extract_publication_year(records: list[dict[str, Any]], *, source: str | None, journal: str | None) -> int | None:
    for text in [source, journal]:
        year = first_year(text or "")
        if year is not None:
            return year

    priority_lines = [record["text"] for record in records[:80] if contains_source_signal(record["text"])]
    for text in priority_lines:
        year = first_year(text)
        if year is not None:
            return year

    for record in records[:40]:
        year = first_year(record["text"])
        if year is not None:
            return year
    return None


def extract_source(records: list[dict[str, Any]]) -> str | None:
    return "upload"


def extract_citation(records: list[dict[str, Any]]) -> str | None:
    for index, record in enumerate(records[:100]):
        text = record["text"]
        arxiv = re.search(r"arXiv:\s*[\w.:-]+(?:\s*\[[^\]]+\])?", text, flags=re.IGNORECASE)
        if arxiv is not None:
            return arxiv.group(0)
        if re.search(r"Published as .*? at\s+.+", text, flags=re.IGNORECASE):
            return text[:500]
        if text.lower().strip(" :") == "acm reference format" and index + 1 < len(records):
            return records[index + 1]["text"][:500]
        if is_source_record(record) and strong_source_signal(text):
            return text[:500]
    return None


def extract_journal(records: list[dict[str, Any]], source: str | None) -> str | None:
    texts = [source or "", *(record["text"] for record in records[:100])]
    for text in texts:
        ieee = re.search(r"\b(IEEE TRANSACTIONS ON .+?)(?:,|\bVOL\b)", text, flags=re.IGNORECASE)
        if ieee is not None:
            return clean_source_name(ieee.group(1)).title()

        match = re.search(r"Published as .*? at\s+(.+)", text, flags=re.IGNORECASE)
        if match is not None:
            return clean_source_name(match.group(1))

        match = re.search(r"\b([A-Z][A-Za-z]*\s*[’']?\d{2})\b", text)
        if match is not None and any(keyword in text.lower() for keyword in ("conference", "proceedings", "usa", "doi", "isbn")):
            return clean_source_name(match.group(1))

        if "arxiv:" in text.lower():
            return "arXiv"
    return None


def extract_publisher(text: str, *, source: str | None, journal: str | None, doi: str | None) -> str | None:
    combined = "\n".join(value for value in (source or "", journal or "", doi or "") if value)
    lowered = combined.lower()
    if "10.1145" in lowered or "acm isbn" in lowered or "association for computing machinery" in lowered:
        return "ACM"
    if "10.1109" in lowered or re.search(r"\bieee\b", combined):
        return "IEEE"
    if "springer" in lowered:
        return "Springer"
    if "elsevier" in lowered:
        return "Elsevier"
    if "arxiv:" in lowered:
        return "arXiv"
    return None


def first_title_index(records: list[dict[str, Any]], paper_name: str) -> int | None:
    target = normalize_paper_name_key(paper_name)
    for index, record in enumerate(records[:30]):
        if normalize_paper_name_key(record["text"]) == target:
            return index
    return 0 if records else None


def split_authors(text: str) -> list[str]:
    cleaned = re.sub(r"[\*†‡§¶∗]+", "", text)
    cleaned = re.sub(r"\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\band\b", ",", cleaned, flags=re.IGNORECASE)
    parts = re.split(r",|;|、", cleaned)

    authors: list[str] = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" .")
        if not is_author_name(name):
            continue
        authors.append(name)
    return authors


def authors_from_citation(citation: str, *, paper_name: str) -> list[str]:
    prefix = citation
    year_match = re.search(r"\.\s+(19\d{2}|20\d{2})\.", citation)
    if year_match is not None:
        prefix = citation[: year_match.start()]
    else:
        title_index = citation.lower().find(paper_name.lower())
        if title_index > 0:
            prefix = citation[:title_index]
    return split_authors(prefix)


def author_from_affiliation_line(text: str) -> str | None:
    lowered = text.lower()
    markers = (
        " university",
        " school",
        " laboratory",
        " department",
        " institute",
        " college",
        " lab",
    )
    indexes = [lowered.find(marker) for marker in markers if lowered.find(marker) > 0]
    if not indexes:
        return None
    name = text[: min(indexes)].strip(" ,.;")
    return name if is_author_name(name) else None


def is_author_name(value: str) -> bool:
    if not 2 <= len(value) <= 80:
        return False
    lowered = value.lower()
    descriptors = {
        "ieee",
        "fellow",
        "life fellow",
        "member",
        "student member",
        "graduate student member",
        "senior member",
    }
    if lowered in descriptors:
        return False
    blocked = (
        "university",
        "school",
        "laboratory",
        "department",
        "institute",
        "college",
        "email",
        "abstract",
        "keywords",
        "published",
        "conference",
        "copyright",
        "license",
        "doi",
        "isbn",
        "http",
        "@",
    )
    if any(token in lowered for token in blocked):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", value))


def looks_like_affiliation(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "university",
            "school",
            "laboratory",
            "department",
            "institute",
            "college",
            "lab",
            "china",
            "usa",
            "email",
            "@",
        )
    )


def is_metadata_heading(text: str) -> bool:
    lowered = text.lower().strip(" :")
    return lowered in {"abstract", "keywords", "index terms", "references", "contents", "table of contents"}


def is_stop_heading(record: dict[str, Any], text: str) -> bool:
    lowered = text.lower().strip(" :")
    if lowered in {"keywords", "index terms", "acm reference format", "ccs concepts"}:
        return True
    if re.match(r"^\d+\.?\s+[A-Za-z]", text):
        return True
    return record.get("text_level") is not None and lowered != "abstract"


def contains_source_signal(text: str) -> bool:
    return strong_source_signal(text)


def strong_source_signal(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "published as",
            "ieee transactions",
            "acm reference format",
            "design automation conference",
            "proceedings",
            "arxiv:",
            "doi.org",
            "digital object identifier",
            "copyright",
            "isbn",
        )
    )


def is_source_record(record: dict[str, Any]) -> bool:
    block_type = str(record.get("type") or "")
    if block_type in {"header", "footer", "page_footnote", "aside_text"}:
        return True
    page = record.get("page")
    order = record.get("order")
    return page == 1 and isinstance(order, int) and order <= 25


def first_year(text: str) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if match is None:
        return None
    return int(match.group(1))


def clean_source_name(value: str) -> str:
    value = re.split(r"[.;]", value, maxsplit=1)[0]
    return normalize_text(value).strip()


def clean_affiliation(value: str) -> str:
    value = re.sub(r"^[\d\s.,;:-]+", "", value)
    value = re.sub(r"\([^)]*e-mail:[^)]+\)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\([^)]*@[^)]*\)", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .;")


def dedupe_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_paper_name_key(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def blocks_from_markdown(result: Any) -> list[TextBlock]:
    markdown = read_markdown(result)
    if not markdown:
        return []

    blocks: list[TextBlock] = []
    section_title = DEFAULT_SECTION_TITLE
    section_index = 0
    order = 0
    for paragraph in re.split(r"\n\s*\n", markdown):
        text = normalize_text(paragraph)
        if not text:
            continue
        if text.startswith("#"):
            section_title = clean_title(text)
            section_index += 1
        blocks.append(
            TextBlock(
                text=clean_title(text) if text.startswith("#") else text,
                metadata={
                    "page_numbers": [],
                    "section_title": section_title,
                    "section_index": section_index,
                    "block_type": "markdown",
                    "order": order,
                },
            )
        )
        order += 1
    return blocks


def read_markdown(result: Any) -> str | None:
    item = select_file(result.files, suffix=".md")
    if item is None:
        return None
    try:
        return item[1].decode("utf-8")
    except UnicodeDecodeError:
        return None


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


def walk_dicts(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        items.append(value)
        for child in value.values():
            items.extend(walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(walk_dicts(child))
    return items


def text_from_item(item: dict[str, Any]) -> str:
    for key in ("text", "content", "title"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def block_type_from_item(item: dict[str, Any]) -> str:
    for key in ("type", "block_type", "category"):
        value = item.get(key)
        if isinstance(value, str):
            return value.lower()
    return ""


def page_number_from_item(item: dict[str, Any]) -> int | None:
    for key in ("page_idx", "page_id"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value + 1
    value = item.get("page")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def clean_title(value: str) -> str:
    value = value.strip().strip("#").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def clean_metadata_text(value: str) -> str:
    value = re.sub(r"<sup>.*?</sup>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = unescape(value)
    return normalize_text(value)


def normalize_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value


def is_valid_title(value: str) -> bool:
    if not 4 <= len(value) <= 300:
        return False
    lowered = value.lower()
    invalid = {"abstract", "keywords", "references", "contents", "table of contents"}
    return lowered not in invalid
