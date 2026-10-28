"""Text-based official PDFs → page text → passages (articles where the document has them).

No OCR: a scanned PDF yields no text, and the snapshot records ``text_extracted=False``
instead of guessing. Headers and footers repeated on most pages are removed so a
passage is the document's own wording. Articles are detected only on a line of their
own ("Artigo 25.º", "Artigo 5.º-A"), which skips table-of-contents lines with dot
leaders and page numbers.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader

MAX_PAGES = 600
MAX_PASSAGE = 2400
MIN_TEXT = 200
#: Header/footer candidates: this many lines at the top and bottom of each page.
EDGE_LINES = 3

_ARTICLE = re.compile(r"^\s*(Artigo\s+\d+\.?\s*º(?:\s*-\s*[A-Z])?)\s*$")
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class Passage:
    page: int
    text: str
    article: str | None = None
    heading: str | None = None
    part: int | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    pages: int
    text_extracted: bool
    passages: list[Passage]
    version_detected: str | None


def extract_pdf(data: bytes) -> ExtractedDocument:
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"document has more than {MAX_PAGES} pages")
    pages = [(page.extract_text() or "") for page in reader.pages]
    meta = reader.metadata or {}
    version = str(meta.get("/ModDate") or meta.get("/CreationDate") or "") or None
    if sum(len(p.strip()) for p in pages) < MIN_TEXT:
        return ExtractedDocument(len(pages), False, [], version)
    return ExtractedDocument(len(pages), True, passages_from_pages(pages), version)


def _edges(lines: list[str]) -> set[str]:
    return {_DIGITS.sub("#", line) for line in lines[:EDGE_LINES] + lines[-EDGE_LINES:] if not _ARTICLE.match(line)}


def _strip_repeated_lines(pages: list[str]) -> list[list[str]]:
    """Drop header/footer lines: among each page's first and last lines, those (ignoring digits,
    e.g. page numbers) that recur on at least half the pages. Article headings are never dropped."""
    split = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    if len(split) < 4:
        return split
    counts = Counter(key for lines in split for key in _edges(lines))
    repeated = {key for key, n in counts.items() if n >= len(split) / 2}
    return [
        [line for n, line in enumerate(lines)
         if not ((n < EDGE_LINES or n >= len(lines) - EDGE_LINES) and _DIGITS.sub("#", line) in repeated
                 and not _ARTICLE.match(line))]
        for lines in split
    ]


def _split(text: str, limit: int = MAX_PASSAGE) -> list[str]:
    parts, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


def passages_from_pages(pages: list[str]) -> list[Passage]:
    lines_by_page = _strip_repeated_lines(pages)
    articles: list[tuple[int, str, list[str]]] = []  # (page, article label, lines)
    for page_no, lines in enumerate(lines_by_page, 1):
        for line in lines:
            match = _ARTICLE.match(line)
            if match:
                articles.append((page_no, re.sub(r"\s+", " ", match.group(1)), []))
            elif articles:
                articles[-1][2].append(line)

    passages: list[Passage] = []
    if articles:
        for page_no, label, body in articles:
            heading = body[0] if body and len(body[0]) <= 160 else None
            text = "\n".join(body).strip()
            chunks = _split(text) or [""]
            for n, chunk in enumerate(chunks, 1):
                if chunk:
                    passages.append(Passage(page_no, chunk, label, heading, n if len(chunks) > 1 else None))
        return passages

    for page_no, lines in enumerate(lines_by_page, 1):
        for n, chunk in enumerate(parts := _split("\n".join(lines), 1600), 1):
            passages.append(Passage(page_no, chunk, part=n if len(parts) > 1 else None))
    return passages
