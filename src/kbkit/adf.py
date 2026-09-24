"""Atlassian Document Format (ADF) tree utilities.

Bug classes this module exists to prevent:

* Words split across mark boundaries. ADF splits "Scanned" into several text
  nodes when part of it is bold or linked; joining text nodes with " " turns it
  into "Sca nned". Inline text here is concatenated with no separator.
* Cards silently dropped. inlineCard / blockCard / embedCard carry their URL
  in ``attrs``, not in text, so a renderer that only collects ``text`` loses
  them, including inside headings. They are never dropped here.
* Unknown node types raising or vanishing. Anything unrecognised is walked
  through its ``content`` and never raises.
* Table labels assumed to be in column 0 only. ``row_value`` checks column 0
  and column 1, because many templates put a row number or icon first.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

__all__ = ["iter_nodes", "to_text", "cards", "tables", "row_value", "find_adf"]

CARD_TYPES = ("inlineCard", "blockCard", "embedCard")

# Nodes that occupy their own line(s): output is guaranteed to end with a
# newline after each of these.
BLOCK_TYPES = {
    "paragraph", "heading", "listItem", "tableRow", "blockquote", "codeBlock",
    "panel", "expand", "nestedExpand", "rule", "table", "bulletList",
    "orderedList", "taskList", "taskItem", "decisionList", "decisionItem",
    "mediaSingle", "mediaGroup", "blockCard", "embedCard", "extension",
    "bodiedExtension", "layoutSection", "layoutColumn",
}


def _load(doc: Any) -> Any:
    """Accept a JSON string as well as an already-decoded object."""
    if isinstance(doc, (str, bytes)):
        return json.loads(doc)
    return doc


def iter_nodes(doc: Any) -> Iterator[dict]:
    """Yield every dict node depth-first (pre-order), document order.

    Recurses into ``content`` lists and into plain lists. Accepts a JSON string.
    """
    doc = _load(doc)
    stack = [doc]
    while stack:
        n = stack.pop()
        if isinstance(n, list):
            stack.extend(reversed(n))
        elif isinstance(n, dict):
            yield n
            c = n.get("content")
            if isinstance(c, list):
                stack.extend(reversed(c))


def _card_url(attrs: dict | None) -> str:
    """URL of a card node: attrs.url, else attrs.data.url / @id, else JSON of data."""
    attrs = attrs or {}
    url = attrs.get("url")
    if isinstance(url, str) and url:
        return url
    data = attrs.get("data")
    if isinstance(data, dict):
        for k in ("url", "@id"):
            v = data.get(k)
            if isinstance(v, str) and v:
                return v
    if data:
        return json.dumps(data, sort_keys=True, ensure_ascii=False)
    return ""


def _date(ts: Any) -> str:
    """ADF date attrs.timestamp is epoch milliseconds (as a string) -> ISO date, UTC."""
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return "" if ts is None else str(ts)


class _Writer:
    """Accumulates output and tracks whether we are at the start of a line."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.bol = True  # beginning of line

    def write(self, s: str) -> None:
        if s:
            self.parts.append(s)
            self.bol = s.endswith("\n")

    def prefix(self, s: str) -> None:
        # A line prefix ("- ", "[x] ") still counts as the start of a line, so
        # the block that follows does not force another newline.
        self.parts.append(s)
        self.bol = True

    def newline(self) -> None:
        if not self.bol:
            self.write("\n")

    def text(self) -> str:
        return "".join(self.parts)


def to_text(doc: Any, *, cards: str | Callable[[str, str], str] = "url") -> str:
    """Render an ADF document (or any node / list of nodes) as plain text.

    * Block nodes end with a newline; inline text inside a block is joined with
      no separator, so words split across marks stay whole.
    * Cards are rendered via ``cards``: ``"url"`` emits the bare URL; a callable
      ``f(node_type, url) -> str`` lets the caller choose a format. A card is
      never dropped, wherever it sits (headings, table cells, panels).
    * Table cells are separated by ``" | "`` on one line per row.
    * Unknown node types are walked through their ``content``; nothing raises.

    A JSON string is decoded first; a string that is not JSON is returned as is
    (plain-text fields are common where ADF was expected).
    """
    if isinstance(doc, (str, bytes)):
        try:
            doc = json.loads(doc)
        except ValueError:
            return doc.decode("utf-8", "replace") if isinstance(doc, bytes) else doc
    if callable(cards):
        fmt = cards
    elif cards == "url":
        fmt = lambda _t, url: url  # noqa: E731
    else:
        raise ValueError("cards must be 'url' or a callable(node_type, url)")
    w = _Writer()
    _render(doc, w, fmt, 0)
    return w.text()


def _children(n: dict) -> list:
    c = n.get("content")
    return c if isinstance(c, list) else []


def _render_children(n: dict, w: _Writer, fmt, depth: int) -> None:
    for c in _children(n):
        _render(c, w, fmt, depth)


def _cell_text(cell: dict, fmt) -> str:
    sub = _Writer()
    _render_children(cell, sub, fmt, 0)
    # One row per line: newlines inside a cell become spaces.
    return " ".join(line.strip() for line in sub.text().splitlines() if line.strip())


def _render(n: Any, w: _Writer, fmt, depth: int) -> None:
    if isinstance(n, list):
        for x in n:
            _render(x, w, fmt, depth)
        return
    if not isinstance(n, dict):
        return
    t = n.get("type")
    a = n.get("attrs") if isinstance(n.get("attrs"), dict) else {}

    # ---- inline leaves -------------------------------------------------
    if t == "text":
        w.write(str(n.get("text", "")))
        return
    if t == "hardBreak":
        w.write("\n")
        return
    if t == "mention":
        w.write(a.get("text") or ("@" + str(a.get("id", ""))))
        return
    if t == "emoji":
        w.write(a.get("text") or a.get("shortName") or "")
        return
    if t == "status":
        w.write(str(a.get("text", "")))
        return
    if t == "date":
        w.write(_date(a.get("timestamp")))
        return
    if t == "inlineCard":
        w.write(fmt(t, _card_url(a)))
        return
    if t == "media":
        w.write("[media]")
        return
    if t == "inlineExtension":
        if _children(n):
            _render_children(n, w, fmt, depth)
        else:
            w.write("[extension: %s]" % (a.get("extensionKey") or "?"))
        return

    # ---- block nodes ---------------------------------------------------
    if t not in BLOCK_TYPES:
        # doc, unknown types, and inline containers: just walk the content.
        _render_children(n, w, fmt, depth)
        return

    w.newline()
    if t in ("blockCard", "embedCard"):
        w.write(fmt(t, _card_url(a)))
    elif t == "rule":
        w.write("---")
    elif t == "mediaSingle" or t == "mediaGroup":
        if _children(n):
            _render_children(n, w, fmt, depth)
        else:
            w.write("[media]")
    elif t in ("extension", "bodiedExtension"):
        if _children(n):
            _render_children(n, w, fmt, depth)
        else:
            w.write("[extension: %s]" % (a.get("extensionKey") or "?"))
    elif t in ("expand", "nestedExpand"):
        if a.get("title"):
            w.write(str(a["title"]))
            w.newline()
        _render_children(n, w, fmt, depth)
    elif t == "tableRow":
        cells = [c for c in _children(n) if isinstance(c, dict)]
        w.write(" | ".join(_cell_text(c, fmt) for c in cells))
    elif t in ("bulletList", "orderedList"):
        start = a.get("order", 1) if t == "orderedList" else None
        for i, item in enumerate(_children(n)):
            marker = "- " if start is None else "%d. " % (int(start or 1) + i)
            _render_list_item(item, w, fmt, depth, marker)
    elif t == "listItem":
        _render_list_item(n, w, fmt, depth, "- ")
    elif t == "taskItem":
        _render_list_item(n, w, fmt, depth,
                          "[x] " if str(a.get("state", "")).upper() == "DONE" else "[ ] ")
    else:
        # paragraph, heading, blockquote, codeBlock, panel, table, taskList, ...
        _render_children(n, w, fmt, depth)
    w.newline()


def _render_list_item(item: Any, w: _Writer, fmt, depth: int, marker: str) -> None:
    if not isinstance(item, dict):
        return
    if item.get("type") not in ("listItem", "taskItem", None):
        _render(item, w, fmt, depth)
        return
    w.newline()
    w.prefix("  " * depth + marker)
    before = len(w.parts)
    for c in _children(item):
        # Nested lists inside an item are indented one level deeper.
        _render(c, w, fmt, depth + 1 if isinstance(c, dict) and c.get("type") in (
            "bulletList", "orderedList", "taskList") else depth)
    if len(w.parts) == before:
        w.write("\n")  # empty item: still terminate the line
    w.newline()


def cards(doc: Any) -> list[dict]:
    """Every card and link in document order.

    Returns ``{"type": <inlineCard|blockCard|embedCard>, "url": ...}`` for card
    nodes and ``{"type": "link", "url": href, "text": ...}`` for text nodes that
    carry a ``link`` mark.
    """
    out = []
    for n in iter_nodes(doc):
        t = n.get("type")
        if t in CARD_TYPES:
            out.append({"type": t, "url": _card_url(n.get("attrs"))})
        elif t == "text":
            for m in n.get("marks") or []:
                if isinstance(m, dict) and m.get("type") == "link":
                    href = (m.get("attrs") or {}).get("href", "")
                    out.append({"type": "link", "url": href, "text": n.get("text", "")})
    return out


def _table_rows(table: dict) -> list[list[dict]]:
    rows = []
    for tr in _children(table):
        if isinstance(tr, dict) and tr.get("type") == "tableRow":
            rows.append([c for c in _children(tr)
                         if isinstance(c, dict) and c.get("type") in ("tableCell", "tableHeader")])
    return rows


def cell_text(cell: Any) -> str:
    """Text of one table cell (via to_text), stripped. Internal newlines kept."""
    return to_text(_children(cell) if isinstance(cell, dict) else cell).strip()


def tables(doc: Any) -> list[list[list[str]]]:
    """All tables (nested ones included, separately) as rows of cell text."""
    return [[[cell_text(c) for c in row] for row in _table_rows(t)]
            for t in iter_nodes(doc) if t.get("type") == "table"]


def _default_match(cell: str, label: str) -> bool:
    # Casefold equality, with whitespace (including no-break spaces) collapsed.
    return " ".join(cell.split()).casefold() == " ".join(label.split()).casefold()


def row_value(doc: Any, label: str, *, match: Callable[[str, str], bool] | None = None,
              nodes: bool = False) -> list:
    """Values of every table row whose label cell matches ``label``.

    The label may sit in column 0 or column 1; the values are all cells after
    it. Default matching is casefold equality after whitespace collapse; pass
    ``match(cell_text, label) -> bool`` for anything looser (e.g. a trailing
    colon). With ``nodes=True`` each value is ``(text, cell_node)`` so callers
    can run ``cards(cell_node)`` to recover links that the text alone hides.
    """
    match = match or _default_match
    out: list = []
    for t in iter_nodes(doc):
        if t.get("type") != "table":
            continue
        for row in _table_rows(t):
            for li in (0, 1):
                if li < len(row) and match(cell_text(row[li]), label):
                    for c in row[li + 1:]:
                        out.append((cell_text(c), c) if nodes else cell_text(c))
                    break
    return out


def find_adf(obj: Any) -> list[dict]:
    """Every ADF document (a dict with ``type == "doc"``) anywhere inside ``obj``.

    Recurses through dicts and lists, and decodes strings that look like JSON,
    because API and tool responses routinely carry the ADF body as a JSON
    string inside JSON. Documents are returned in encounter order and are not
    searched internally (ADF does not nest documents).
    """
    out: list[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if o.get("type") == "doc":
                out.append(o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            s = o.lstrip()
            # '"doc"' for a JSON string; 'doc\' for one nested inside another,
            # where the quotes arrive escaped (\"doc\", \\\"doc\\\", ...).
            if s[:1] in ("{", "[") and ('"doc"' in s or 'doc\\' in s):
                try:
                    walk(json.loads(s))
                except ValueError:
                    pass

    walk(obj)
    return out
