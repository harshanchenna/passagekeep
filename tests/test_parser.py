from pathlib import Path

import pytest

from passagekeep.parser import (
    ClippingType,
    dedupe_clippings,
    parse_file,
    parse_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_file_basic_counts():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    assert result.skipped == 0
    # 9 entries in the fixture
    assert len(result.clippings) == 9


def test_bom_is_stripped():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    first = result.clippings[0]
    # The book title should not start with a BOM character.
    assert not first.book_title.startswith("﻿")
    assert first.book_title == "Moby-Dick; or, The Whale"


def test_crlf_line_endings_parse_identically():
    lf = parse_file(str(FIXTURES / "sample_clippings.txt"))
    crlf = parse_file(str(FIXTURES / "sample_clippings_crlf.txt"))
    assert len(lf.clippings) == len(crlf.clippings)
    for a, b in zip(lf.clippings, crlf.clippings):
        assert a.text == b.text
        assert a.book_title == b.book_title


def test_title_and_author_split():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    pride = [c for c in result.clippings if "Pride" in c.book_title][0]
    assert pride.book_title == "Pride and Prejudice"
    assert pride.author == "Jane Austen"


def test_highlight_type_and_location():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    h = result.clippings[0]
    assert h.type == ClippingType.HIGHLIGHT
    assert h.location_start == 1
    assert h.location_end == 2
    assert h.page == "1"
    assert h.added_at is not None
    assert h.added_at.year == 2024
    assert h.added_at.hour == 22  # 10:15:32 PM


def test_note_type():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    notes = [c for c in result.clippings if c.type == ClippingType.NOTE]
    assert len(notes) == 2
    assert "foreshadows" in notes[0].text


def test_bookmark_has_no_text():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    bookmarks = [c for c in result.clippings if c.type == ClippingType.BOOKMARK]
    assert len(bookmarks) == 1
    assert bookmarks[0].text == ""


def test_location_without_page():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    holmes = [c for c in result.clippings if "Holmes" in c.book_title]
    no_page = [c for c in holmes if c.page is None]
    assert len(no_page) == 1
    assert no_page[0].location_start == 30
    assert no_page[0].location_end == 31


def test_dedupe_overlapping_highlights():
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    deduped = dedupe_clippings(result.clippings)
    moby_highlights = [
        c
        for c in deduped
        if "Moby" in c.book_title and c.type == ClippingType.HIGHLIGHT
    ]
    # The two overlapping Moby-Dick highlights (1-2 and 1-5) collapse to one,
    # keeping the later/longer version.
    assert len(moby_highlights) == 1
    assert "never mind" in moby_highlights[0].text

    # Non-overlapping highlights and other types are untouched.
    assert len(deduped) == 8  # 9 clippings - 1 collapsed duplicate


def test_content_hash_stable_across_reparse():
    result1 = parse_file(str(FIXTURES / "sample_clippings.txt"))
    result2 = parse_file(str(FIXTURES / "sample_clippings.txt"))
    hashes1 = sorted(c.content_hash for c in result1.clippings)
    hashes2 = sorted(c.content_hash for c in result2.clippings)
    assert hashes1 == hashes2


def test_malformed_entry_is_skipped_not_fatal():
    raw = "Just a title with no metadata line\n==========\n"
    result = parse_text(raw)
    assert result.skipped == 1
    assert result.clippings == []


def test_empty_file():
    result = parse_text("")
    assert result.clippings == []
    assert result.skipped == 0
