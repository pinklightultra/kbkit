# What the calls guarantee

These are the rules the functions in `src/kbkit` follow. The short examples are in the [README](../README.md).

### adf

- Inline text inside a block is concatenated with no separator. Block nodes
  end with a newline. Nested lists indent two spaces per level.
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
  text. Cell text is stripped.
- `row_value()` looks for the label in column 0 or column 1 and returns the
  cells after it, stripped. Matching is casefold equality after whitespace
  collapse. A trailing colon needs a custom `match`. `nodes=True` returns
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
- `normalize()` applies those options in that order: tail style, heading
  ids, then nbsp. It always finishes with `rstrip()`, the same way for
  every input. Run it on both sides of a diff.
- `first_diff()` returns `None` when the inputs are equal. Otherwise
  `{offset, a, b}`. Each window is the slice `[offset - context, offset + context)`
  (default `context` 40). When one side is a prefix of the other, `offset`
  is the shorter length.
- `table_rows()` lists every table's rows, nested tables separately, as
  `{text, hrefs}` cells. The outer cell's text leaves the nested table out.
  `text_outside_tables()` is the visible text with every table removed.

### jira

- `field_text()` checks, in order: `None` (returns `""`), a string (as it
  is), a bool or number (`str`), then a list joined with `", "` (empty
  items dropped). A dict is an ADF doc if `type` is `"doc"`, then a
  cascading select (`parent > child`), then the first string among `value`,
  `name`, `displayName`, `key`, and `text`. A dict with none of those becomes
  compact JSON. Anything else becomes `str(value)`. Nothing is truncated.
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
  targets. With no such row, an `Epic:` or `Epic ID:` line outside tables
  is the fallback. In ADF that line has to be a paragraph or a heading. In
  HTML it is any text outside a table. Source is `"row"`, `"line"`, or
  `None`. Keys in the rest of the page stay out of the result. An empty
  `keys` list means unmeasured, not that the page has no epic, whatever
  `source` is. A status lozenge in the epic cell returns `([], "row")`, and
  the line fallback is not tried.

### paging

- `next_cursor()` reads `resp["_links"]["next"]` and returns the named query
  parameter (`cursor` by default), URL-unquoted with `unquote`. A literal
  `+` stays a `+`.
- `offset_pages(fetch, *, page_size, start=0, max_offset=None)` expects
  `fetch(offset, limit)` to return `(items, total_or_None)`. It stops when
  a page is shorter than `page_size`, or when `offset` reaches a reported
  total. It raises `PageCapReached(offset, items_seen, reason)` when:
  - `max_offset` is reached while the data is still open (`max_offset`)
  - a later page is empty and `total` is 0, after at least one item was
    already yielded (`empty_page_total_zero`). A first page that is empty
    with `total` 0 is an empty listing, not this error.
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
  file under `tool-results/*.txt` has `tool_name=None`. A `tool=` filter is
  a substring of the tool name, or, for a spill file, a substring of the
  file name. The harness names those files after the tool, with `-` where
  the tool name has `__`. With `follow_spills=True` (the default), a spill
  notice is replaced by the file's text when that file can be found.
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
  symbols, and checkboxes as `[x]` or `[ ]` are kept. Table cells join with
  `" | "`. Paragraphs inside one cell join with `" / "`. After the body:
  headers, footers, footnotes, endnotes, comments. `docx_text` separates
  those parts with a blank line.
- `xlsx_rows()` returns every sheet, hidden sheets included, as a dict of
  sheet name to rows of strings. `xlsx_sheets()` reports `visible`,
  `hidden`, or `veryHidden`. Shared, rich, and inline strings are resolved.
  Phonetic runs are skipped. Cells are placed by their reference, so a blank
  cell leaves a gap and a skipped row is `[]`. Numbers and dates stay as
  stored. Dates are serials.

### io

- `read_text()` decodes UTF-8 and strips a BOM, then falls back to cp1252
  with `errors="replace"`.
- `utf8_stdout()` reconfigures stdout and stderr to UTF-8 with
  `errors="replace"`. A stream that cannot be reconfigured is left as it is.
- `Tee(path)` writes UTF-8 to the file and echoes to stdout. Call it like
  `print`. The file receives the string unchanged. If the console cannot
  encode a character, the echo replaces that character and does not raise.
