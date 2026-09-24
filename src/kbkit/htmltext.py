"""HTML article text and byte-diff normalisation.

Bug classes this module exists to prevent:

* Double-decoding entities. Hand-rolled replacement that decodes ``&amp;``
  before ``&lt;`` turns the literal text ``&lt;`` (stored as ``&amp;lt;``) into
  ``<``. Entities are decoded exactly once, by the standard library.
* Greedy style stripping. ``<style>.*?</style>\\s*$`` matches from the FIRST
  ``<style>`` to the end, deleting legitimate content in between. Only the
  last style block, and only when it closes the document, is removed.
* Over-broad id stripping. Removing every ``id=`` hides real changes to
  anchors, tables and form fields. Only ids on h1-h6 are removed.
* Asymmetric normalisation. Every option is applied identically to whatever
  string is passed, and both sides of a diff must go through the same call.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

__all__ = ["visible_text", "table_rows", "text_outside_tables", "normalize", "first_diff"]

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "thead", "tbody", "tfoot",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr", "section",
    "article", "header", "footer", "aside", "nav", "dl", "dt", "dd", "figure",
    "figcaption", "caption", "details", "summary", "main", "form", "fieldset",
}
_SKIP_TAGS = {"script", "style"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs=True: the parser decodes entities in text exactly once.
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html: str) -> str:
    """Human-visible text of an HTML fragment.

    script/style content is skipped, entities are decoded once, block tags
    start new lines, runs of whitespace (including U+00A0) collapse to one
    space, and blank lines are dropped.
    """
    p = _TextParser()
    p.feed(html)
    p.close()
    lines = (" ".join(line.split()) for line in "".join(p.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def _collapse(s: str) -> str:
    lines = (" ".join(line.split()) for line in s.split("\n"))
    return "\n".join(line for line in lines if line)


class _TableParser(_TextParser):
    """Rows of every table (nested tables separately), plus text outside tables."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self.stack: list[dict] = []  # one frame per open <table>
        self.outside: list[str] = []

    def _sink(self) -> list[str]:
        if self.stack and self.stack[-1]["cell"] is not None:
            return self.stack[-1]["cell"]["parts"]
        return self.outside if not self.stack else []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"row": None, "cell": None})
            return
        f = self.stack[-1] if self.stack else None
        if f is not None and tag == "tr":
            f["row"] = []
            self.rows.append(f["row"])
        elif f is not None and tag in ("td", "th"):
            if f["row"] is None:  # a cell with no <tr>, which browsers tolerate
                f["row"] = []
                self.rows.append(f["row"])
            f["cell"] = {"parts": [], "hrefs": []}
            f["row"].append(f["cell"])
        if tag == "a" and self.stack and self.stack[-1]["cell"] is not None:
            href = dict(attrs).get("href")
            if href:
                self.stack[-1]["cell"]["hrefs"].append(href)
        self.parts = self._sink()
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "table" and self.stack:
            self.stack.pop()
        elif self.stack and tag in ("td", "th"):
            self.stack[-1]["cell"] = None
        elif self.stack and tag == "tr":
            self.stack[-1]["row"] = None
            self.stack[-1]["cell"] = None
        self.parts = self._sink()


def _parse_tables(html: str) -> _TableParser:
    p = _TableParser()
    p.parts = p.outside
    p.feed(html)
    p.close()
    return p


def table_rows(html: str) -> list[list[dict]]:
    """Every table row in document order, as ``[{"text", "hrefs"}, ...]`` per cell.

    ``text`` is the cell's visible text (as ``visible_text``); ``hrefs`` lists
    the cell's link targets, because a cell labelled with a ticket summary often
    carries the key only in its link. A nested table's rows are listed on their
    own; the outer cell's text does not include them.
    """
    return [[{"text": _collapse("".join(c["parts"])), "hrefs": list(c["hrefs"])}
             for c in row] for row in _parse_tables(html).rows]


def text_outside_tables(html: str) -> str:
    """Visible text of everything that is not inside a table, one block per line."""
    return _collapse("".join(_parse_tables(html).outside))


_NBSP_ENTITY = re.compile(r"&(?:nbsp|#160|#x0*a0);", re.I)
# The last <style> block, only if nothing but whitespace follows it. The
# tempered token (?:(?!</?style\b).)* stops the match from spanning an earlier
# style block, which is the greedy-from-first-style bug.
_TAIL_STYLE = re.compile(r"<style\b[^>]*>(?:(?!</?style\b).)*</style\s*>\s*\Z", re.S | re.I)
_HEADING_TAG = re.compile(r"<h[1-6]\b[^>]*>", re.I)
_ID_ATTR = re.compile(r"""\s+id\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)


def normalize(html: str, *, nbsp: bool = True, strip_tail_style: bool = True,
              heading_ids: bool = True) -> str:
    """Normalise HTML for a byte comparison. Apply to BOTH sides.

    Options (each targets one transform a content store may apply on save):

    * ``nbsp`` - U+00A0 and the entities ``&nbsp;`` / ``&#160;`` / ``&#xa0;``
      become a plain space. ``&amp;nbsp;`` (literal text) is left alone.
    * ``strip_tail_style`` - remove a single ``<style>...</style>`` block only
      when it is the last thing in the document (only whitespace after it).
      Any earlier style block is untouched.
    * ``heading_ids`` - remove ``id="..."`` attributes from h1-h6 start tags
      only. ids on any other element are kept, since changing them is content.

    The result is always ``rstrip()``-ed, identically for every input.

    Prefer checking the precondition (e.g. "the other side holds zero nbsp")
    before relying on a normalisation, so it cannot absorb a real difference.
    """
    s = html
    if strip_tail_style:
        s = _TAIL_STYLE.sub("", s, count=1)
    if heading_ids:
        s = _HEADING_TAG.sub(lambda m: _ID_ATTR.sub("", m.group(0)), s)
    if nbsp:
        s = _NBSP_ENTITY.sub(" ", s.replace("\u00a0", " "))
    return s.rstrip()


def first_diff(a: Any, b: Any, *, context: int = 40) -> dict | None:
    """First position where two strings (or bytes) differ.

    Returns None when equal, else ``{"offset": i, "a": window, "b": window}``
    where each window is the slice ``[i - context, i + context)`` of that side.
    When one side is a prefix of the other, offset is the shorter length.
    """
    if a == b:
        return None
    n = min(len(a), len(b))
    off = next((i for i in range(n) if a[i] != b[i]), n)
    lo = max(0, off - context)
    return {"offset": off, "a": a[lo:off + context], "b": b[lo:off + context]}
