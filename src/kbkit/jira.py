"""Generic Jira field helpers.

Bug classes this module exists to prevent:

* Plain-string descriptions reported as missing. Jira API v3 returns ADF; v2
  and wiki-markup paths return a string. A renderer that only understands ADF
  reports a real description as empty. ``description_text`` handles both.
* Cascading selects losing their child. ``{"value": "A", "child": {"value":
  "B"}}`` is "A > B", not "A".
* Silent truncation inside a flattener. Nothing here truncates; callers do.
* Case mismatches in issue-key scans. Keys in URL slugs are often lowercased;
  ``issue_keys(..., ignore_case=True)`` finds them and returns them uppercased.
* Inventing epics from a body-wide key scan. A release-note page that lists one
  epic and its 21 stories yields 22 keys, and the generic key shape also
  matches error codes such as ``ABC-001``. ``epic_keys`` reads only the page's
  Jira Epic row, or failing that its ``Epic:`` line, and says which it used.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from . import adf, htmltext

__all__ = ["ISSUE_KEY", "issue_keys", "epic_keys", "field_text", "description_text"]

ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_ISSUE_KEY_I = re.compile(r"\b[A-Za-z][A-Za-z0-9]+-\d+\b")


def issue_keys(text: str, *, projects: Iterable[str] | None = None,
               ignore_case: bool = False) -> list[str]:
    """Unique issue keys in ``text``, in first-seen order.

    ``projects`` restricts to the given project prefixes (e.g. ``["PROJ"]``).
    ``ignore_case=True`` also matches lowercase keys (as found in slugs and
    URLs) and returns them uppercased.
    """
    if not text:
        return []
    allowed = {p.upper() for p in projects} if projects is not None else None
    rx = _ISSUE_KEY_I if ignore_case else ISSUE_KEY
    seen: dict[str, None] = {}
    for m in rx.finditer(text):
        k = m.group(0).upper() if ignore_case else m.group(0)
        if allowed is not None and k.rsplit("-", 1)[0] not in allowed:
            continue
        seen.setdefault(k, None)
    return list(seen)


def field_text(value: Any) -> str:
    """Flatten any Jira field value to text.

    None -> ""; str as is; numbers and bools via str(); lists joined with ", "
    (empty items dropped); an ADF doc via ``adf.to_text`` (stripped); a
    cascading select ``{"value", "child": {...}}`` -> "parent > child"; other
    dicts -> the first string among value / name / displayName / key / text;
    anything else -> compact JSON so nothing is silently lost.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(s for s in (field_text(x) for x in value) if s)
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return adf.to_text(value).strip()
        child = value.get("child")
        if isinstance(child, dict) and "value" in value:
            parent = field_text(value.get("value"))
            sub = field_text(child) if child.get("value") is not None else ""
            return "%s > %s" % (parent, sub) if sub else parent
        for k in ("value", "name", "displayName", "key", "text"):
            v = value.get(k)
            if isinstance(v, str):
                return v
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def description_text(fields: dict) -> str:
    """Description text from an issue's ``fields`` (or the issue itself).

    Handles ADF (API v3), plain/wiki strings (API v2), and ADF delivered as a
    JSON string. Returns "" only when the description is genuinely absent or
    blank.
    """
    if not isinstance(fields, dict):
        return ""
    if "description" not in fields and isinstance(fields.get("fields"), dict):
        fields = fields["fields"]
    d = fields.get("description")
    if isinstance(d, str):
        s = d.strip()
        if s.startswith("{") and '"doc"' in s:
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("type") == "doc":
                return adf.to_text(parsed).strip()
        return s
    return field_text(d).strip()


# "Jira Epic", "JIRA Epic Link", "Jira epic(s):". A prefix, so trailing words and
# colons still match; the label sits in cell 0 or cell 1 (a Row | Field | Content
# table puts it in 1).
_EPIC_LABEL = re.compile(r"^\s*jira\s*epic", re.I)
# The fallback some templates use instead of a table row: a line "Epic: KEY" or
# "Epic ID: KEY" in a paragraph or heading.
_EPIC_LINE = re.compile(r"^\s*epic(?:\s*id)?\s*:(.*)$", re.I | re.M)


def _adf_blocks_outside_tables(n: Any) -> Iterable[dict]:
    if isinstance(n, list):
        for x in n:
            yield from _adf_blocks_outside_tables(x)
    elif isinstance(n, dict):
        t = n.get("type")
        if t == "table":
            return
        if t in ("paragraph", "heading"):
            yield n
            return
        yield from _adf_blocks_outside_tables(n.get("content"))


def epic_keys(doc: Any, *, projects: Iterable[str] | None = None) -> tuple[list[str], str | None]:
    """The epic key(s) a page or article declares for itself, and where they came from.

    ``doc`` is ADF (a doc dict, or JSON text of one) or an HTML string. Returns
    ``(keys, source)``:

    * ``source == "row"``: a table row labelled Jira Epic (cell 0 or 1). Keys
      come from the NEXT cell only: its text, its cards, and its link targets,
      so plain-text keys, inlineCards and links labelled with a summary all
      count.
    * ``source == "line"``: no such row; an ``Epic:`` / ``Epic ID:`` line in a
      paragraph or heading outside any table.
    * ``source is None``: neither was found.

    An EMPTY ``keys`` list means UNMEASURED, never "this page has no epic",
    whatever ``source`` says: an epic cell that reads empty usually means the
    reader missed a form. There is deliberately no fallback to scanning the
    whole body. Pass ``projects`` (e.g. ``["PROJ"]``) to ignore key-shaped
    strings from other prefixes.
    """
    def keys_of(*texts: str) -> list[str]:
        return issue_keys(" ".join(t for t in texts if t), projects=projects)

    if isinstance(doc, str) and not doc.lstrip().startswith(("{", "[")):
        rows = [[(c["text"], c["hrefs"]) for c in row] for row in htmltext.table_rows(doc)]
        lines = htmltext.text_outside_tables(doc)
    else:
        found = adf.find_adf(doc) if not (isinstance(doc, dict) and doc.get("type") == "doc") else [doc]
        if not found:
            return [], None
        root = found[0]
        rows = []
        for t in adf.iter_nodes(root):
            if t.get("type") == "table":
                for row in adf._table_rows(t):
                    rows.append([(adf.cell_text(c), [x["url"] for x in adf.cards(c)]) for c in row])
        lines = "\n".join(adf.to_text(b) for b in _adf_blocks_outside_tables(root.get("content")))

    out: dict[str, None] = {}
    matched_row = False
    for row in rows:
        for li in (0, 1):
            if li + 1 < len(row) and _EPIC_LABEL.match(row[li][0]):
                matched_row = True
                text, hrefs = row[li + 1]
                for k in keys_of(text, *hrefs):
                    out.setdefault(k, None)
                break
    if matched_row:
        return list(out), "row"
    hits = [m.group(1) for m in _EPIC_LINE.finditer(lines)]
    if hits:
        return keys_of(*hits), "line"
    return [], None
