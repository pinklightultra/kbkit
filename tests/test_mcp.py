import json
import os

from kbkit import mcp


def test_unwrap_joins_all_text_parts():
    payload = json.dumps({"items": [1, 2, 3], "name": "Acme"})
    parts = [{"type": "text", "text": payload[:10]}, {"type": "text", "text": payload[10:]}]
    assert mcp.unwrap(parts) == {"items": [1, 2, 3], "name": "Acme"}


def test_unwrap_shapes():
    assert mcp.unwrap({"content": [{"type": "text", "text": "[1, 2]"}], "isError": False}) == [1, 2]
    assert mcp.unwrap('{"a": 1}') == {"a": 1}
    assert mcp.unwrap({"a": 1}) == {"a": 1}
    assert mcp.unwrap([{"type": "text", "text": "plain words"}]) == "plain words"
    # A raw file holding a JSON part list whose text is JSON again.
    raw = json.dumps([{"type": "text", "text": json.dumps({"k": "v"})}])
    assert mcp.unwrap(raw) == {"k": "v"}


def test_unwrap_envelope_only_when_asked():
    wrapped = [{"type": "text", "text": json.dumps({"data": {"id": "x"}, "success": True})}]
    assert mcp.unwrap(wrapped) == {"data": {"id": "x"}, "success": True}
    assert mcp.unwrap(wrapped, envelope=True) == {"id": "x"}


def _line(obj):
    return json.dumps(obj) + "\n"


def test_iter_tool_results_pairs_use_and_result(tmp_path):
    sess = tmp_path / "session"
    (sess / "tool-results").mkdir(parents=True)
    body = json.dumps({"id": "PROJ-123", "title": "Acme"})
    lines = [
        _line({"type": "user", "message": {"role": "user", "content": "hi"}}),
        _line({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "calling"},
            {"type": "tool_use", "id": "toolu_1", "name": "mcp__srv__get-item",
             "input": {"id": "PROJ-123"}}]}}),
        "{this line is not json\n",
        _line({"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {
            "role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1",
                 "content": [{"type": "text", "text": body}]}]}}),
        _line({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {}}]}}),
        _line({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "file text"}]}}),
    ]
    (sess / "t.jsonl").write_text("".join(lines), encoding="utf-8")
    (sess / "tool-results" / "mcp-srv-get-item-1.txt").write_text(body, encoding="utf-8")
    (sess / "notes.txt").write_text("not a spill", encoding="utf-8")

    recs = list(mcp.iter_tool_results(str(tmp_path)))
    assert len(recs) == 3
    j = [r for r in recs if r["tool_use_id"] == "toolu_1"][0]
    assert j["tool_name"] == "mcp__srv__get-item"
    assert j["input"] == {"id": "PROJ-123"}
    assert j["line"] == 4
    assert j["timestamp"] == "2026-01-01T00:00:00Z"
    assert mcp.unwrap(j["result"]) == {"id": "PROJ-123", "title": "Acme"}

    only = list(mcp.iter_tool_results(str(tmp_path), tool="get-item"))
    assert len(only) == 2
    spill = [r for r in only if r["tool_name"] is None][0]
    assert os.path.basename(spill["path"]) == "mcp-srv-get-item-1.txt"
    assert mcp.unwrap(spill["result"])["id"] == "PROJ-123"


def _rec(key, text, mtime, line=1):
    return {"path": "p", "mtime": mtime, "line": line, "tool_name": "x",
            "result": [{"type": "text", "text": json.dumps({"k": key, "t": text})}]}


def test_pick_policies_and_truncation():
    recs = [
        _rec("a", "short", 1),
        _rec("a", "much longer body", 2),
        _rec("a", "mid", 3),
        _rec("a", "x" * 50 + " [truncated 900 chars]", 4),
        _rec("b", "only [truncated", 1),
    ]
    key = lambda r: mcp.unwrap(r["result"])["k"]  # noqa: E731
    newest = mcp.pick(recs, key, policy="newest")
    assert mcp.unwrap(newest["a"]["result"])["t"] == "mid"  # truncated newer copy skipped
    assert newest["a"]["truncated"] is False
    longest = mcp.pick(recs, key, policy="longest")
    assert mcp.unwrap(longest["a"]["result"])["t"] == "much longer body"
    assert newest["b"]["truncated"] is True  # only a truncated copy exists: kept, flagged


def test_pick_skips_none_keys():
    assert mcp.pick([_rec("a", "x", 1)], lambda r: None, policy="newest") == {}


def test_iter_tool_results_follows_spill_notice(tmp_path):
    # Layout as the harness writes it: subagent transcripts one level below the
    # session's tool-results/. The notice names an absolute path from another
    # machine (with spaces), so resolution must fall back to the file name.
    sess = tmp_path / "session"
    (sess / "subagents").mkdir(parents=True)
    (sess / "tool-results").mkdir()
    body = json.dumps({"id": "PROJ-9", "body": "x" * 50})
    (sess / "tool-results" / "mcp-srv-get-page-77.txt").write_text(body, encoding="utf-8")
    notice = ("Error: result (266,341 characters) exceeds maximum allowed tokens. "
              "Output has been saved to C:\\Other Machine\\proj\\sess\\tool-results\\"
              "mcp-srv-get-page-77.txt. Format: Plain text")
    lines = [
        _line({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_9", "name": "mcp__srv__get-page",
             "input": {"pageId": "9"}}]}}),
        _line({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_9", "content": notice}]}}),
    ]
    (sess / "subagents" / "agent-a.jsonl").write_text("".join(lines), encoding="utf-8")

    rec = [r for r in mcp.iter_tool_results(str(tmp_path)) if r["tool_use_id"] == "toolu_9"][0]
    assert rec["tool_name"] == "mcp__srv__get-page"
    assert rec["input"] == {"pageId": "9"}
    assert os.path.basename(rec["spill_path"]) == "mcp-srv-get-page-77.txt"
    assert mcp.unwrap(rec["result"])["id"] == "PROJ-9"

    raw = [r for r in mcp.iter_tool_results(str(tmp_path), follow_spills=False)
           if r["tool_use_id"] == "toolu_9"][0]
    assert raw["spill_path"] is None and "exceeds maximum" in raw["result"]

    (sess / "tool-results" / "mcp-srv-get-page-77.txt").unlink()
    gone = [r for r in mcp.iter_tool_results(str(tmp_path)) if r["tool_use_id"] == "toolu_9"][0]
    assert gone["spill_path"] is None and "exceeds maximum" in gone["result"]


def test_iter_tool_results_follows_persisted_output_notice(tmp_path):
    # The second notice shape: a <persisted-output> block with "saved to:" (colon)
    # and a 2KB preview that must not be mistaken for the full result.
    sess = tmp_path / "session"
    (sess / "tool-results").mkdir(parents=True)
    (sess / "tool-results" / "brxbxr8gr.txt").write_text('{"id": "full"}', encoding="utf-8")
    notice = ("<persisted-output>\nOutput too large (64.5KB). Full output saved to: "
              "D:/elsewhere/tool-results/brxbxr8gr.txt\n\nPreview (first 2KB):\n{\"id\": \"fu")
    plain = "the report was saved to notes.txt yesterday"
    (sess / "tool-results" / "notes.txt").write_text("not a spill", encoding="utf-8")
    lines = []
    for tid, content in (("toolu_p", notice), ("toolu_q", plain)):
        lines.append(_line({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {}}]}}))
        lines.append(_line({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": content}]}}))
    (sess / "t.jsonl").write_text("".join(lines), encoding="utf-8")

    recs = {r["tool_use_id"]: r for r in mcp.iter_tool_results(str(tmp_path)) if r["tool_use_id"]}
    assert mcp.unwrap(recs["toolu_p"]["result"]) == {"id": "full"}
    assert os.path.basename(recs["toolu_p"]["spill_path"]) == "brxbxr8gr.txt"
    # Ordinary prose naming a .txt is left alone even when such a file exists.
    assert recs["toolu_q"]["spill_path"] is None and recs["toolu_q"]["result"] == plain


def test_pick_treats_unfollowed_spill_notice_as_truncated():
    good = _rec("a", '{"id": 1, "body": "full"}', 1)
    notice = _rec("a", "<persisted-output>\nOutput too large (9KB). Full output saved to: "
                       "X:/gone.txt\n\nPreview (first 2KB):\n{\"id\": 1", 2)
    key = lambda r: mcp.unwrap(r["result"])["k"]  # noqa: E731
    assert mcp.pick([good, notice], key, policy="newest")["a"]["result"] == good["result"]
