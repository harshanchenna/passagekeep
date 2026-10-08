"""FastAPI + HTMX local web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from passagekeep.export import export_book_markdown
from passagekeep.storage import Store

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Passagekeep")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def get_store() -> Store:
        return Store(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with get_store() as store:
            books = store.list_books()
        return templates.TemplateResponse(
            request, "index.html", {"books": books}
        )

    @app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(request: Request, book_id: int):
        with get_store() as store:
            book = store.get_book(book_id)
            highlights = store.list_highlights(book_id)
            tags_by_highlight = {h["id"]: store.get_tags(h["id"]) for h in highlights}
        return templates.TemplateResponse(
            request,
            "book.html",
            {
                "book": book,
                "highlights": highlights,
                "tags_by_highlight": tags_by_highlight,
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = ""):
        results = []
        if q.strip():
            with get_store() as store:
                results = store.search(q)
        return templates.TemplateResponse(
            request, "search.html", {"query": q, "results": results}
        )

    @app.post("/highlights/{highlight_id}/tags", response_class=HTMLResponse)
    def add_tag(request: Request, highlight_id: int, tag: str = Form(...)):
        with get_store() as store:
            store.add_tag(highlight_id, tag)
            tags = store.get_tags(highlight_id)
        return templates.TemplateResponse(
            request, "_tags.html", {"highlight_id": highlight_id, "tags": tags}
        )

    @app.post("/highlights/{highlight_id}/tags/{tag}/delete", response_class=HTMLResponse)
    def delete_tag(request: Request, highlight_id: int, tag: str):
        with get_store() as store:
            store.remove_tag(highlight_id, tag)
            tags = store.get_tags(highlight_id)
        return templates.TemplateResponse(
            request, "_tags.html", {"highlight_id": highlight_id, "tags": tags}
        )

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        with get_store() as store:
            due = store.due_reviews()
        return templates.TemplateResponse(request, "review.html", {"due": due})

    @app.post("/review/{highlight_id}/grade", response_class=HTMLResponse)
    def grade(request: Request, highlight_id: int, quality: int = Form(...)):
        with get_store() as store:
            store.grade_review(highlight_id, quality)
            due = store.due_reviews()
        return templates.TemplateResponse(request, "_review_queue.html", {"due": due})

    @app.get("/books/{book_id}/export", response_class=PlainTextResponse)
    def export_book(book_id: int):
        with get_store() as store:
            markdown = export_book_markdown(store, book_id)
        return PlainTextResponse(markdown, media_type="text/markdown")

    return app
