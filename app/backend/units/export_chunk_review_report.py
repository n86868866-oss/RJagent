from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports"


@dataclass(frozen=True, slots=True)
class PaperRow:
    paper_id: str
    paper_name: str
    filename: str
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ChunkRow:
    chunk_id: str
    paper_id: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    section_title: str | None
    section_index: int | None
    text: str

    @property
    def text_length(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class ChunkStats:
    chunk_count: int
    min_len: int
    max_len: int
    avg_len: float
    empty_count: int
    short_count: int
    long_count: int
    heading_only_count: int
    section_missing_count: int
    page_missing_count: int
    duplicate_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a human-readable paper chunk review report from SQLite."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path. Default: data/app.db")
    parser.add_argument("--out", type=Path, default=None, help="Report output path. Default: data/reports/chunk_review_<time>.md")
    parser.add_argument("--paper-id", default=None, help="Only export one paper by paper_id.")
    parser.add_argument("--paper-name", default=None, help="Only export papers whose name contains this text.")
    parser.add_argument("--sample-size", type=int, default=3, help="Sample count for each sample group.")
    parser.add_argument("--short-chars", type=int, default=120, help="Chunks shorter than this are marked as short.")
    parser.add_argument("--long-chars", type=int, default=1800, help="Chunks longer than this are marked as long.")
    parser.add_argument("--preview-chars", type=int, default=220, help="Characters kept at chunk start and end in previews.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite数据库不存在: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def fetch_papers(connection: sqlite3.Connection, *, paper_id: str | None, paper_name: str | None) -> list[PaperRow]:
    clauses: list[str] = []
    params: list[str] = []
    if paper_id:
        clauses.append("paper_id = ?")
        params.append(paper_id)
    if paper_name:
        clauses.append("paper_name LIKE ?")
        params.append(f"%{paper_name}%")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT paper_id, paper_name, filename, status, created_at
        FROM papers
        {where_sql}
        ORDER BY created_at DESC
        """,
        params,
    ).fetchall()
    return [
        PaperRow(
            paper_id=row["paper_id"],
            paper_name=row["paper_name"],
            filename=row["filename"],
            status=row["status"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def fetch_chunks(connection: sqlite3.Connection, paper_id: str) -> list[ChunkRow]:
    rows = connection.execute(
        """
        SELECT chunk_id, paper_id, chunk_index, page_start, page_end, section_title, section_index, text
        FROM paper_chunks
        WHERE paper_id = ?
        ORDER BY chunk_index
        """,
        (paper_id,),
    ).fetchall()
    return [
        ChunkRow(
            chunk_id=row["chunk_id"],
            paper_id=row["paper_id"],
            chunk_index=row["chunk_index"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            section_title=row["section_title"],
            section_index=row["section_index"],
            text=row["text"] or "",
        )
        for row in rows
    ]


def calculate_stats(chunks: list[ChunkRow], *, short_chars: int, long_chars: int) -> ChunkStats:
    lengths = [chunk.text_length for chunk in chunks]
    text_counts = Counter(normalize_text(chunk.text) for chunk in chunks if normalize_text(chunk.text))
    duplicate_count = sum(count - 1 for count in text_counts.values() if count > 1)

    if not lengths:
        return ChunkStats(
            chunk_count=0,
            min_len=0,
            max_len=0,
            avg_len=0,
            empty_count=0,
            short_count=0,
            long_count=0,
            heading_only_count=0,
            section_missing_count=0,
            page_missing_count=0,
            duplicate_count=0,
        )

    return ChunkStats(
        chunk_count=len(chunks),
        min_len=min(lengths),
        max_len=max(lengths),
        avg_len=sum(lengths) / len(lengths),
        empty_count=sum(1 for chunk in chunks if not chunk.text.strip()),
        short_count=sum(1 for length in lengths if 0 < length < short_chars),
        long_count=sum(1 for length in lengths if length > long_chars),
        heading_only_count=sum(1 for chunk in chunks if is_heading_only(chunk.text)),
        section_missing_count=sum(1 for chunk in chunks if not (chunk.section_title or "").strip()),
        page_missing_count=sum(1 for chunk in chunks if chunk.page_start is None and chunk.page_end is None),
        duplicate_count=duplicate_count,
    )


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def is_heading_only(value: str) -> bool:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return bool(lines) and len(lines) <= 3 and all(line.startswith("#") for line in lines)


def preview_chunk(chunk: ChunkRow, *, preview_chars: int) -> str:
    text = normalize_text(chunk.text)
    if len(text) <= preview_chars * 2:
        return text
    start = text[:preview_chars].rstrip()
    end = text[-preview_chars:].lstrip()
    return f"{start}\n\n...\n\n{end}"


def select_samples(chunks: list[ChunkRow], sample_size: int) -> list[tuple[str, ChunkRow]]:
    if not chunks:
        return []

    sample_size = max(1, sample_size)
    selected: list[tuple[str, ChunkRow]] = []
    seen: set[str] = set()

    groups = [
        ("开头样本", chunks[:sample_size]),
        ("中间样本", middle_items(chunks, sample_size)),
        ("结尾样本", chunks[-sample_size:]),
        ("最短样本", sorted(chunks, key=lambda chunk: chunk.text_length)[:sample_size]),
        ("最长样本", sorted(chunks, key=lambda chunk: chunk.text_length, reverse=True)[:sample_size]),
    ]

    for group_name, group_chunks in groups:
        for chunk in group_chunks:
            key = f"{group_name}:{chunk.chunk_id}"
            if key in seen:
                continue
            seen.add(key)
            selected.append((group_name, chunk))

    return selected


def middle_items(items: list[ChunkRow], count: int) -> list[ChunkRow]:
    if len(items) <= count:
        return items
    start = max(0, (len(items) - count) // 2)
    return items[start : start + count]


def section_summary(chunks: list[ChunkRow], limit: int = 20) -> list[tuple[str, int]]:
    counter = Counter((chunk.section_title or "未识别章节").strip() or "未识别章节" for chunk in chunks)
    return counter.most_common(limit)


def render_report(
    *,
    db_path: Path,
    papers: list[PaperRow],
    chunks_by_paper: dict[str, list[ChunkRow]],
    short_chars: int,
    long_chars: int,
    sample_size: int,
    preview_chars: int,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        "# 论文分块审查报告",
        "",
        f"- 生成时间: {now}",
        f"- SQLite: `{db_path}`",
        f"- 论文数量: {len(papers)}",
        f"- 短块阈值: {short_chars} 字符",
        f"- 长块阈值: {long_chars} 字符",
        "",
    ]

    if not papers:
        lines.extend(["没有找到论文记录。", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "## 总览",
            "",
            "| 论文 | 状态 | 块数 | 最短 | 最长 | 平均 | 空块 | 短块 | 长块 | 纯标题块 | 缺章节 | 缺页码 | 重复 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    stats_by_paper: dict[str, ChunkStats] = {}
    for paper in papers:
        chunks = chunks_by_paper[paper.paper_id]
        stats = calculate_stats(chunks, short_chars=short_chars, long_chars=long_chars)
        stats_by_paper[paper.paper_id] = stats
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_cell(paper.paper_name),
                    escape_cell(paper.status),
                    str(stats.chunk_count),
                    str(stats.min_len),
                    str(stats.max_len),
                    f"{stats.avg_len:.1f}",
                    str(stats.empty_count),
                    str(stats.short_count),
                    str(stats.long_count),
                    str(stats.heading_only_count),
                    str(stats.section_missing_count),
                    str(stats.page_missing_count),
                    str(stats.duplicate_count),
                ]
            )
            + " |"
        )

    for paper in papers:
        chunks = chunks_by_paper[paper.paper_id]
        stats = stats_by_paper[paper.paper_id]
        lines.extend(
            [
                "",
                f"## {paper.paper_name}",
                "",
                f"- paper_id: `{paper.paper_id}`",
                f"- 文件名: `{paper.filename}`",
                f"- 状态: `{paper.status}`",
                f"- 创建时间: `{paper.created_at}`",
                f"- 块数: {stats.chunk_count}",
                f"- 长度: min={stats.min_len}, max={stats.max_len}, avg={stats.avg_len:.1f}",
                f"- 风险计数: empty={stats.empty_count}, short={stats.short_count}, long={stats.long_count}, heading_only={stats.heading_only_count}, section_missing={stats.section_missing_count}, page_missing={stats.page_missing_count}, duplicate={stats.duplicate_count}",
                "",
                "### 章节分布",
                "",
                "| 章节 | 块数 |",
                "| --- | ---: |",
            ]
        )
        for section_title, count in section_summary(chunks):
            lines.append(f"| {escape_cell(section_title)} | {count} |")

        lines.extend(["", "### 抽样块", ""])
        for group_name, chunk in select_samples(chunks, sample_size):
            page_range = format_page_range(chunk)
            lines.extend(
                [
                    f"#### {group_name} - chunk_index {chunk.chunk_index}",
                    "",
                    f"- chunk_id: `{chunk.chunk_id}`",
                    f"- section_index: {chunk.section_index}",
                    f"- section_title: {chunk.section_title or '未识别章节'}",
                    f"- page: {page_range}",
                    f"- length: {chunk.text_length}",
                    "",
                    "```text",
                    preview_chunk(chunk, preview_chars=preview_chars),
                    "```",
                    "",
                ]
            )

    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def format_page_range(chunk: ChunkRow) -> str:
    if chunk.page_start is None and chunk.page_end is None:
        return "-"
    if chunk.page_start == chunk.page_end:
        return str(chunk.page_start)
    return f"{chunk.page_start}-{chunk.page_end}"


def main() -> None:
    args = parse_args()
    db_path = resolve_path(args.db)
    output_path = resolve_path(args.out) if args.out else default_output_path()

    with connect_readonly(db_path) as connection:
        for table_name in ("papers", "paper_chunks"):
            if not table_exists(connection, table_name):
                raise RuntimeError(f"SQLite缺少数据表: {table_name}")

        papers = fetch_papers(connection, paper_id=args.paper_id, paper_name=args.paper_name)
        chunks_by_paper = {paper.paper_id: fetch_chunks(connection, paper.paper_id) for paper in papers}

    report = render_report(
        db_path=db_path,
        papers=papers,
        chunks_by_paper=chunks_by_paper,
        short_chars=args.short_chars,
        long_chars=args.long_chars,
        sample_size=args.sample_size,
        preview_chars=args.preview_chars,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"分块审查报告已导出: {output_path}")


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_REPORT_DIR / f"chunk_review_{timestamp}.md"


if __name__ == "__main__":
    main()
