"""Term-list matching with honest reporting.

Bug classes this module exists to prevent:

* Substring matching. ``"Scan" in text`` matches "Scanned" and "Scanner".
  Terms here match on word boundaries only (``(?<!\\w)`` / ``(?!\\w)``, which
  also works for terms that start or end with punctuation).
* Case-sensitive misses. Matching is case-insensitive unless asked otherwise.
* Shorter terms shadowing longer ones. "Acme" must not win over "Acme Health"
  at the same position; alternatives are tried longest first.
* Reading "no hits" as "clean". A term list is evidence about the names ON
  THE LIST, never proof that no other names are present. The report object
  deliberately has no ``clean`` / ``is_clean`` attribute.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping

__all__ = ["TermList", "TermReport"]


def _canon(s: str) -> str:
    return " ".join(s.split())


class TermList:
    """A fixed list of terms, matched on word boundaries.

    Whitespace inside a term matches any run of whitespace (so a term still
    matches across a line break or a no-break space).
    """

    def __init__(self, terms: Iterable[str], *, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive
        self.terms: list[str] = []
        self._lookup: dict[str, str] = {}
        for t in terms:
            t = _canon(t or "")
            k = self._key(t)
            if t and k not in self._lookup:
                self._lookup[k] = t
                self.terms.append(t)
        alts = sorted(self.terms, key=len, reverse=True)
        body = "|".join(r"\s+".join(re.escape(w) for w in t.split()) for t in alts)
        flags = 0 if case_sensitive else re.IGNORECASE
        self._rx = re.compile(r"(?<!\w)(?:%s)(?!\w)" % body, flags) if alts else None

    def _key(self, s: str) -> str:
        s = _canon(s)
        return s if self.case_sensitive else s.casefold()

    def find(self, text: str) -> list[tuple[str, int, int]]:
        """``(listed_term, start, end)`` for every match, left to right."""
        if not self._rx or not text:
            return []
        return [(self._lookup.get(self._key(m.group(0)), m.group(0)), m.start(), m.end())
                for m in self._rx.finditer(text)]

    def report(self, texts: Iterable[str] | Mapping[object, str]) -> "TermReport":
        """Scan many texts. ``texts`` may be a list (ids are indexes) or a mapping."""
        items = texts.items() if isinstance(texts, Mapping) else enumerate(texts)
        per_text: dict = {}
        scanned = 0
        for ident, text in items:
            scanned += 1
            hits = self.find(text or "")
            if hits:
                per_text[ident] = hits
        return TermReport(len(self.terms), scanned, per_text)


class TermReport:
    """Result of ``TermList.report``.

    A list is evidence about the names on the list, never proof of absence:
    zero hits means none of THESE terms appeared, not that the texts are free
    of names. There is intentionally no ``clean`` / ``is_clean`` attribute;
    ``__slots__`` stops one being bolted on.

    Attributes: ``terms_listed``, ``texts_scanned``, ``per_text`` (id -> hits),
    ``counts`` (term -> occurrences), ``terms_found`` (sorted list).
    """

    __slots__ = ("terms_listed", "texts_scanned", "per_text", "counts")

    def __init__(self, terms_listed: int, texts_scanned: int, per_text: dict) -> None:
        self.terms_listed = terms_listed
        self.texts_scanned = texts_scanned
        self.per_text = per_text
        counts: dict[str, int] = {}
        for hits in per_text.values():
            for term, _s, _e in hits:
                counts[term] = counts.get(term, 0) + 1
        self.counts = counts

    @property
    def terms_found(self) -> list[str]:
        return sorted(self.counts)

    @property
    def texts_with_hits(self) -> int:
        return len(self.per_text)

    def __str__(self) -> str:
        return "%d listed terms found in %d of %d texts" % (
            len(self.counts), self.texts_with_hits, self.texts_scanned)

    def __repr__(self) -> str:
        return "<TermReport %s (%d terms listed)>" % (self, self.terms_listed)
