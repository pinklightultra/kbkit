import json

from kbkit import jira

ADF = {"type": "doc", "version": 1,
       "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body text"}]}]}


def test_issue_keys_unique_ordered_and_filtered():
    text = "PROJ-12 then ABC-9, PROJ-12 again, X-1 is not a key, and OPS2-7."
    assert jira.issue_keys(text) == ["PROJ-12", "ABC-9", "OPS2-7"]
    assert jira.issue_keys(text, projects=["PROJ", "ops2"]) == ["PROJ-12", "OPS2-7"]


def test_issue_keys_ignore_case_for_slugs():
    assert jira.issue_keys("/proj-45-some-title") == []
    assert jira.issue_keys("/proj-45-some-title", projects=["PROJ"], ignore_case=True) == ["PROJ-45"]


def test_field_text_scalars_and_lists():
    assert jira.field_text(None) == ""
    assert jira.field_text("s") == "s"
    assert jira.field_text(3.0) == "3.0"
    assert jira.field_text(True) == "True"
    assert jira.field_text([{"value": "A"}, None, {"name": "B"}]) == "A, B"


def test_field_text_dict_key_order():
    assert jira.field_text({"name": "n", "value": "v"}) == "v"
    assert jira.field_text({"displayName": "Pat", "accountId": "1"}) == "Pat"
    assert jira.field_text({"key": "PROJ-1", "self": "u"}) == "PROJ-1"
    assert json.loads(jira.field_text({"id": "10"})) == {"id": "10"}


def test_cascading_select_flattening():
    v = {"value": "Region", "id": "1", "child": {"value": "North", "id": "2"}}
    assert jira.field_text(v) == "Region > North"
    assert jira.field_text({"value": "Region", "child": {}}) == "Region"


def test_field_text_adf():
    assert jira.field_text(ADF) == "Body text"


def test_description_text_string_and_adf():
    assert jira.description_text({"description": "Plain v2 description\n"}) == "Plain v2 description"
    assert jira.description_text({"description": ADF}) == "Body text"
    assert jira.description_text({"description": json.dumps(ADF)}) == "Body text"
    assert jira.description_text({"fields": {"description": "via issue"}}) == "via issue"


def test_description_text_empty_only_when_empty():
    assert jira.description_text({"description": None}) == ""
    assert jira.description_text({"description": "   "}) == ""
    assert jira.description_text({}) == ""


def _t(s, **marks):
    n = {"type": "text", "text": s}
    if marks.get("href"):
        n["marks"] = [{"type": "link", "attrs": {"href": marks["href"]}}]
    return n


def _cell(*inline):
    return {"type": "tableCell", "content": [{"type": "paragraph", "content": list(inline)}]}


def _doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def _table(*rows):
    return {"type": "table", "content": [{"type": "tableRow", "content": list(r)} for r in rows]}


def _para(*inline):
    return {"type": "paragraph", "content": list(inline)}


def test_epic_keys_row_label_in_cell_0_or_1_reads_next_cell_only():
    doc = _doc(_table([_cell(_t("Jira Epic")), _cell(_t("PROJ-1")), _cell(_t("see PROJ-2"))]),
               _table([_cell(_t("3")), _cell(_t("JIRA Epic:")), _cell(_t("PROJ-1"))]))
    assert jira.epic_keys(doc) == (["PROJ-1"], "row")


def test_epic_keys_reads_cards_and_link_targets_in_the_cell():
    card = {"type": "inlineCard", "attrs": {"url": "https://x.atlassian.net/browse/PROJ-7"}}
    assert jira.epic_keys(_doc(_table([_cell(_t("Jira Epic")), _cell(card)]))) == (["PROJ-7"], "row")
    link = _t("Summary of the work - Jira", href="https://x.atlassian.net/browse/PROJ-8")
    assert jira.epic_keys(_doc(_table([_cell(_t("Jira Epic")), _cell(link)]))) == (["PROJ-8"], "row")


def test_epic_keys_never_falls_back_to_a_body_wide_scan():
    # One epic and its stories in a ticket table, error codes shaped like keys:
    # none of it declares the page's epic.
    doc = _doc(_para(_t("Stories PROJ-2, PROJ-3 and error ERR-001.")),
               _table([_cell(_t("1")), _cell(_t("PROJ-1")), _cell(_t("Epic"))]))
    assert jira.epic_keys(doc) == ([], None)


def test_epic_keys_line_fallback_only_outside_tables_and_only_without_a_row():
    doc = _doc(_para(_t("Release: 1.0"), {"type": "hardBreak"}, _t("Epic: PROJ-5 "),
                     {"type": "hardBreak"}, _t("Date: today")))
    assert jira.epic_keys(doc) == (["PROJ-5"], "line")
    assert jira.epic_keys(_doc(_para(_t("Epic ID: PROJ-6")))) == (["PROJ-6"], "line")
    in_table = _doc(_table([_cell(_t("Epic: PROJ-9")), _cell(_t("x"))]))
    assert jira.epic_keys(in_table) == ([], None)
    both = _doc(_para(_t("Epic: PROJ-5")), _table([_cell(_t("Jira Epic")), _cell(_t("PROJ-1"))]))
    assert jira.epic_keys(both) == (["PROJ-1"], "row")


def test_epic_keys_empty_row_is_reported_as_found_but_unkeyed():
    # Worklist pages score a "Jira Epic" field with a status lozenge. The row is
    # there; the key is not, and the caller must treat [] as unmeasured.
    lozenge = {"type": "status", "attrs": {"text": "Filled", "color": "green"}}
    assert jira.epic_keys(_doc(_table([_cell(_t("Jira Epic")), _cell(lozenge)]))) == ([], "row")


def test_epic_keys_projects_filter_and_json_string_input():
    doc = _doc(_table([_cell(_t("Jira Epic")), _cell(_t("ERR-001 PROJ-4"))]))
    assert jira.epic_keys(doc, projects=["PROJ"]) == (["PROJ-4"], "row")
    wrapped = json.dumps({"id": "1", "body": {"atlas_doc_format": {"value": json.dumps(doc)}}})
    assert jira.epic_keys(wrapped) == (["ERR-001", "PROJ-4"], "row")
    assert jira.epic_keys({"no": "doc"}) == ([], None)


def test_epic_keys_html():
    html = ("<table><tbody><tr><td><p><strong>Jira Epic</strong></p></td>"
            "<td><a href='https://x.atlassian.net/browse/PROJ-3'>Summary - Jira</a></td>"
            "<td>PROJ-99</td></tr></tbody></table><p>Also PROJ-50.</p>")
    assert jira.epic_keys(html) == (["PROJ-3"], "row")
    assert jira.epic_keys("<h2>Epic: PROJ-12</h2><table><tr><td>PROJ-1</td></tr></table>") == (["PROJ-12"], "line")
    assert jira.epic_keys("<p>Nothing declared, PROJ-1 mentioned.</p>") == ([], None)
