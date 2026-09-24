import json

from kbkit import adf


def doc(*content):
    return {"type": "doc", "version": 1, "content": list(content)}


def p(*inline):
    return {"type": "paragraph", "content": list(inline)}


def t(text, *marks):
    n = {"type": "text", "text": text}
    if marks:
        n["marks"] = list(marks)
    return n


def cell(*content, header=False):
    return {"type": "tableHeader" if header else "tableCell", "content": list(content)}


def row(*cells):
    return {"type": "tableRow", "content": list(cells)}


def table(*rows):
    return {"type": "table", "content": list(rows)}


CARD = {"type": "inlineCard", "attrs": {"url": "https://example.test/browse/PROJ-123"}}


def test_words_split_across_marks_stay_joined():
    d = doc(p(t("Sca", {"type": "strong"}), t("nned"), t(" twice")))
    assert adf.to_text(d) == "Scanned twice\n"


def test_card_inside_heading_survives():
    d = doc({"type": "heading", "attrs": {"level": 2}, "content": [t("Epic: "), CARD]})
    assert "https://example.test/browse/PROJ-123" in adf.to_text(d)


def test_card_url_fallbacks():
    d = doc(p({"type": "inlineCard", "attrs": {"data": {"@id": "https://example.test/x"}}}),
            p({"type": "inlineCard", "attrs": {"data": {"name": "only-name"}}}))
    out = adf.to_text(d)
    assert "https://example.test/x" in out
    assert "only-name" in out  # JSON of data, never dropped


def test_card_formatter_callable():
    out = adf.to_text(doc(p(CARD)), cards=lambda typ, url: "<%s:%s>" % (typ, url))
    assert out == "<inlineCard:https://example.test/browse/PROJ-123>\n"


def test_inline_nodes():
    d = doc(p(t("a"), {"type": "hardBreak"}, t("b ")),
            p({"type": "mention", "attrs": {"id": "u1"}}, t(" "),
              {"type": "mention", "attrs": {"id": "u2", "text": "@Pat"}}),
            p({"type": "emoji", "attrs": {"shortName": ":smile:"}},
              {"type": "status", "attrs": {"text": "DONE"}}),
            p({"type": "date", "attrs": {"timestamp": "1700000000000"}}))
    lines = adf.to_text(d).splitlines()
    assert lines[0] == "a"
    assert lines[1] == "b "
    assert lines[2] == "@u1 @Pat"
    assert lines[3] == ":smile:DONE"
    assert lines[4] == "2023-11-14"


def test_media_extension_task_rule_and_unknown():
    d = doc({"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "m"}}]},
            {"type": "extension", "attrs": {"extensionKey": "toc"}},
            {"type": "bodiedExtension", "attrs": {"extensionKey": "x"}, "content": [p(t("inside"))]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [t("done")]},
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [t("todo")]}]},
            {"type": "rule"},
            {"type": "someFutureNode", "content": [p(t("still here"))]},
            {"type": "weird-leaf"})
    lines = adf.to_text(d).splitlines()
    assert lines == ["[media]", "[extension: toc]", "inside", "[x] done", "[ ] todo",
                     "---", "still here"]


def test_lists_and_table_rows():
    d = doc({"type": "bulletList", "content": [
                {"type": "listItem", "content": [p(t("one")), {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [p(t("nested"))]}]}]},
                {"type": "listItem", "content": [p(t("two"))]}]},
            table(row(cell(p(t("Label")), header=True), cell(p(t("Val")), p(t("ue"))))))
    assert adf.to_text(d) == "- one\n  - nested\n- two\nLabel | Val ue\n"


def test_accepts_json_string_and_plain_string():
    d = doc(p(t("hello")))
    assert adf.to_text(json.dumps(d)) == "hello\n"
    assert adf.to_text("not json at all") == "not json at all"


def test_iter_nodes_order():
    d = doc(p(t("a")), p(t("b")))
    assert [n["type"] for n in adf.iter_nodes(d)] == ["doc", "paragraph", "text", "paragraph", "text"]


def test_cards_includes_links_in_order():
    link = {"type": "link", "attrs": {"href": "https://example.test/l"}}
    d = doc(p(t("see ", ), t("here", link)), p(CARD),
            {"type": "blockCard", "attrs": {"url": "https://example.test/b"}})
    assert adf.cards(d) == [
        {"type": "link", "url": "https://example.test/l", "text": "here"},
        {"type": "inlineCard", "url": "https://example.test/browse/PROJ-123"},
        {"type": "blockCard", "url": "https://example.test/b"},
    ]


def test_tables():
    d = doc(table(row(cell(p(t("A"))), cell(p(t(" B "))))))
    assert adf.tables(d) == [[["A", "B"]]]


def test_row_value_label_in_column_0_or_1_and_nodes():
    d = doc(table(
        row(cell(p(t("Owner"))), cell(p(t("Acme")))),
        row(cell(p(t("2"))), cell(p(t("Tracking  Issue"))), cell(p(CARD)), cell(p(t("extra")))),
    ))
    assert adf.row_value(d, "owner") == ["Acme"]
    vals = adf.row_value(d, "tracking issue", nodes=True)
    assert [v[0] for v in vals] == ["https://example.test/browse/PROJ-123", "extra"]
    assert adf.cards(vals[0][1]) == [{"type": "inlineCard",
                                      "url": "https://example.test/browse/PROJ-123"}]
    assert adf.row_value(d, "Nope") == []


def test_row_value_custom_match():
    d = doc(table(row(cell(p(t("Owner:"))), cell(p(t("Acme"))))))
    assert adf.row_value(d, "Owner") == []
    m = lambda c, lbl: c.rstrip(":").casefold() == lbl.casefold()  # noqa: E731
    assert adf.row_value(d, "Owner", match=m) == ["Acme"]


def test_find_adf_in_nested_json_strings():
    d1, d2 = doc(p(t("one"))), doc(p(t("two")))
    resp = {"results": [{"body": {"atlas_doc_format": {"value": json.dumps(d1)}}},
                        {"fields": {"description": d2}}],
            "note": "{not json"}
    found = adf.find_adf([{"type": "text", "text": json.dumps(resp)}])
    assert [adf.to_text(x) for x in found] == ["one\n", "two\n"]


def test_find_adf_in_doubly_encoded_json():
    doc = {"type": "doc", "version": 1, "content": []}
    inner = json.dumps({"body": {"value": json.dumps(doc)}})
    assert adf.find_adf(json.dumps({"result": inner})) == [doc]
