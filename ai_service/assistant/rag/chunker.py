"""Markdown chunking for ops-doc RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def _slugify_heading(text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "section"


@dataclass(frozen=True)
class DocChunk:
    """A searchable document chunk with source metadata."""

    chunk_id: str
    text: str
    source_path: str
    heading: str
    anchor: str


def _iter_sections(markdown: str) -> Iterator[tuple[str, str, int]]:
    """Yield (heading, body, level) split on markdown headings."""
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        body = markdown.strip()
        if body:
            yield ("Document", body, 1)
        return

    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        yield ("Preamble", preamble, 1)

    for idx, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if body:
            yield (heading, body, level)


def _split_paragraphs(body: str, *, max_chars: int = 1200) -> list[str]:
    """Split long section bodies by blank lines, merging small paragraphs."""
    raw_parts = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not raw_parts:
        return []

    merged: list[str] = []
    buffer = ""
    for part in raw_parts:
        candidate = f"{buffer}\n\n{part}".strip() if buffer else part
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            merged.append(buffer)
        if len(part) <= max_chars:
            buffer = part
        else:
            # Hard-split oversized paragraphs.
            for offset in range(0, len(part), max_chars):
                merged.append(part[offset : offset + max_chars])
            buffer = ""
    if buffer:
        merged.append(buffer)
    return merged


def chunk_markdown_file(path: Path, *, service_root: Path) -> list[DocChunk]:
    """Chunk a markdown file by headings and paragraphs."""
    text = path.read_text(encoding="utf-8")
    rel_source = str(path.relative_to(service_root))
    chunks: list[DocChunk] = []

    for heading, body, _level in _iter_sections(text):
        anchor = _slugify_heading(heading)
        parts = _split_paragraphs(body)
        if not parts:
            parts = [body] if body.strip() else []
        for part_index, part in enumerate(parts):
            chunk_id = f"{rel_source}#{anchor}:{part_index}"
            chunk_text = f"## {heading}\n\n{part}".strip()
            chunks.append(
                DocChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    source_path=rel_source,
                    heading=heading,
                    anchor=anchor,
                )
            )
    return chunks


def chunk_markdown_files(paths: list[Path], *, service_root: Path) -> list[DocChunk]:
    """Chunk multiple markdown files; skip missing paths with a warning in logs."""
    all_chunks: list[DocChunk] = []
    for path in paths:
        if not path.exists():
            continue
        all_chunks.extend(chunk_markdown_file(path, service_root=service_root))
    return all_chunks
