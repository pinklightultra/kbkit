# kbkit

kbkit is for people checking a Confluence knowledge base: it reads a page the way a diff needs it read, turning Atlassian Document Format and HTML storage into text, tables, and links, and reading the Jira epic from the row that names it.

Python 3.10 or newer. Standard library only. Hand it the export or the API payload you already have. There is no console script.

## Quickstart

The name `kbkit` on PyPI is [Kirkwood-Buff Analysis Toolkit](https://pypi.org/project/kbkit/), a different project. `pip install kbkit` will not install this one.

```bash
git clone https://github.com/pinklightultra/kbkit
cd kbkit
python3 -m pip install -e .
python3 -c "import kbkit; print(kbkit.__version__)"
```

```
0.2.0
```

`PYTHONPATH=src` works without the install:

```bash
PYTHONPATH=src python3 -c "import kbkit; print(kbkit.__version__)"
```

These commands use `python3`. On a machine where the interpreter is named `python`, use that. CI does: `actions/setup-python` provides `python`.

## Use

| Job | Call |
| --- | --- |
| Render an ADF body. A word split by a bold mark stays one word. Smart links stay. | `adf.to_text`, `adf.cards`, `adf.find_adf` |
| Read a property table in ADF or HTML, including the link behind the cell text. | `adf.tables`, `adf.row_value`, `htmltext.table_rows` |
| Take the epic from the Jira Epic row. | `jira.epic_keys` |
| Flatten a Jira issue when the description is ADF or a plain string. | `jira.description_text`, `jira.field_text`, `jira.issue_keys` |
| Compare HTML after a save rewrites non-breaking spaces and heading ids. | `htmltext.visible_text`, `htmltext.normalize`, `htmltext.first_diff` |

The same package pages a REST listing (`paging.offset_pages`,
`paging.next_cursor`), chooses one copy of an MCP tool result from a Claude
Code transcript (`mcp.iter_tool_results`, `mcp.unwrap`, `mcp.pick`), matches
a term list on word boundaries (`terms.TermList`), and reads `.docx` and
`.xlsx` attachments (`office.docx_text`, `office.xlsx_rows`). `io.read_text`
and `io.Tee` cover exports and report files.

Render a page body. The heading is one word, and the smart link keeps its
URL. A link mark stays visible text. `cards` returns both.

```python
from kbkit import adf

page = {
    "type": "doc",
    "version": 1,
    "content": [
        {"type": "heading", "attrs": {"level": 1}, "content": [
            {"type": "text", "text": "Sca", "marks": [{"type": "strong"}]},
            {"type": "text", "text": "nned documents"},
        ]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Tracking "},
            {"type": "inlineCard", "attrs": {
                "url": "https://example.atlassian.net/browse/PROJ-12"}},
        ]},
        {"type": "table", "content": [
            {"type": "tableRow", "content": [
                {"type": "tableCell", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Jira Epic"}]}]},
                {"type": "tableCell", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Payments rewrite", "marks": [
                        {"type": "link", "attrs": {
                            "href": "https://example.atlassian.net/browse/PROJ-7"}}]}
                ]}]},
            ]},
        ]},
    ],
}

adf.to_text(page)
# 'Scanned documents\nTracking https://example.atlassian.net/browse/PROJ-12\nJira Epic | Payments rewrite\n'

adf.tables(page)
# [[['Jira Epic', 'Payments rewrite']]]

adf.cards(page)
# [{'type': 'inlineCard', 'url': 'https://example.atlassian.net/browse/PROJ-12'},
#  {'type': 'link', 'url': 'https://example.atlassian.net/browse/PROJ-7',
#   'text': 'Payments rewrite'}]
```

`row_value(..., nodes=True)` returns the cell node, so the URL that the cell
text hides is recoverable:

```python
text, cell = adf.row_value(page, "Jira Epic", nodes=True)[0]
text                     # 'Payments rewrite'
adf.cards(cell)[0]["url"]  # 'https://example.atlassian.net/browse/PROJ-7'
```

The same row in HTML storage. The visible label is a summary. The key is on
the link. Stories and an error code later in the page stay out of the epic.

```python
from kbkit import jira
from kbkit import htmltext as h

html = (
    "<table><tr>"
    "<td><strong>Jira Epic</strong></td>"
    "<td><a href='https://example.atlassian.net/browse/PROJ-7'>Payments rewrite</a></td>"
    "</tr></table>"
    "<p>Stories: PROJ-20, PROJ-21. Error ERR-001.</p>"
)

h.table_rows(html)[0][1]
# {'text': 'Payments rewrite',
#  'hrefs': ['https://example.atlassian.net/browse/PROJ-7']}

jira.epic_keys(html, projects=["PROJ"])
# (['PROJ-7'], 'row')

jira.epic_keys(page, projects=["PROJ"])
# (['PROJ-7'], 'row')
```

`source` is `"row"`, `"line"`, or `None`. An empty key list means
unmeasured: the declaration was found and the key was not. A status lozenge
in the epic cell returns `([], "row")`.

Flatten a Jira issue. API v3 returns ADF. API v2 returns a string. A
cascading select keeps its child.

```python
jira.description_text({"description": "Plain v2 description\n"})
# 'Plain v2 description'

jira.description_text({"description": page})
# 'Scanned documents\nTracking https://example.atlassian.net/browse/PROJ-12\nJira Epic | Payments rewrite'

jira.field_text({"value": "Region", "child": {"value": "North"}})
# 'Region > North'

jira.issue_keys("see PROJ-12 and proj-9", projects=["PROJ"], ignore_case=True)
# ['PROJ-12', 'PROJ-9']
```

Compare two HTML copies after the editor has done its save-time rewrite.
Run `normalize` on both sides.

```python
staged = "<h2 id='intro'>Scan</h2><p>a&nbsp;b</p>\n"
stored = "<h2>Scan</h2><p>a b</p>"
h.first_diff(h.normalize(staged), h.normalize(stored))
# None
```

`visible_text("<p>&amp;lt;code&amp;gt;</p>")` is `'&lt;code&gt;'`. The entity
is decoded once.

Page a listing with your own fetch. `fetch(offset, limit)` returns
`(items, total)`. This one stands in for a server that, past offset 200,
answers with an empty page and a total of 0.

```python
from kbkit.paging import next_cursor, offset_pages, PageCapReached

next_cursor({
    "_links": {"next": "https://example.atlassian.net/wiki/api/v2/pages?cursor=abc+def%3D"},
})
# 'abc+def='

def fetch(offset, limit):
    if offset >= 200:
        return [], 0
    return list(range(offset, min(offset + limit, 250))), None

got = []
try:
    for item in offset_pages(fetch, page_size=100):
        got.append(item)
except PageCapReached as exc:
    print("partial:", exc.items_seen, "stopped at", exc.offset, exc.reason)
# partial: 200 stopped at 200 empty_page_total_zero
```

A `+` in the cursor stays a `+`. `reason` is `max_offset`,
`empty_page_total_zero`, or `short_page_below_total`.

Term lists match on a word boundary. `Scan` does not hit `Scanned`.

```python
from kbkit.terms import TermList

TermList(["Scan"]).find("Scanned and a SCAN run")
# [('Scan', 14, 18)]
```

`str(TermList(...).report(texts))` is `"N listed terms found in M of K texts"`.

The other calls take a transcript directory or a file you already have:

```python
from kbkit import mcp, office, io as kio

def page_id(rec):
    body = mcp.unwrap(rec["result"])
    if rec["is_error"] or not isinstance(body, dict):
        return None
    return body.get("id")

chosen = mcp.pick(
    mcp.iter_tool_results(session_dir, tool="get-page"),
    key=page_id,
    policy="newest",   # or "longest"
)

office.docx_text("attachment.docx")    # path or bytes
office.xlsx_rows(xlsx_bytes)["Sheet1"]
office.xlsx_sheets(xlsx_bytes)         # [{"name", "state"}, ...]

kio.utf8_stdout()
kio.read_text("export.html")           # UTF-8, BOM stripped; cp1252 fallback
with kio.Tee("report.txt") as out:
    out("rows:", 3)
```

`chosen` maps each page id to the record `pick` kept. The file receives
`rows: 3`. The same line is echoed to stdout.

## The problem

Tooling for a knowledge base of about 1,900 articles grew as one script per
question. The copies shared bugs that return a wrong result and look
finished.

- A listing endpoint, past its offset cap, returned an empty page with a
  total of 0. A normal loop treats that as the end. On one version of the
  corpus that loop missed 41% of the articles. `paging.offset_pages` raises
  `PageCapReached` with reason `empty_page_total_zero`.
- Joining ADF text nodes with a space turns "Scanned", split across a bold
  mark, into "Sca nned". A search for the word misses it. `adf.to_text`
  concatenates inline text with no separator.
- A tool result the harness truncated, diffed against the stored page, shows
  the missing tail as a deletion in the middle of the body. `mcp.pick` drops
  a truncated copy when a complete copy of the same key exists, and it
  requires an explicit policy because the choice changes the answer.
- Taking a page's epic from every issue key in the body credits one page
  with 22 epics. It has one. The other 21 keys are its stories, and an
  error-code table matches the same shape, which brings a scan to 36.
  `jira.epic_keys` reads the `Jira Epic` row, or an `Epic:` / `Epic ID:`
  line outside any table.

Each parser is that fix, with a test that pins it. The rules are in
[What the calls guarantee](docs/reference.md).

## Tests

```bash
python3 -m pip install pytest
python3 -W error -m pytest -q
```

68 tests. Nothing else is required at runtime. The suite needs pytest.
`python3 -m pip install -e .` does not install it.

`-W error` fails the run on a `DeprecationWarning` or a `SyntaxWarning`.
GitHub Actions runs that pytest command as `python` on Ubuntu and Windows
for Python 3.10, 3.11, 3.12, and 3.13. The workflow is
[`.github/workflows/tests.yml`](.github/workflows/tests.yml), on every push
and pull request.

## Limits

- kbkit parses bytes you already have. `offset_pages` calls the fetch
  function you pass. `iter_tool_results` reads transcript files Claude Code
  has already written.
- Truncation markers, spill-notice wording, and `Jira Epic` row shapes come
  from one organization's pages and one version of the Claude Code harness.
  When a format changes, a marker list goes stale and stays quiet. `pick`
  sets `truncated` only when a marker it knows is present.
- `epic_keys` returns the key the document states, including a key that
  has since been renamed or deleted. Empty `keys` means unmeasured.
- Coverage is the ADF and HTML that knowledge-base articles contain. An
  unrecognised ADF node is walked through its `content`, which can render
  as less than the node holds.

## License

MIT. See [LICENSE](LICENSE).
