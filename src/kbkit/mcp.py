"""Reading MCP tool results that Claude Code has already written to disk.

Claude Code records every tool call in transcript files (``*.jsonl``, one JSON
record per line) and spills large results to ``tool-results/*.txt``. Those are
the bytes the tool returned, so they can be re-read without calling the API
again.

Bug classes this module exists to prevent:

* Keeping only the first content part. An MCP result is a list of parts; code
  that reads ``parts[0]["text"]`` silently drops the rest. ``unwrap`` joins all
  text parts.
* Loading multi-hundred-megabyte transcripts into memory. ``iter_tool_results``
  streams ``*.jsonl`` line by line.
* Mistaking a truncated copy for the real thing. The harness elides large
  results; a truncated body looks like a mid-body deletion. ``pick`` discards
  truncated copies whenever a complete copy of the same key exists.
* Unstated "which copy wins". The same object is often captured many times
  (before and after an edit, from different queries). ``pick`` makes the
  choice an explicit policy.
"""
from __future__ import annotations

import json
import re
import os
from typing import Any, Callable, Hashable, Iterable, Iterator

__all__ = ["unwrap", "result_text", "iter_tool_results", "pick", "TRUNCATION_MARKERS"]

# Substrings the harness inserts when it elides a large result. The last two are
# spill notices that could not be followed: the transcript holds only a notice
# or a 2KB preview, so that copy is as good as truncated.
TRUNCATION_MARKERS = ("[truncated", "\u2026 +", "...(truncated", "<response clipped>",
                      "[Result too long", "<persisted-output>",
                      "exceeds maximum allowed tokens")

_PART_TYPES = {"text", "image", "audio", "resource", "resource_link"}


def _is_parts(x: Any) -> bool:
    """True for an MCP content-part list: [{"type": "text", "text": ...}, ...]."""
    if not isinstance(x, list) or not x:
        return False
    if not all(isinstance(p, dict) and p.get("type") in _PART_TYPES and "marks" not in p
               for p in x):
        return False
    return any(p.get("type") == "text" and isinstance(p.get("text"), str) for p in x)


def result_text(result: Any) -> str:
    """The raw text of a result, all text parts joined, without JSON decoding."""
    if isinstance(result, str):
        return result
    if isinstance(result, bytes):
        return result.decode("utf-8", "replace")
    if isinstance(result, dict) and _is_parts(result.get("content")):
        result = result["content"]
    if _is_parts(result):
        return "".join(p.get("text", "") for p in result if p.get("type") == "text")
    return json.dumps(result, ensure_ascii=False)


def _maybe_json(s: str) -> Any:
    t = s.strip()
    if t[:1] in ("{", "[", '"') or t in ("null", "true", "false") or t[:1].isdigit():
        try:
            return json.loads(t)
        except ValueError:
            pass
    return s


def unwrap(result: Any, *, envelope: bool = False) -> Any:
    """Turn a tool result into a Python object.

    Accepts a content-part list (ALL text parts are joined, not just the
    first), a dict with ``content`` holding such parts, a raw JSON string, or an
    already-decoded object. The joined text is JSON-decoded if it parses,
    otherwise returned as text. JSON that decodes to another JSON string or
    part list is unwrapped again (up to a few levels).

    ``envelope=True`` additionally strips ONE level of ``{"data": ...}`` or
    ``{"result": ...}``. It is off by default because real payloads use those
    key names too, and unwrapping them blindly discards sibling fields.
    """
    obj = result
    for _ in range(4):
        if isinstance(obj, bytes):
            obj = obj.decode("utf-8", "replace")
        if isinstance(obj, dict) and _is_parts(obj.get("content")):
            obj = obj["content"]
        if _is_parts(obj):
            obj = result_text(obj)
        if isinstance(obj, str):
            new = _maybe_json(obj)
            if new is obj or new == obj:
                break
            obj = new
            continue
        break
    if envelope and isinstance(obj, dict):
        for k in ("data", "result"):
            if k in obj:
                inner = obj[k]
                return _maybe_json(inner) if isinstance(inner, str) else inner
    return obj


def _walk_files(root: str) -> Iterator[str]:
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            yield os.path.join(d, f)


def iter_tool_results(root: str, *, tool: str | None = None,
                      follow_spills: bool = True) -> Iterator[dict]:
    """Yield one record per tool result found under ``root``.

    Records are dicts with keys ``path, mtime, line, timestamp, tool_name,
    tool_use_id, input, result, is_error, spill_path``.

    A result too large for the transcript is recorded there only as a notice
    ("... Output has been saved to <path>.txt ..."), with the body in a spill
    file. With ``follow_spills`` (the default) that notice is replaced by the
    spill file's text and ``spill_path`` says where it came from, so the
    largest results, often the ones that matter, keep their tool name and
    input. The recorded path is absolute to the machine that wrote it; if it
    does not exist, the same file name is tried under ``tool-results/`` beside
    and above the transcript. If no file is found the notice is left as the
    result and ``spill_path`` is None: check for it rather than parsing an
    error string as content.

    * ``**/*.jsonl`` transcripts: assistant lines carry ``message.content`` items
      ``{"type": "tool_use", "id", "name", "input"}``; user lines carry
      ``{"type": "tool_result", "tool_use_id", "content"}``. Uses are paired
      with results by id within the same file. A result whose use is not in
      the file is still yielded, with ``tool_name`` None. Malformed lines are
      skipped. Files are streamed, never read whole.
    * ``**/tool-results/*.txt`` spill files: one record per file, ``result`` is
      the file text, ``tool_name`` / ``tool_use_id`` / ``input`` are None.

    ``result`` is left raw (usually a part list or string); pass it to
    ``unwrap``. ``tool`` filters by substring of the tool name; spill files have
    no recorded tool name, so for them ``tool`` is matched against the file
    name (the harness names spills after the tool, with ``-`` for ``__``).
    """
    for path in _walk_files(root):
        name = os.path.basename(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if name.endswith(".jsonl"):
            yield from _from_jsonl(path, mtime, tool, follow_spills)
        elif name.endswith(".txt") and os.path.basename(os.path.dirname(path)) == "tool-results":
            if tool is not None and tool not in name and tool.replace("__", "-") not in name:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            yield {"path": path, "mtime": mtime, "line": 0, "timestamp": None,
                   "tool_name": None, "tool_use_id": None, "input": None,
                   "result": text, "is_error": None, "spill_path": path}


# The two phrasings the harness writes:
#   "Error: result (N characters) exceeds maximum allowed tokens. Output has been saved to <path>"
#   "<persisted-output>\nOutput too large (N KB). Full output saved to: <path>\n\nPreview ..."
# Anchored on those phrases so ordinary text that says "saved to x.txt" is not
# followed. The path runs to the first ".txt" on the line, not \S+, so a path
# with spaces (OneDrive folders) matches.
_SPILL_NOTICE = re.compile(r"(?:Output has been saved to|Full output saved to:)\s*([^\r\n]+?\.txt)")


def _resolve_spill(transcript: str, text: str) -> str | None:
    m = _SPILL_NOTICE.search(text[:2000])
    if not m:
        return None
    recorded = m.group(1)
    if os.path.isfile(recorded):
        return recorded
    base = os.path.basename(recorded.replace("\\", "/"))
    d = os.path.dirname(transcript)
    for _ in range(3):  # transcript dir, its parent (subagents/), grandparent
        cand = os.path.join(d, "tool-results", base)
        if os.path.isfile(cand):
            return cand
        d = os.path.dirname(d)
    return None


def _from_jsonl(path: str, mtime: float, tool: str | None,
                follow_spills: bool = True) -> Iterator[dict]:
    pending: dict[str, tuple[str, Any]] = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for ln, line in enumerate(fh, 1):
            # Cheap pre-filter before paying for json.loads on every line.
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use" and isinstance(item.get("id"), str):
                    pending[item["id"]] = (item.get("name"), item.get("input"))
                elif item.get("type") == "tool_result":
                    tid = item.get("tool_use_id")
                    name, inp = pending.pop(tid, (None, None))
                    if tool is not None and (name is None or tool not in name):
                        continue
                    result, spill = item.get("content"), None
                    if follow_spills:
                        spill = _resolve_spill(path, result_text(result))
                        if spill:
                            try:
                                with open(spill, encoding="utf-8", errors="replace") as sf:
                                    result = sf.read()
                            except OSError:
                                spill = None
                    yield {"path": path, "mtime": mtime, "line": ln,
                           "timestamp": rec.get("timestamp"), "tool_name": name,
                           "tool_use_id": tid, "input": inp,
                           "result": result, "is_error": item.get("is_error"),
                           "spill_path": spill}


def _truncated(rec: dict, markers: Iterable[str]) -> bool:
    text = result_text(rec.get("result"))
    return any(m in text for m in markers)


def pick(records: Iterable[dict], key: Callable[[dict], Hashable | None], *,
         policy: str,
         markers: Iterable[str] = TRUNCATION_MARKERS) -> dict:
    """Choose one record per key.

    ``key(record)`` returns the grouping key, or None to skip the record.
    Use that to drop failed calls: "newest" will otherwise choose a sign-in
    error over an older good read, e.g. ``key=lambda r: None if r["is_error"]
    or not isinstance(unwrap(r["result"]), dict) else r["input"]["id"]``.

    THE POLICY CHANGES THE ANSWER, so it is explicit:

    * ``"newest"`` - latest (mtime, line). Right when the object changes over
      time (a read after a write must beat the read before it).
    * ``"longest"`` - longest result text. Right when copies differ only in how
      much was captured (partial listings, excerpts).

    Within each key, copies whose text contains a truncation marker are
    discarded if at least one untruncated copy exists; the policy then chooses
    among the survivors. Returned records are shallow copies with an added
    ``"truncated"`` flag, which is True only when every copy was truncated.
    """
    if policy not in ("newest", "longest"):
        raise ValueError("policy must be 'newest' or 'longest'")
    markers = tuple(markers)
    groups: dict = {}
    for r in records:
        k = key(r)
        if k is not None:
            groups.setdefault(k, []).append(r)
    out = {}
    for k, recs in groups.items():
        flagged = [(r, _truncated(r, markers)) for r in recs]
        complete = [r for r, t in flagged if not t]
        pool = complete or recs
        if policy == "newest":
            best = max(pool, key=lambda r: (r.get("mtime") or 0, r.get("line") or 0))
        else:
            best = max(pool, key=lambda r: len(result_text(r.get("result"))))
        chosen = dict(best)
        chosen["truncated"] = not complete
        out[k] = chosen
    return out
