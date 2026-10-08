"""SQLite storage layer: books, highlights, tags, and SM-2 review state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from passagekeep.parser import Clipping

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    UNIQUE(title, author)
);

CREATE TABLE IF NOT EXISTS highlights (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    page TEXT,
    location_start INTEGER,
    location_end INTEGER,
    added_at TEXT,
    raw_added TEXT,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS highlight_tags (
    highlight_id INTEGER NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (highlight_id, tag_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    highlight_id INTEGER PRIMARY KEY REFERENCES highlights(id) ON DELETE CASCADE,
    due_at TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    last_reviewed_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS highlights_fts USING fts5(
    text,
    content='highlights',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN
    INSERT INTO highlights_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN
    INSERT INTO highlights_fts(highlights_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS highlights_au AFTER UPDATE ON highlights BEGIN
    INSERT INTO highlights_fts(highlights_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO highlights_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


@dataclass
class ImportStats:
    books_seen: int = 0
    highlights_total: int = 0
    highlights_added: int = 0
    highlights_duplicate: int = 0


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _get_or_create_book(self, title: str, author: str | None) -> int:
        cur = self.conn.execute(
            "SELECT id FROM books WHERE title = ? AND author IS ?", (title, author)
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO books (title, author) VALUES (?, ?)", (title, author)
        )
        return cur.lastrowid

    def import_clippings(self, clippings: list[Clipping]) -> ImportStats:
        """Insert clippings, skipping any whose content_hash already exists.

        This is what makes re-importing the same (or overlapping) export
        file a no-op: `content_hash` is derived purely from the clipping's
        content, not its import time.
        """
        stats = ImportStats()
        books_touched: set[tuple[str, str | None]] = set()
        with self.tx():
            for c in clippings:
                stats.highlights_total += 1
                books_touched.add((c.book_title, c.author))
                book_id = self._get_or_create_book(c.book_title, c.author)
                try:
                    self.conn.execute(
                        """
                        INSERT INTO highlights
                            (book_id, type, page, location_start, location_end,
                             added_at, raw_added, text, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            book_id,
                            c.type.value,
                            c.page,
                            c.location_start,
                            c.location_end,
                            c.added_at.isoformat() if c.added_at else None,
                            c.raw_added,
                            c.text,
                            c.content_hash,
                        ),
                    )
                    stats.highlights_added += 1
                except sqlite3.IntegrityError:
                    stats.highlights_duplicate += 1
        stats.books_seen = len(books_touched)
        return stats

    # --- Browse / search -------------------------------------------------

    def list_books(self):
        return self.conn.execute(
            """
            SELECT b.id, b.title, b.author, COUNT(h.id) AS highlight_count
            FROM books b LEFT JOIN highlights h ON h.book_id = b.id
            GROUP BY b.id ORDER BY b.title COLLATE NOCASE
            """
        ).fetchall()

    def get_book(self, book_id: int):
        return self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()

    def list_highlights(self, book_id: int | None = None):
        if book_id is None:
            return self.conn.execute(
                "SELECT * FROM highlights ORDER BY book_id, location_start"
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM highlights WHERE book_id = ? ORDER BY location_start",
            (book_id,),
        ).fetchall()

    def get_highlight(self, highlight_id: int):
        return self.conn.execute(
            "SELECT * FROM highlights WHERE id = ?", (highlight_id,)
        ).fetchone()

    def search(self, query: str, limit: int = 50):
        if not query.strip():
            return []
        # FTS5 default query syntax; wrap in quotes-safe form by escaping.
        safe_query = query.replace('"', '""')
        return self.conn.execute(
            """
            SELECT h.*, b.title AS book_title, b.author AS book_author
            FROM highlights_fts f
            JOIN highlights h ON h.id = f.rowid
            JOIN books b ON b.id = h.book_id
            WHERE f.text MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (f'"{safe_query}"', limit),
        ).fetchall()

    # --- Tags --------------------------------------------------------------

    def add_tag(self, highlight_id: int, tag_name: str):
        tag_name = tag_name.strip().lower()
        if not tag_name:
            return
        with self.tx():
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
            tag_id = self.conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()["id"]
            self.conn.execute(
                "INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_id) VALUES (?, ?)",
                (highlight_id, tag_id),
            )

    def remove_tag(self, highlight_id: int, tag_name: str):
        tag_name = tag_name.strip().lower()
        with self.tx():
            self.conn.execute(
                """
                DELETE FROM highlight_tags
                WHERE highlight_id = ?
                  AND tag_id = (SELECT id FROM tags WHERE name = ?)
                """,
                (highlight_id, tag_name),
            )

    def get_tags(self, highlight_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN highlight_tags ht ON ht.tag_id = t.id
            WHERE ht.highlight_id = ?
            ORDER BY t.name
            """,
            (highlight_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # --- Spaced repetition (SM-2) ------------------------------------------

    def ensure_review_state(self, highlight_id: int):
        with self.tx():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO reviews (highlight_id, due_at)
                VALUES (?, datetime('now'))
                """,
                (highlight_id,),
            )

    def due_reviews(self, limit: int = 20):
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reviews (highlight_id, due_at)
            SELECT id, datetime('now') FROM highlights
            WHERE id NOT IN (SELECT highlight_id FROM reviews)
            """
        )
        self.conn.commit()
        return self.conn.execute(
            """
            SELECT h.*, b.title AS book_title, b.author AS book_author,
                   r.due_at, r.interval_days, r.repetitions, r.ease_factor
            FROM reviews r
            JOIN highlights h ON h.id = r.highlight_id
            JOIN books b ON b.id = h.book_id
            WHERE r.due_at <= datetime('now')
            ORDER BY r.due_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def grade_review(self, highlight_id: int, quality: int):
        """SM-2 update. quality: 0-5 (standard SM-2 grading scale)."""
        quality = max(0, min(5, quality))
        row = self.conn.execute(
            "SELECT * FROM reviews WHERE highlight_id = ?", (highlight_id,)
        ).fetchone()
        if row is None:
            self.ensure_review_state(highlight_id)
            row = self.conn.execute(
                "SELECT * FROM reviews WHERE highlight_id = ?", (highlight_id,)
            ).fetchone()

        ease = row["ease_factor"]
        reps = row["repetitions"]
        interval = row["interval_days"]

        if quality < 3:
            reps = 0
            interval = 1
        else:
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 6
            else:
                interval = round(interval * ease, 2)

        ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        ease = max(1.3, ease)

        due_at = datetime.now(timezone.utc) + timedelta(days=interval)
        with self.tx():
            self.conn.execute(
                """
                UPDATE reviews
                SET due_at = ?, interval_days = ?, repetitions = ?,
                    ease_factor = ?, last_reviewed_at = datetime('now')
                WHERE highlight_id = ?
                """,
                (due_at.isoformat(), interval, reps, ease, highlight_id),
            )
