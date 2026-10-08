from pathlib import Path

from passagekeep.parser import dedupe_clippings, parse_file
from passagekeep.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def _import(db_path, fixture="sample_clippings.txt"):
    result = parse_file(str(FIXTURES / fixture))
    clippings = dedupe_clippings(result.clippings)
    with Store(db_path) as store:
        return store.import_clippings(clippings)


def test_import_creates_books_and_highlights(tmp_path):
    db = tmp_path / "test.db"
    stats = _import(db)
    assert stats.books_seen == 3
    assert stats.highlights_added == 8

    with Store(db) as store:
        books = store.list_books()
        assert len(books) == 3
        titles = {b["title"] for b in books}
        assert "Moby-Dick; or, The Whale" in titles
        assert "Pride and Prejudice" in titles


def test_reimport_is_idempotent(tmp_path):
    db = tmp_path / "test.db"
    stats1 = _import(db)
    stats2 = _import(db)

    assert stats2.highlights_added == 0
    assert stats2.highlights_duplicate == stats1.highlights_added

    with Store(db) as store:
        total = store.conn.execute("SELECT COUNT(*) AS c FROM highlights").fetchone()["c"]
    assert total == stats1.highlights_added


def test_reimport_crlf_variant_also_dedupes(tmp_path):
    """Same content, different line endings, should not double the DB."""
    db = tmp_path / "test.db"
    stats1 = _import(db, "sample_clippings.txt")
    stats2 = _import(db, "sample_clippings_crlf.txt")

    assert stats2.highlights_added == 0
    assert stats2.highlights_duplicate == stats1.highlights_added


def test_search_finds_highlight(tmp_path):
    db = tmp_path / "test.db"
    _import(db)
    with Store(db) as store:
        results = store.search("Ishmael")
    assert len(results) == 1
    assert "Ishmael" in results[0]["text"]


def test_tags_add_and_remove(tmp_path):
    db = tmp_path / "test.db"
    _import(db)
    with Store(db) as store:
        highlight = store.list_highlights()[0]
        store.add_tag(highlight["id"], "Favorite")
        store.add_tag(highlight["id"], "favorite")  # case-insensitive, no dup
        tags = store.get_tags(highlight["id"])
        assert tags == ["favorite"]
        store.remove_tag(highlight["id"], "favorite")
        assert store.get_tags(highlight["id"]) == []


def test_review_queue_and_grading(tmp_path):
    db = tmp_path / "test.db"
    _import(db)
    with Store(db) as store:
        due = store.due_reviews()
        assert len(due) > 0
        first_id = due[0]["id"]
        store.grade_review(first_id, 5)
        row = store.conn.execute(
            "SELECT * FROM reviews WHERE highlight_id = ?", (first_id,)
        ).fetchone()
        assert row["repetitions"] == 1
        assert row["interval_days"] == 1

        # Graded card with a future due date should drop out of the
        # immediately-due queue.
        due_after = store.due_reviews()
        assert first_id not in [h["id"] for h in due_after]


def test_low_quality_grade_resets_interval(tmp_path):
    db = tmp_path / "test.db"
    _import(db)
    with Store(db) as store:
        due = store.due_reviews()
        hid = due[0]["id"]
        store.grade_review(hid, 5)
        store.grade_review(hid, 1)  # forgot it
        row = store.conn.execute(
            "SELECT * FROM reviews WHERE highlight_id = ?", (hid,)
        ).fetchone()
        assert row["repetitions"] == 0
        assert row["interval_days"] == 1
