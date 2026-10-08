"""Parser for e-reader `My Clippings.txt` exports.

The file format (as exported by e-readers that use this convention) is a
sequence of entries separated by a line of ten or more equals signs::

    Book Title (Author Name)
    - Your Highlight on page 12 | Location 345-346 | Added on Tuesday, April 23, 2024 10:15:32 PM

    The highlighted text goes here.
    ==========

Entries can be highlights, notes, or bookmarks (which have no body text).
This module is deliberately defensive: real-world export files are full of
minor format variations (missing page numbers, missing "Your", different
separators, BOM, CRLF line endings, non-English date strings) and the goal
is to extract as much as possible rather than fail outright.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

SEPARATOR_RE = re.compile(r"^=+\s*$")

# Recognized entry type keywords, in the clipping's metadata line.
_TYPE_RE = re.compile(
    r"(?P<type>Article\s+Highlight|Highlight|Note|Bookmark)", re.IGNORECASE
)
_PAGE_RE = re.compile(r"page\s+([^\s|]+)", re.IGNORECASE)
_LOCATION_RE = re.compile(r"[Ll]ocation\s+(\d+)(?:-(\d+))?")
_ADDED_RE = re.compile(r"[Aa]dded on\s*(.*)$")

# Date formats we try, in order. English-locale only for v0.1; non-English
# or unrecognized date strings are kept verbatim in `raw_added` with
# `added_at` left as None rather than raising.
_DATE_FORMATS = [
    "%A, %B %d, %Y %I:%M:%S %p",
    "%A, %d %B %Y %H:%M:%S",
    "%A, %B %d, %Y %H:%M:%S",
    "%B %d, %Y %I:%M:%S %p",
    "%d %B %Y %H:%M:%S",
    "%A, %d %b %Y %H:%M:%S",
    "%A, %B %d, %Y, %I:%M %p",
]

# Title line: "Book Title (Author Name)" — author is the last
# parenthesized group, if the line ends with one.
_TITLE_RE = re.compile(r"^(?P<title>.*?)(?:\s*\((?P<author>[^()]*)\))?\s*$")


class ClippingType(str, Enum):
    HIGHLIGHT = "highlight"
    NOTE = "note"
    BOOKMARK = "bookmark"
    UNKNOWN = "unknown"


_TYPE_MAP = {
    "highlight": ClippingType.HIGHLIGHT,
    "article highlight": ClippingType.HIGHLIGHT,
    "note": ClippingType.NOTE,
    "bookmark": ClippingType.BOOKMARK,
}


@dataclass
class Clipping:
    book_title: str
    author: str | None
    type: ClippingType
    page: str | None
    location_start: int | None
    location_end: int | None
    added_at: datetime | None
    raw_added: str | None
    text: str

    @property
    def content_hash(self) -> str:
        """Stable identity for dedup/idempotent import.

        Deliberately excludes `added_at`/`raw_added`: the same highlight
        re-exported later should hash identically so re-importing the same
        (or an overlapping) file is a no-op.
        """
        key = "|".join(
            [
                (self.book_title or "").strip().lower(),
                (self.author or "").strip().lower(),
                self.type.value,
                str(self.location_start or ""),
                str(self.location_end or ""),
                (self.text or "").strip(),
            ]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @property
    def location_range(self) -> tuple[int, int] | None:
        if self.location_start is None:
            return None
        return (self.location_start, self.location_end or self.location_start)


@dataclass
class ParseResult:
    clippings: list[Clipping] = field(default_factory=list)
    skipped: int = 0


def _parse_title_line(line: str) -> tuple[str, str | None]:
    m = _TITLE_RE.match(line.strip())
    if not m:
        return line.strip(), None
    title = m.group("title").strip()
    author = m.group("author")
    author = author.strip() if author else None
    return title or line.strip(), author


def _parse_date(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _parse_meta_line(line: str) -> dict:
    type_match = _TYPE_RE.search(line)
    type_str = type_match.group("type").lower() if type_match else None
    clip_type = _TYPE_MAP.get(type_str, ClippingType.UNKNOWN)

    page_match = _PAGE_RE.search(line)
    page = page_match.group(1) if page_match else None

    loc_match = _LOCATION_RE.search(line)
    location_start = int(loc_match.group(1)) if loc_match else None
    location_end = (
        int(loc_match.group(2)) if loc_match and loc_match.group(2) else location_start
    )

    added_match = _ADDED_RE.search(line)
    raw_added = added_match.group(1).strip() if added_match else None
    added_at = _parse_date(raw_added) if raw_added else None

    return {
        "type": clip_type,
        "page": page,
        "location_start": location_start,
        "location_end": location_end,
        "added_at": added_at,
        "raw_added": raw_added,
    }


def _split_entries(raw_text: str) -> list[list[str]]:
    """Split normalized text into entries (lists of lines), each ending at a separator."""
    lines = raw_text.split("\n")
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if SEPARATOR_RE.match(line.strip()):
            if current:
                entries.append(current)
            current = []
        else:
            current.append(line)
    if current and any(l.strip() for l in current):
        entries.append(current)
    return entries


def parse_text(raw_text: str) -> ParseResult:
    """Parse the full contents of a My Clippings.txt-style file."""
    result = ParseResult()
    for entry_lines in _split_entries(raw_text):
        # Drop leading/trailing fully-blank lines but keep internal blanks
        # (a blank line separates the metadata line from the body text).
        while entry_lines and not entry_lines[0].strip():
            entry_lines.pop(0)
        while entry_lines and not entry_lines[-1].strip():
            entry_lines.pop()

        if len(entry_lines) < 2:
            result.skipped += 1
            continue

        title_line, meta_line = entry_lines[0], entry_lines[1]
        body_lines = entry_lines[2:]
        # First body line is normally blank (separating meta from text);
        # strip at most one leading blank, keep the rest verbatim.
        if body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
        text = "\n".join(body_lines).strip()

        book_title, author = _parse_title_line(title_line)
        meta = _parse_meta_line(meta_line)

        if not book_title:
            result.skipped += 1
            continue

        result.clippings.append(
            Clipping(
                book_title=book_title,
                author=author,
                type=meta["type"],
                page=meta["page"],
                location_start=meta["location_start"],
                location_end=meta["location_end"],
                added_at=meta["added_at"],
                raw_added=meta["raw_added"],
                text=text,
            )
        )
    return result


def parse_file(path: str) -> ParseResult:
    """Read and parse a My Clippings.txt file, handling BOM and CRLF."""
    with open(path, "rb") as f:
        raw_bytes = f.read()
    # utf-8-sig transparently strips a UTF-8 BOM if present.
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return parse_text(text)


def _ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def dedupe_clippings(clippings: list[Clipping]) -> list[Clipping]:
    """Collapse overlapping/edited highlights within the same book.

    Kindle-style readers write a new entry each time a highlight is
    extended or edited, with the old entry left in place. For HIGHLIGHT
    entries in the same book whose location ranges overlap, keep only the
    one with the latest `added_at` (falling back to the longest text when
    dates are missing/equal). Notes and bookmarks are passed through
    untouched since they are not subject to this behavior.
    """
    by_book: dict[tuple[str, str | None], list[Clipping]] = {}
    passthrough: list[Clipping] = []

    for c in clippings:
        if c.type != ClippingType.HIGHLIGHT or c.location_range is None:
            passthrough.append(c)
            continue
        by_book.setdefault((c.book_title, c.author), []).append(c)

    deduped: list[Clipping] = list(passthrough)
    for _, group in by_book.items():
        group_sorted = sorted(group, key=lambda c: c.location_range[0])
        kept: list[Clipping] = []
        for c in group_sorted:
            merged = False
            for i, existing in enumerate(kept):
                if _ranges_overlap(existing.location_range, c.location_range):
                    winner = _pick_winner(existing, c)
                    kept[i] = winner
                    merged = True
                    break
            if not merged:
                kept.append(c)
        deduped.extend(kept)
    return deduped


def _pick_winner(a: Clipping, b: Clipping) -> Clipping:
    if a.added_at and b.added_at:
        return b if b.added_at >= a.added_at else a
    if a.added_at or b.added_at:
        return a if a.added_at else b
    return b if len(b.text) >= len(a.text) else a
