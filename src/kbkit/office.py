"""Text out of .docx and .xlsx attachments, standard library only.

Bug classes this module exists to prevent:

* Losing tracked deletions, tabs, breaks, symbols and checkbox state. A reader
  that only collects ``w:t`` turns a ticked form into an unticked one and drops
  text a reviewer deleted. ``docx_text`` renders all of them.
* Reading only the body. Headers, footers, footnotes, endnotes and comments are
  separate parts of the package and often carry the version or the caveat.
* Skipping hidden worksheets. ``xlsx_rows`` returns every sheet;
  ``xlsx_sheets`` reports which are hidden, so the caller decides.
* Column drift. Cells are placed by their ``r`` reference, so a blank cell does
  not shift the rest of the row left.
"""
from __future__ import annotations

import io
import os
import posixpath
import re
import zipfile
from typing import Union
from xml.etree import ElementTree as ET

__all__ = ["docx_parts", "docx_text", "xlsx_sheets", "xlsx_rows"]

Source = Union[str, bytes, os.PathLike]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _zip(src: Source) -> zipfile.ZipFile:
    if isinstance(src, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(bytes(src)))
    return zipfile.ZipFile(src)


# ---------------------------------------------------------------- docx

_PART_ORDER = [
    ("document", re.compile(r"word/document\.xml$")),
    ("header", re.compile(r"word/header\d*\.xml$")),
    ("footer", re.compile(r"word/footer\d*\.xml$")),
    ("footnotes", re.compile(r"word/footnotes\.xml$")),
    ("endnotes", re.compile(r"word/endnotes\.xml$")),
    ("comments", re.compile(r"word/comments\.xml$")),
]


def _on(el: ET.Element, attr: str) -> bool:
    """OOXML on/off value: absent val means on; "0"/"false"/"off" mean off."""
    v = el.get(attr)
    return v is None or v.lower() not in ("0", "false", "off")


def _legacy_checkbox(cb: ET.Element) -> bool:
    checked = cb.find(W + "checked")
    if checked is not None:
        return _on(checked, W + "val")
    default = cb.find(W + "default")
    return default is not None and _on(default, W + "val")


def _para_text(p: ET.Element, deleted: str) -> str:
    out = []
    for el in p.iter():
        tag = el.tag
        if tag == W + "t":
            out.append(el.text or "")
        elif tag == W + "delText":
            if deleted == "mark":
                out.append("[deleted: %s]" % (el.text or ""))
            elif deleted == "keep":
                out.append(el.text or "")
        elif tag == W + "tab":
            out.append("\t")
        elif tag in (W + "br", W + "cr"):
            out.append("\n")
        elif tag == W + "sym":
            out.append("[sym:%s]" % (el.get(W + "char") or "?"))
        elif tag == W + "checkBox":  # legacy form field
            out.append("[x]" if _legacy_checkbox(el) else "[ ]")
        elif tag == W14 + "checkbox":  # content-control checkbox
            c = el.find(W14 + "checked")
            out.append("[x]" if c is not None and _on(c, W14 + "val") else "[ ]")
    return "".join(out)


def _block_lines(node: ET.Element, deleted: str) -> list[str]:
    lines: list[str] = []
    for ch in node:
        if ch.tag == W + "p":
            t = _para_text(ch, deleted)
            if t.strip():
                lines.append(t)
        elif ch.tag == W + "tbl":
            for tr in ch.findall(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    paras = (_para_text(p, deleted) for p in tc.iter(W + "p"))
                    cells.append(" / ".join(t.strip() for t in paras if t.strip()))
                if any(cells):
                    lines.append(" | ".join(cells))
        elif ch.tag == W + "sdt":
            # Block-level content control. A checkbox's state lives in sdtPr,
            # which holds no paragraph, so it must be read here explicitly.
            cb = ch.find(W + "sdtPr/" + W14 + "checkbox")
            content = ch.find(W + "sdtContent")
            inner = _block_lines(content, deleted) if content is not None else []
            if cb is not None:
                c = cb.find(W14 + "checked")
                mark = "[x]" if c is not None and _on(c, W14 + "val") else "[ ]"
                inner = [mark + (inner[0] if inner else "")] + inner[1:]
            lines.extend(inner)
        else:
            lines.extend(_block_lines(ch, deleted))  # body, customXml, ...
    return lines


def docx_parts(src: Source, *, deleted: str = "mark") -> dict[str, str]:
    """Text of each textual part, keyed by zip member name, in reading order:
    document, headers, footers, footnotes, endnotes, comments.

    ``deleted`` controls tracked deletions: ``"mark"`` (default) renders
    ``[deleted: text]``, ``"keep"`` inlines the text, ``"drop"`` omits it.
    Checkboxes render as ``[x]`` / ``[ ]``, symbols as ``[sym:F0FC]``.
    """
    if deleted not in ("mark", "keep", "drop"):
        raise ValueError("deleted must be 'mark', 'keep' or 'drop'")
    out: dict[str, str] = {}
    with _zip(src) as z:
        names = z.namelist()
        for _label, rx in _PART_ORDER:
            for name in sorted(n for n in names if rx.match(n)):
                root = ET.fromstring(z.read(name))
                out[name] = "\n".join(_block_lines(root, deleted))
    return out


def docx_text(src: Source, *, deleted: str = "mark") -> str:
    """All text of a .docx (path or bytes): body first, then the other parts,
    separated by blank lines. See ``docx_parts`` for the rendering rules."""
    return "\n\n".join(t for t in docx_parts(src, deleted=deleted).values() if t)


# ---------------------------------------------------------------- xlsx

def _workbook(z: zipfile.ZipFile) -> list[dict]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    try:
        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels = {r.get("Id"): r.get("Target") for r in rels_root.iter(PKG_REL + "Relationship")}
    except KeyError:
        rels = {}
    sheets = []
    for s in wb.iter(S + "sheet"):
        target = rels.get(s.get(R_ID), "")
        if target.startswith("/"):
            part = target.lstrip("/")
        else:
            part = posixpath.normpath(posixpath.join("xl", target)) if target else ""
        sheets.append({"name": s.get("name"), "state": s.get("state") or "visible",
                       "part": part})
    return sheets


def _si_text(si: ET.Element) -> str:
    # Direct <t>, or rich-text runs <r><t>. Phonetic runs (<rPh>) are skipped.
    parts = []
    for ch in si:
        if ch.tag == S + "t":
            parts.append(ch.text or "")
        elif ch.tag == S + "r":
            parts.extend(t.text or "" for t in ch.iter(S + "t"))
    return "".join(parts)


def _shared(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_si_text(si) for si in root.iter(S + "si")]


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _cell_value(c: ET.Element, shared: list[str]) -> str:
    t = c.get("t")
    v = c.find(S + "v")
    if t == "inlineStr":
        is_ = c.find(S + "is")
        return _si_text(is_) if is_ is not None else ""
    if v is None or v.text is None:
        return ""
    if t == "s":
        try:
            return shared[int(v.text)]
        except (ValueError, IndexError):
            return ""
    if t == "b":
        return "TRUE" if v.text.strip() == "1" else "FALSE"
    return v.text  # numbers, dates (as serials), formula strings, errors: raw


def xlsx_sheets(src: Source) -> list[dict]:
    """``[{"name", "state"}]`` in workbook order; state is visible/hidden/veryHidden."""
    with _zip(src) as z:
        return [{"name": s["name"], "state": s["state"]} for s in _workbook(z)]


def xlsx_rows(src: Source) -> dict[str, list[list[str]]]:
    """Every sheet (hidden ones included) as rows of cell strings.

    Shared and inline strings are resolved; booleans become TRUE/FALSE; numbers
    and dates stay as stored (dates are serial numbers). Cells and rows are
    placed by their references, so gaps become "" / [] rather than shifting.
    """
    out: dict[str, list[list[str]]] = {}
    with _zip(src) as z:
        shared = _shared(z)
        for s in _workbook(z):
            rows: list[list[str]] = []
            try:
                root = ET.fromstring(z.read(s["part"]))
            except KeyError:
                out[s["name"]] = rows
                continue
            for row in root.iter(S + "row"):
                r = row.get("r")
                ri = int(r) - 1 if r and r.isdigit() else len(rows)
                while len(rows) < ri:
                    rows.append([])
                cells: list[str] = []
                for c in row.iter(S + "c"):
                    ref = c.get("r")
                    ci = _col_index(ref) if ref else len(cells)
                    while len(cells) < ci:
                        cells.append("")
                    cells.append(_cell_value(c, shared))
                if ri < len(rows):
                    rows[ri] = cells
                else:
                    rows.append(cells)
            out[s["name"]] = rows
    return out
