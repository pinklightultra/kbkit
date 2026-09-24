"""Small text I/O helpers.

Bug classes this module exists to prevent:

* UnicodeEncodeError on a cp1252 console the moment output contains a
  non-ASCII character (``utf8_stdout``).
* A BOM leaking into the first line, or a hard crash on a legacy-encoded file
  (``read_text``).
* Reports that exist only in scrollback (``Tee`` writes the file as well).
"""
from __future__ import annotations

import os
import sys
from typing import Any

__all__ = ["read_text", "utf8_stdout", "Tee"]


def read_text(path: "str | os.PathLike") -> str:
    """Read a text file as UTF-8 (BOM stripped), falling back to cp1252.

    The cp1252 fallback uses errors="replace", because five byte values are
    undefined in cp1252 and a reader should not crash on them.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def utf8_stdout() -> None:
    """Reconfigure stdout and stderr to UTF-8 with errors="replace".

    Safe to call repeatedly, and a no-op for streams that cannot be
    reconfigured (e.g. when output is captured by a test runner).
    """
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


class Tee:
    """Write lines to a UTF-8 file and echo them to stdout.

    >>> with Tee("report.txt") as out:      # doctest: +SKIP
    ...     out("rows:", 3)
    ...     out.write("raw text\\n")

    ``out(*args)`` behaves like ``print``. Echoing never raises on an
    unencodable character; the file always receives the exact text.
    """

    def __init__(self, path: "str | os.PathLike", mode: str = "w") -> None:
        self.path = path
        self.mode = mode
        self._fh = None

    def __enter__(self) -> "Tee":
        self._fh = open(self.path, self.mode, encoding="utf-8")
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, s: str) -> None:
        if self._fh is None:
            raise ValueError("Tee is not open; use it as a context manager")
        self._fh.write(s)
        try:
            sys.stdout.write(s)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            sys.stdout.write(s.encode(enc, "replace").decode(enc, "replace"))

    def __call__(self, *args: Any, sep: str = " ", end: str = "\n") -> None:
        self.write(sep.join(str(a) for a in args) + end)
