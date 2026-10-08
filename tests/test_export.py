from pathlib import Path

from passagekeep.export import export_book_markdown
from passagekeep.parser import dedupe_clippings, parse_file
from passagekeep.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def _seeded_store(tmp_path) -> Store:
    db = tmp_path / "test.db"
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    clippings = dedupe_clippings(result.clippings)
    store = Store(db)
    store.import_clippings(clippings)
    return store


def test_export_includes_frontmatter(tmp_path):
    store = _seeded_store(tmp_path)
    books = {b["title"]: b["id"] for b in store.list_books()}
    md = export_book_markdown(store, books["Pride and Prejudice"])

    assert md.startswith("---\n")
    assert 'title: "Pride and Prejudice"' in md
    assert 'author: "Jane Austen"' in md
    assert "source: passagekeep" in md


def test_export_includes_all_highlights_and_notes(tmp_path):
    store = _seeded_store(tmp_path)
    books = {b["title"]: b["id"] for b in store.list_books()}
    md = export_book_markdown(store, books["Pride and Prejudice"])

    assert "a truth universally acknowledged" in md
    assert "tolerable, but not handsome" in md
    assert "Darcy, early characterization." in md
    assert "## Highlight" in md
    assert "## Note" in md


def test_export_includes_tags(tmp_path):
    store = _seeded_store(tmp_path)
    books = {b["title"]: b["id"] for b in store.list_books()}
    highlight = store.list_highlights(books["Pride and Prejudice"])[0]
    store.add_tag(highlight["id"], "theme")

    md = export_book_markdown(store, books["Pride and Prejudice"])
    assert "#theme" in md
