"""A deliberately small Markdown subset: ATX headings, paragraphs, and fences."""

import hashlib
from pathlib import Path
import re

from app.kb.schemas import Chunk

CHUNKER_VERSION = "headings-v1-1500-2000-overlap200"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _pieces(text: str, target: int = 1500, maximum: int = 2000) -> list[str]:
    """Prefer paragraph boundaries; overlap only within oversized sections.

    Long blocks (including oversized lists/fences) fall back to a whitespace
    boundary. They may span chunks; short procedures and fences stay intact.
    """
    pieces = []
    remaining = text.strip()
    while len(remaining) > maximum:
        boundary = remaining.rfind("\n\n", 0, target + 1)
        if boundary < target // 2:
            boundary = remaining.rfind(" ", 0, target + 1)
        if boundary < target // 2:
            boundary = target
        pieces.append(remaining[:boundary].strip())
        # Start overlap at a word boundary, ensuring forward progress.
        start = remaining.find(" ", max(1, boundary - 200), boundary)
        start = start + 1 if start >= 0 else boundary
        remaining = remaining[start:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_document(path: Path, root: Path) -> list[Chunk]:
    relative = path.relative_to(root).as_posix()
    document_id = relative.removesuffix(".md")
    text = path.read_text(encoding="utf-8-sig")
    title = ""
    headings: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    body: list[str] = []
    fence = ""
    fence_size = 0
    seen_sections: set[str] = set()

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append((" / ".join(name for _, name in headings) or "Overview", content))
        body.clear()

    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            marks, suffix = marker.groups()
            if not fence:
                fence, fence_size = marks[0], len(marks)
            elif marks[0] == fence and len(marks) >= fence_size and not suffix.strip():
                fence = ""
            body.append(line)
            continue
        heading = None if fence else re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level, name = len(heading[1]), heading[2].strip()
            if level == 1:
                if title or any(part.strip() for part in body):
                    raise ValueError(f"{relative}: require one leading H1 title.")
                title = name
            else:
                if not title:
                    raise ValueError(f"{relative}: missing H1 title.")
                flush()
                headings = [(depth, value) for depth, value in headings if depth < level]
                headings.append((level, name))
            continue
        body.append(line)
    flush()
    if not title or not sections or fence:
        raise ValueError(f"{relative}: require a title, nonempty content, and closed fences.")

    chunks = []
    for section_path, content in sections:
        section_id = f"{document_id}#{_slug(section_path)}"
        if section_id in seen_sections:
            raise ValueError(f"{relative}: duplicate section ID {section_id}.")
        seen_sections.add(section_id)
        for piece in _pieces(content):
            digest = hashlib.sha256(f"{title}\n{section_path}\n{piece}".encode()).hexdigest()
            index = len(chunks)
            chunk_id = hashlib.sha256(
                f"{CHUNKER_VERSION}:{section_id}:{index}:{digest}".encode()
            ).hexdigest()
            chunks.append(Chunk(
                chunk_id=chunk_id, document_id=document_id, source_path=relative,
                title=title, section_id=section_id, section_path=section_path,
                chunk_index=index, content=piece, content_hash=digest,
            ))
    return chunks


def load_chunks(root: Path) -> list[Chunk]:
    if not root.is_dir():
        raise ValueError(f"Knowledge-base directory does not exist: {root}")
    chunks = [chunk for path in sorted(root.rglob("*.md")) for chunk in chunk_document(path, root)]
    if not chunks:
        raise ValueError("Knowledge base is empty; refusing to replace the index.")
    return chunks
