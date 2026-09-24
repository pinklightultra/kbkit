# kbkit

Small, stdlib-only (Python 3.10+) helpers for knowledge-base tooling: Atlassian
ADF documents, Jira fields, Claude Code MCP tool-result files, HTML article
text, paged REST APIs, term lists, and Office attachments. No network calls,
no credentials.

```bash
pip install -e .          # or: PYTHONPATH=src python -m pytest -q
```

## Why this exists

Documentation tooling for a knowledge base of about 1,900 articles grew the
way this kind of tooling does: one script per question, each reimplementing
the same parsing. The copies shared a set of bugs whose common trait is that
they return a confident wrong result instead of an error:

- A listing endpoint stopped at offset 1000 and returned an empty page with a
  total of 0. A normal paging loop takes that as the end. On one version it
  missed 41% of the articles.
- Joining ADF text nodes with a space turns "Scanned", split across a bold
  mark, into "Sca nned", which no search for the word matches.
- A result the harness truncated, diffed against the original, shows its
  missing tail as a mid-body deletion.
- Taking an article's epic from any issue key in its body credits one real
  page with 22 epics. It has one; the other 21 keys are its stories. The generic
  key pattern finds 36, because its error-code table has the same shape.

kbkit is those parsers written once, each with the fix built in and a test
that pins it. The "Behaviour contracts" section below lists each decision and
why it was made.

## Modules

**`kbkit.adf`**: walks ADF trees and renders them as text. Covers tables, row lookup, cards and links, and finds ADF documents inside a response.

```python
from kbkit import adf
text = adf.to_text(page_body)                    # cards and links kept as URLs
for text, cell in adf.row_value(page_body, "Tracking issue", nodes=True):
    urls = [c["url"] for c in adf.cards(cell)]
```

**`kbkit.mcp`**: unwraps MCP tool results and streams them out of Claude Code transcripts and `tool-results/` spill files. Also picks one copy per key.

```python
from kbkit import mcp
recs = mcp.iter_tool_results(session_dir, tool="get-page")
best = mcp.pick(recs, key=lambda r: (mcp.unwrap(r["result"]) or {}).get("id"), policy="newest")
```

**`kbkit.jira`**: issue-key extraction and field flattening, including cascading selects, and descriptions in both ADF and plain-string form. `epic_keys` reads the epic a Confluence page or HTML article belongs to from its `Jira Epic` row.

```python
from kbkit import jira
jira.issue_keys("see PROJ-12 and proj-9", projects=["PROJ"], ignore_case=True)  # ['PROJ-12', 'PROJ-9']
jira.description_text(issue["fields"])
keys, source = jira.epic_keys(page_adf_or_html, projects=["PROJ"])  # (['PROJ-7'], 'row')
```

**`kbkit.htmltext`**: visible text of an HTML article, byte-diff normalisation, the first difference between two strings, and table cells with their links.

```python
from kbkit import htmltext as h
d = h.first_diff(h.normalize(staged), h.normalize(stored))   # None if identical
h.table_rows(html)[0][1]   # {'text': 'PROJ-7', 'hrefs': ['https://.../browse/PROJ-7']}
```

**`kbkit.paging`**: cursor extraction and offset paging that raises when paging stops at a limit and not at the end of the data.

```python
from kbkit.paging import offset_pages, PageCapReached
try:
    rows = list(offset_pages(lambda off, lim: api(off, lim), page_size=100))
except PageCapReached as e:
    print("partial:", e.items_seen, "items, stopped at", e.offset, e.reason)
```

**`kbkit.terms`**: matches a term list on word boundaries and reports the result without claiming the text is clean.

```python
from kbkit.terms import TermList
print(TermList(["Acme", "Globex"]).report(texts))   # "1 listed terms found in 3 of 40 texts"
```

**`kbkit.office`**: text from `.docx` files and rows from `.xlsx` files, using only zipfile and ElementTree.

```python
from kbkit import office
office.docx_text("spec.docx"); office.xlsx_rows(data_bytes)["Sheet1"]; office.xlsx_sheets(data_bytes)
```

**`kbkit.io`**: `read_text` (UTF-8/BOM, cp1252 fallback), `utf8_stdout()`, and `Tee(path)`.

```python
from kbkit import io as kio
kio.utf8_stdout()
with kio.Tee("report.txt") as out:
    out("rows:", 3)
```

## Behaviour contracts

These are deliberate decisions. Most of them fix a bug found in an earlier ad-hoc script.

adf
- Inline text within a block is concatenated with **no separator**, so a word split across marks stays whole. Block nodes end with a newline.
- `inlineCard`/`blockCard`/`embedCard` are **never dropped**, including inside headings and table cells. The URL comes from `attrs.url`, then `attrs.data.url`, then `attrs.data["@id"]`, then the JSON of `attrs.data`.
- Other node renderings: `hardBreak` is a newline. `mention` is `attrs.text`, or `@id` when there is no text. `emoji` is `attrs.text`, or `shortName`. `status` is its text. `date` is the ISO date in UTC. Media renders as `[media]`. An extension renders its content, or `[extension: key]` when it has none. `taskItem` gets a `[ ]` or `[x]` prefix. Table cells are joined with `" | "`, one row per line.
- Unknown node types are walked through their `content` and never raise. A JSON string is decoded. A string that is not JSON is returned unchanged.
- `cards()` returns cards and link marks in document order: `{type, url}`, plus `text` for links.
- `row_value()` looks for the label in column 0 **or** column 1 and returns the cells after it. Matching is casefold equality after whitespace collapse. With `nodes=True` it returns `(text, cell_node)` pairs. For an epic row use `jira.epic_keys`, which also accepts "Jira Epic:" and "JIRA Epic Link".
- `find_adf()` returns every `type == "doc"` dict and decodes JSON strings nested inside JSON, including doubly encoded ones.

mcp
- `unwrap()` joins **all** text parts. It accepts a part list, `{"content": parts}`, a JSON string or a decoded object, and decodes nested JSON-in-JSON. It strips `{"data"}`/`{"result"}` envelopes **only** with `envelope=True`, because real payloads use those keys.
- `iter_tool_results()` streams `*.jsonl` line by line, pairs `tool_use` with `tool_result` by id, and skips malformed lines. Spill files under `tool-results/*.txt` have `tool_name=None`, so `tool=` is matched against their file name.
- `pick()` requires an explicit policy, `newest` (mtime, line) or `longest`, because the choice changes the answer. A truncated copy is discarded when a complete copy of the same key exists. The `truncated` flag is True only when every copy was truncated.

jira
- `field_text()` checks, in order: an ADF doc, then a cascading select (`a > b`), then the value/name/displayName/key/text fields, then a list (joined with `", "`). Anything else falls back to JSON. It never truncates.
- `description_text()` accepts ADF, plain strings, and ADF delivered as a JSON string. It returns `""` only when the description is empty or blank.
- `issue_keys()` returns unique keys in order. `ignore_case=True` finds lowercase keys, for example in slugs, and returns them uppercased. Combine it with `projects=` to avoid false positives.
- `epic_keys()` returns `(keys, source)`. It reads the cell after a label matching `^jira\s*epic` in column 0 or 1, including card and link URLs. With no such row it falls back to an `Epic:` / `Epic ID:` line outside tables, and never to a body-wide key scan. Source is `"row"`, `"line"` or None. Empty `keys` means unmeasured: a row holding a status lozenge returns `([], "row")`.

htmltext
- Entities are decoded **once**, by the stdlib. `&amp;lt;` decodes to `&lt;`, never to `<`.
- `normalize(nbsp=True)` turns U+00A0, `&nbsp;`, `&#160;` and `&#xa0;` into a space. The literal text `&amp;nbsp;` is left alone.
- `normalize(strip_tail_style=True)` removes one `<style>` block, and only when it is the last thing in the document. An earlier `<style>` is never touched.
- `normalize(heading_ids=True)` removes `id=` from `h1`–`h6` only.
- `normalize()` always applies `rstrip()`, identically for every input. Apply it to both sides of a diff.
- `first_diff()` returns `None` when the inputs are equal. Otherwise it returns `{offset, a, b}`, where each value is a window of `±context` around the first difference.
- `table_rows()` lists every table's rows, nested tables separately, as `{text, hrefs}` cells. `text_outside_tables()` is the visible text with all tables removed.

paging
- `next_cursor()` URL-unquotes the cursor, using `unquote`, which keeps `+` as `+`.
- `offset_pages()` raises `PageCapReached(offset, items_seen, reason)` in three cases:
  - `max_offset` is reached before the data is known to be exhausted.
  - A page comes back **empty with total 0 after earlier pages had items**. Some APIs signal a hard offset cap this way, and a normal paging loop reads it as the end of the data and silently undercounts.
  - A short page arrives while the reported total says more items remain.

terms
- Matching uses word boundaries: `(?<!\w)` and `(?!\w)`. Longest terms are tried first. Matching is case-insensitive by default. Whitespace inside a term matches any whitespace.
- `report()` prints `"N listed terms found in M of K texts"`. It has **no** `clean`/`is_clean` attribute. A list is evidence about the names on the list, never proof of absence.

office
- `docx_text()` renders tracked deletions (`[deleted: …]` by default), tabs, breaks, `[sym:XXXX]` symbols, and legacy and content-control checkboxes as `[x]`/`[ ]`. Table rows are joined with `" | "`. It covers headers, footers, footnotes, endnotes and comments, in that order after the body.
- `xlsx_rows()` returns every sheet, hidden ones included. `xlsx_sheets()` reports each sheet's state. Shared, rich and inline strings are resolved, and phonetic runs are skipped. Cells and rows are placed by reference, so blank cells never shift a row left. Numbers and dates are returned exactly as stored.

## Tests

```bash
python -W error -m pytest -q      # 68 tests, standard library plus pytest
```

`-W error` is deliberate: an invalid escape in a test string only raises a
`SyntaxWarning`, and this suite has shipped one. CI runs the suite on Linux and
Windows for Python 3.10 to 3.13.

## Limitations

- **No network code.** kbkit parses what you already fetched. Paging takes
  your fetch function, and the MCP reader works on files Claude Code has
  already written.
- **The heuristics are empirical.** The truncation markers, the spill-notice
  formats and the `Jira Epic` row shapes come from one organization's content
  and one version of the Claude Code harness. When a format changes, a marker
  list goes out of date without raising an error. `pick()` flags a record as
  truncated only when a marker it knows about appears.
- **`epic_keys` finds a row; it does not validate the key.** It returns what
  the document says, even if the issue has been re-keyed or deleted.
  Empty `keys` means unmeasured, not "this document has no epic".
- **Not a general HTML or ADF library.** Coverage is what knowledge-base
  articles actually contain. Anything unrecognized is walked and never raises,
  which also means it can be silently rendered as less than it is.

## License

MIT. See [LICENSE](LICENSE).
