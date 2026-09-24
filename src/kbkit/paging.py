"""Pagination helpers that refuse to undercount silently.

Bug classes this module exists to prevent:

* Cursor corruption. A cursor taken raw from ``_links.next`` is still
  URL-encoded; sending it back re-encodes it (``%3D`` -> ``%253D``) and the
  server starts over or rejects it. ``next_cursor`` URL-unquotes it.
* The silent offset cap. Some APIs, past a hard maximum offset, return an
  EMPTY page with ``total == 0`` instead of an error. A normal paging loop reads
  that as "end of data" and reports a partial listing as complete.
  ``offset_pages`` raises ``PageCapReached`` instead.
* Stopping early on a short page when the server's page size is smaller than
  the one requested but the reported total says more rows exist.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import unquote

__all__ = ["next_cursor", "offset_pages", "PageCapReached"]


def next_cursor(resp: Any, *, param: str = "cursor") -> str | None:
    """The ``param`` query value from ``resp["_links"]["next"]``, URL-unquoted.

    None if there is no next link or it carries no such parameter. Uses
    ``unquote`` (not ``unquote_plus``): a literal ``+`` in a base64 cursor is
    data, not a space.
    """
    links = resp.get("_links") if isinstance(resp, dict) else None
    nxt = links.get("next") if isinstance(links, dict) else None
    if not isinstance(nxt, str) or not nxt:
        return None
    m = re.search(r"[?&]" + re.escape(param) + r"=([^&#]*)", nxt)
    return unquote(m.group(1)) if m else None


class PageCapReached(Exception):
    """Paging stopped at a limit, not at the end of the data.

    Attributes: ``offset`` (where it stopped), ``items_seen`` (how many items
    were yielded before stopping), ``reason`` (short machine-readable string).
    """

    def __init__(self, offset: int, items_seen: int, reason: str) -> None:
        self.offset = offset
        self.items_seen = items_seen
        self.reason = reason
        super().__init__("paging stopped at offset %d after %d items: %s"
                         % (offset, items_seen, reason))


def offset_pages(fetch: Callable[[int, int], tuple[Iterable, int | None]], *,
                 page_size: int, start: int = 0,
                 max_offset: int | None = None) -> Iterator[Any]:
    """Yield every item from an offset/limit API.

    ``fetch(offset, limit)`` must return ``(items, total_or_None)``.

    Stops normally when a page is shorter than ``page_size``, or when
    ``offset`` reaches a reported total. Raises ``PageCapReached`` when:

    * ``max_offset`` is set and the next request would start at or beyond it
      while the data is not known to be exhausted (reason ``"max_offset"``);
    * a page comes back empty with total 0 AFTER earlier pages returned items
      (reason ``"empty_page_total_zero"``). This is the silent-cap signature:
      some APIs answer past a hard offset with an empty page and a zeroed total
      rather than an error, and a normal loop would treat it as the end of the
      data and silently undercount;
    * a short page arrives while the reported total says more items remain
      (reason ``"short_page_below_total"``).

    Items already yielded stay yielded; catch the exception to report the
    listing as partial, with its denominator unknown.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    offset, seen = start, 0
    while True:
        if max_offset is not None and offset >= max_offset:
            raise PageCapReached(offset, seen, "max_offset")
        items, total = fetch(offset, page_size)
        items = list(items or [])
        if not items and total == 0 and seen > 0:
            raise PageCapReached(offset, seen, "empty_page_total_zero")
        yield from items
        seen += len(items)
        offset += len(items)
        if total is not None and offset >= total:
            return
        if len(items) < page_size:
            if total is not None and offset < total:
                raise PageCapReached(offset, seen, "short_page_below_total")
            return
