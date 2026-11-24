"""Split policy text into readable, line-preserving chunks."""

import re
import unicodedata

from config.settings import CHUNK_SIZE, CHUNK_OVERLAP


HEADING_PATTERNS = (
    re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$"),
    re.compile(r"^\s*\*\*(.{2,100}?)\*\*\s*$"),
)


def _split_into_sections(text: str, fallback: str) -> list[tuple[str, str]]:
    """Separate headings so chunks from different sections are not mixed."""
    sections = []
    current_title = fallback
    current_lines = []

    for line in text.splitlines():
        heading = None
        for pattern in HEADING_PATTERNS:
            match = pattern.match(line)
            if match:
                heading = match.group(1).strip()
                break

        if heading:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, body))
            current_title = heading
            current_lines = []
        else:
            current_lines.append(line)

    body = "\n".join(current_lines).strip()
    if body:
        sections.append((current_title, body))

    return sections or [(fallback, text.strip())]


def _split_lines(text: str) -> list[str]:
    """Split on complete source lines; never cut a line in the middle."""
    return [line for line in text.splitlines() if line.strip()]


def _chunk_section(text: str) -> list[str]:
    """Build bounded chunks with overlap made from complete lines."""
    lines = _split_lines(text)
    if not lines:
        return []

    chunks = []
    start = 0

    while start < len(lines):
        end = start
        current_length = 0

        # Add whole lines until the next line would exceed the target size.
        while end < len(lines):
            added_length = len(lines[end]) + (1 if end > start else 0)
            if end > start and current_length + added_length > CHUNK_SIZE:
                break
            current_length += added_length
            end += 1
            # A single unusually long line is kept intact rather than broken.
            if current_length > CHUNK_SIZE:
                print(
                    f"[WARNING] One source line is {current_length} characters; "
                    f"keeping it intact (target: {CHUNK_SIZE})."
                )
                break

        chunks.append("\n".join(lines[start:end]))
        if end >= len(lines):
            break

        # Start the next chunk with whole trailing lines from this chunk.
        # At least one line is carried over when possible.
        overlap_start = end
        overlap_length = 0
        while overlap_start > start + 1 and overlap_length < CHUNK_OVERLAP:
            overlap_start -= 1
            overlap_length += len(lines[overlap_start]) + 1

        # Guarantee forward progress, even when a line is longer than the target.
        start = max(start + 1, overlap_start)

    return chunks


def chunk_documents(documents: list[dict]) -> list[dict]:
    """Chunk page documents while preserving section and source metadata."""
    chunks = []

    for document in documents:
        # NFC normalizes equivalent Unicode spellings without changing line order.
        page_text = unicodedata.normalize("NFC", document["text"])
        page_metadata = document["metadata"].copy()
        fallback_section = page_metadata.get("title", "General")

        for section, section_text in _split_into_sections(page_text, fallback_section):
            for chunk_text in _chunk_section(section_text):
                metadata = page_metadata.copy()
                metadata["section"] = section
                # Chroma accepts scalar metadata values only.
                metadata = {
                    key: value for key, value in metadata.items()
                    if value is not None and isinstance(value, (str, int, float, bool))
                }
                chunks.append({"text": chunk_text, "metadata": metadata})

    print(
        f"[SUCCESS] Created {len(chunks)} line-preserving chunks "
        f"from {len(documents)} pages (target={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})."
    )
    return chunks
