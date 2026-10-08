"""Command-line entry point: import, serve, export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from passagekeep.export import export_book_markdown
from passagekeep.parser import dedupe_clippings, parse_file
from passagekeep.storage import Store

DEFAULT_DB = "passagekeep.db"


def cmd_import(args: argparse.Namespace) -> int:
    result = parse_file(args.file)
    clippings = dedupe_clippings(result.clippings)
    with Store(args.db) as store:
        stats = store.import_clippings(clippings)
    print(f"Parsed {len(result.clippings)} clippings ({result.skipped} skipped lines).")
    print(f"Books touched: {stats.books_seen}")
    print(f"Added: {stats.highlights_added}  Duplicates skipped: {stats.highlights_duplicate}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from passagekeep.webapp import create_app

    app = create_app(args.db)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        books = store.list_books()
        match = None
        for b in books:
            if b["title"].strip().lower() == args.book.strip().lower():
                match = b
                break
        if match is None:
            # fall back to substring match
            for b in books:
                if args.book.strip().lower() in b["title"].strip().lower():
                    match = b
                    break
        if match is None:
            print(f"No book matching '{args.book}' found.", file=sys.stderr)
            return 1

        markdown = export_book_markdown(store, match["id"])

    if args.output:
        out_path = Path(args.output)
    else:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in match["title"])
        out_path = Path(f"{safe_name}.md")

    out_path.write_text(markdown, encoding="utf-8")
    print(f"Exported '{match['title']}' to {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="passagekeep")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Import a My Clippings.txt file")
    p_import.add_argument("file", help="Path to the clippings file")
    p_import.set_defaults(func=cmd_import)

    p_serve = sub.add_parser("serve", help="Run the local web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8420)
    p_serve.set_defaults(func=cmd_serve)

    p_export = sub.add_parser("export", help="Export a book's highlights to Markdown")
    p_export.add_argument("book", help="Book title (exact or substring match)")
    p_export.add_argument("--format", choices=["md"], default="md")
    p_export.add_argument("--output", help="Output file path (default: <title>.md)")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
