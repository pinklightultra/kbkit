# kbkit

Read a Confluence page the way a diff needs it read. kbkit turns Atlassian
Document Format and HTML storage into text, tables, and links, and it reads
the Jira epic from the row that names it.

Python 3.10 or newer. Standard library only. Hand it the export or the API
payload you already have.

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

Each parser is that fix, with a test that pins it. The rules are under
[What the calls guarantee](#what-the-calls-guarantee).

## Install

```bash
git clone https://github.com/pinklightultra/kbkit
cd kbkit
pip install -e .
python -W error -m pytest -q
```

`pip install -e .` puts the package on the path. `PYTHONPATH=src` works
without the install. The interface is the import: there is no console script.

The name `kbkit` on PyPI is Kirkwood-Buff Analysis Toolkit, a different
project. `pip install kbkit` will not install this one.

## Use

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
`(items, total)`. kbkit calls that function.

```python
from kbkit.paging import next_cursor, offset_pages, PageCapReached

next_cursor({
    "_links": {"next": "https://example.atlassian.net/wiki/api/v2/pages?cursor=abc+def%3D"},
})
# 'abc+def='

try:
    rows = list(offset_pages(lambda offset, limit: fetch(offset, limit), page_size=100))
except PageCapReached as exc:
    print("partial:", exc.items_seen, "stopped at", exc.offset, exc.reason)
```

A `+` in the cursor stays a `+`. `reason` is `max_offset`,
`empty_page_total_zero`, or `short_page_below_total`.

The other four modules:

```python
from kbkit import mcp, office, io as kio
from kbkit.terms import TermList

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

TermList(["Scan"]).find("Scanned and a SCAN run")
# [('Scan', 14, 18)]

office.docx_text("attachment.docx")    # path or bytes
office.xlsx_rows(xlsx_bytes)["Sheet1"]
office.xlsx_sheets(xlsx_bytes)         # [{"name", "state"}, ...]

kio.utf8_stdout()
kio.read_text("export.html")           # UTF-8, BOM stripped; cp1252 fallback
with kio.Tee("report.txt") as out:
    out("rows:", 3)
```

`chosen` maps each page id to the record `pick` kept. `str(TermList(...).report(texts))`
is `"N listed terms found in M of K texts"`.

## What the calls guarantee

### adf

- Inline text inside a block is concatenated with no separator. Block nodes
  end with a newline.
- `inlineCard`, `blockCard`, and `embedCard` render wherever they sit,
  including headings and table cells. The URL is `attrs.url`, then
  `attrs.data.url`, then `attrs.data["@id"]`, then the JSON of `attrs.data`.
  Pass `cards=` a callable `(node_type, url) -> str` to format them. The
  default is the bare URL.
- `hardBreak` is a newline. `mention` is `attrs.text`, or `@` plus `id`.
  `emoji` is `attrs.text`, or `shortName`. `status` is its text. `date` is
  the UTC calendar date. A rule is `---`. Media renders as `[media]`. An
  extension renders its content, or `[extension: key]`. A `taskItem` is
  prefixed `[ ]` or `[x]`. Bullet items are prefixed `- `. Ordered items
  are numbered from `attrs.order`, which defaults to 1. Table cells join
  with `" | "`, one row per line.
- Unknown node types are walked through `content`. A JSON string is decoded.
  A string that is not JSON is returned unchanged.
- `cards()` returns cards and link marks in document order: `{type, url}`,
  plus `text` for links.
- `tables()` returns every table, nested tables included, as rows of cell
  text.
- `row_value()` looks for the label in column 0 or column 1 and returns the
  cells after it. Matching is casefold equality after whitespace collapse.
  A trailing colon needs a custom `match`. `nodes=True` returns
  `(text, cell_node)` pairs. For the epic row, use `jira.epic_keys`.
- `find_adf()` returns every dict with `type == "doc"`, and decodes JSON
  strings nested inside JSON, including a document encoded twice. API
  payloads often carry the ADF body that way.
- `iter_nodes()` yields every dict node depth-first, in document order.

### htmltext

- `visible_text()` skips `script` and `style`, decodes entities once, and
  collapses whitespace. `&amp;lt;` becomes `&lt;`.
- `normalize(nbsp=True)` turns U+00A0, `&nbsp;`, `&#160;`, and `&#xa0;` into
  a space. The literal text `&amp;nbsp;` stays.
- `normalize(strip_tail_style=True)` removes one `<style>` block, and only
  when it is the last thing in the document. An earlier `<style>` stays.
- `normalize(heading_ids=True)` removes `id` from `h1` through `h6` only.
- `normalize()` always applies `rstrip()`, the same way for every input.
  Run it on both sides of a diff.
- `first_diff()` returns `None` when the inputs are equal. Otherwise
  `{offset, a, b}`, each value a window of `context` characters (default
  40) on either side of the first difference.
- `table_rows()` lists every table's rows, nested tables separately, as
  `{text, hrefs}` cells. The outer cell's text leaves the nested table out.
  `text_outside_tables()` is the visible text with every table removed.

### jira

- `field_text()` checks, in order: an ADF doc, a cascading select
  (`parent > child`), then `value`, `name`, `displayName`, `key`, `text`,
  then a list joined with `", "`. Anything else becomes compact JSON. The
  full value is kept.
- `description_text()` accepts an issue or its `fields`. It handles ADF,
  a plain string, and ADF delivered as a JSON string. It returns `""` when
  the description is absent or blank.
- `issue_keys()` returns unique keys in first-seen order. The pattern is
  an uppercase letter, more uppercase letters or digits, a hyphen, and
  digits, so `X-1` does not match. `ignore_case=True` also matches
  lowercase keys, as in slugs, and returns them uppercased. `projects=`
  keeps the prefixes you name.
- `epic_keys(doc)` accepts an ADF doc, JSON text of one, or an HTML string.
  It returns `(keys, source)`. The label matches `^jira\s*epic` in column
  0 or 1, so `Jira Epic`, `JIRA Epic Link`, and `Jira epic:` all count.
  Keys come from the next cell only: its text, its cards, and its link
  targets. With no such row, an `Epic:` or `Epic ID:` line in a paragraph
  or heading outside tables is the fallback. Source is `"row"`, `"line"`,
  or `None`. Keys in the rest of the page stay out of the result.

### paging

- `next_cursor()` reads `resp["_links"]["next"]` and returns the named query
  parameter (`cursor` by default), URL-unquoted with `unquote`. A literal
  `+` stays a `+`.
- `offset_pages(fetch, *, page_size, start=0, max_offset=None)` expects
  `fetch(offset, limit)` to return `(items, total_or_None)`. It stops when
  a page is shorter than `page_size`, or when `offset` reaches a reported
  total. It raises `PageCapReached(offset, items_seen, reason)` when:
  - `max_offset` is reached while the data is still open (`max_offset`)
  - a later page is empty and `total` is 0 (`empty_page_total_zero`)
  - a short page arrives while `total` says more items remain
    (`short_page_below_total`)

Items already yielded stay yielded. The exception carries the count.

### mcp

- `unwrap()` joins every text part. It accepts a part list, a dict whose
  `content` is parts, a JSON string, or a decoded object, and it decodes
  JSON nested inside JSON. `envelope=True` strips one `data` or `result`
  wrapper. The default leaves those keys alone, because payloads use them.
- `result_text()` joins the text parts and leaves them as text.
- `iter_tool_results(root)` streams `*.jsonl` line by line, pairs
  `tool_use` with `tool_result` by id, and skips malformed lines. A spill
  file under `tool-results/*.txt` has `tool_name=None`, so a `tool=` filter
  is matched against the file name. With `follow_spills=True` (the default),
  a spill notice is replaced by the file's text when that file can be found.
- `pick(records, key, *, policy)` requires `policy`: `newest` (mtime, then
  line) or `longest`. A truncated copy is discarded when a complete copy of
  the same key exists. Each chosen record is a shallow copy with `truncated`
  set, and that flag is true only when every copy was truncated. The return
  value maps key to record. `key` returning `None` skips the record.

### terms

- `TermList` matches on word boundaries, longest term first, so `Scan` misses
  `Scanned` and `Acme` loses to `Acme Health` at the same position. Matching
  is case-insensitive unless `case_sensitive=True`. Whitespace inside a term
  matches any whitespace.
- `report()` returns a `TermReport`. `str(report)` is
  `"N listed terms found in M of K texts"`. The report has `counts`,
  `terms_found`, and `per_text`. It has no `clean` attribute. A list is
  evidence about the names on the list.

### office

- `docx_text()` and `docx_parts()` read a path or bytes with `zipfile` and
  `ElementTree`. Tracked deletions render as `[deleted: text]` by default
  (`deleted="mark"`; also `"keep"` and `"drop"`). Tabs, breaks, `[sym:XXXX]`
  symbols, and checkboxes as `[x]` or `[ ]` are kept. Table rows join with
  `" | "`. After the body: headers, footers, footnotes, endnotes, comments.
- `xlsx_rows()` returns every sheet, hidden sheets included, as a dict of
  sheet name to rows of strings. `xlsx_sheets()` reports `visible`,
  `hidden`, or `veryHidden`. Shared, rich, and inline strings are resolved.
  Phonetic runs are skipped. Cells are placed by their reference, so a blank
  cell leaves a gap. Numbers and dates stay as stored. Dates are serials.

### io

- `read_text()` decodes UTF-8 and strips a BOM, then falls back to cp1252
  with `errors="replace"`.
- `utf8_stdout()` reconfigures stdout and stderr to UTF-8 with
  `errors="replace"`. A stream that cannot be reconfigured is left as it is.
- `Tee(path)` writes UTF-8 to the file and echoes to stdout. Call it like
  `print`. `write` sends the string through unchanged.

## Tests

```bash
python -W error -m pytest -q
```

68 tests. Nothing else is required at runtime. The suite needs pytest.
`-W error` is there because an invalid escape in a test string raises only
a `SyntaxWarning`, and this suite has shipped one.

GitHub Actions runs that command on Ubuntu and Windows for Python 3.10,
3.11, 3.12, and 3.13. The workflow is `.github/workflows/tests.yml`, on
every push and pull request.

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
