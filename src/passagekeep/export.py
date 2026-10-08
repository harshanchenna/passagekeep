"""Markdown export, Obsidian-friendly (YAML frontmatter + one section per highlight)."""

from __future__ import annotations

from passagekeep.storage import Store


def _yaml_escape(value: str) -> str:
    if value is None:
        return '""'
    value = value.replace('"', '\\"')
    return f'"{value}"'


def export_book_markdown(store: Store, book_id: int) -> str:
    book = store.get_book(book_id)
    if book is None:
        raise ValueError(f"No book with id {book_id}")
    highlights = store.list_highlights(book_id)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {_yaml_escape(book['title'])}")
    lines.append(f"author: {_yaml_escape(book['author'] or 'Unknown')}")
    lines.append(f"highlight_count: {len(highlights)}")
    lines.append("source: passagekeep")
    lines.append("---")
    lines.append("")
    lines.append(f"# {book['title']}")
    if book["author"]:
        lines.append(f"*by {book['author']}*")
    lines.append("")

    for h in highlights:
        tags = store.get_tags(h["id"])
        loc = h["location_start"]
        if h["location_end"] and h["location_end"] != h["location_start"]:
            loc_str = f"{h['location_start']}-{h['location_end']}"
        else:
            loc_str = str(loc) if loc is not None else "?"

        heading = h["type"].capitalize()
        lines.append(f"## {heading} — Location {loc_str}")
        if h["page"]:
            lines.append(f"*Page {h['page']}*")
        if tags:
            lines.append(" ".join(f"#{t}" for t in tags))
        lines.append("")
        if h["text"]:
            lines.append(f"> {h['text']}")
        else:
            lines.append("*(no text)*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
