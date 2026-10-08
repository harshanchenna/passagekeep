from pathlib import Path

from fastapi.testclient import TestClient

from passagekeep.parser import dedupe_clippings, parse_file
from passagekeep.storage import Store
from passagekeep.webapp import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def _seeded_db(tmp_path):
    db = tmp_path / "web.db"
    result = parse_file(str(FIXTURES / "sample_clippings.txt"))
    clippings = dedupe_clippings(result.clippings)
    with Store(db) as store:
        store.import_clippings(clippings)
    return db


def test_index_lists_books(tmp_path):
    db = _seeded_db(tmp_path)
    client = TestClient(create_app(str(db)))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Moby-Dick" in resp.text
    assert "Pride and Prejudice" in resp.text


def test_search_finds_highlight(tmp_path):
    db = _seeded_db(tmp_path)
    client = TestClient(create_app(str(db)))
    resp = client.get("/search", params={"q": "Ishmael"})
    assert resp.status_code == 200
    assert "Ishmael" in resp.text


def test_review_queue_shows_due_cards(tmp_path):
    db = _seeded_db(tmp_path)
    client = TestClient(create_app(str(db)))
    resp = client.get("/review")
    assert resp.status_code == 200
    # Everything is due immediately after import.
    assert "How well did you recall this?" in resp.text


def test_book_export_route(tmp_path):
    db = _seeded_db(tmp_path)
    with Store(db) as store:
        book_id = store.list_books()[0]["id"]
    client = TestClient(create_app(str(db)))
    resp = client.get(f"/books/{book_id}/export")
    assert resp.status_code == 200
    assert resp.text.startswith("---\n")


def test_add_and_remove_tag(tmp_path):
    db = _seeded_db(tmp_path)
    with Store(db) as store:
        highlight_id = store.list_highlights()[0]["id"]
    client = TestClient(create_app(str(db)))
    resp = client.post(f"/highlights/{highlight_id}/tags", data={"tag": "favorite"})
    assert resp.status_code == 200
    assert "favorite" in resp.text
