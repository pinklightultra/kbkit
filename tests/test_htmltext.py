from kbkit import htmltext

NBSP = "\u00a0"


def test_visible_text_decodes_once():
    assert htmltext.visible_text("<p>&amp;lt;tag&amp;gt;</p>") == "&lt;tag&gt;"
    assert htmltext.visible_text("<p>&lt;b&gt;</p>") == "<b>"


def test_visible_text_skips_script_style_and_breaks_blocks():
    html = ("<style>p{color:red}</style><h1>Title</h1><p>one" + NBSP + " two</p>"
            "<script>var x=1;</script><ul><li>a</li><li>b<br>c</li></ul><span>in</span>line")
    assert htmltext.visible_text(html) == "Title\none two\na\nb\nc\ninline"


def test_normalize_nbsp():
    s = "a" + NBSP + "b&nbsp;c&#160;d&#xA0;e &amp;nbsp;"
    assert htmltext.normalize(s) == "a b c d e &amp;nbsp;"
    assert NBSP in htmltext.normalize("a" + NBSP + "b", nbsp=False)


def test_tail_style_strip_leaves_earlier_style_intact():
    html = ("<style>.keep{}</style><p>body</p><p>more</p>"
            "<style>\n p[data-x] { margin: 0 }\n</style>\n  ")
    out = htmltext.normalize(html)
    assert out == "<style>.keep{}</style><p>body</p><p>more</p>"


def test_tail_style_not_stripped_when_not_at_end():
    html = "<p>a</p><style>.s{}</style><p>b</p>"
    assert htmltext.normalize(html) == html
    assert htmltext.normalize(html + "<style>t</style>", strip_tail_style=False).endswith("<style>t</style>")


def test_only_heading_ids_removed():
    html = '<h2 id="intro" class="c">Intro</h2><p id="para">x</p><H3 ID=\'y\'>Y</H3><a id="anchor"></a>'
    out = htmltext.normalize(html)
    assert out == '<h2 class="c">Intro</h2><p id="para">x</p><H3>Y</H3><a id="anchor"></a>'
    assert htmltext.normalize(html, heading_ids=False) == html


def test_rstrip_applied_identically():
    assert htmltext.normalize("<p>x</p>\n\n", strip_tail_style=False, heading_ids=False,
                              nbsp=False) == "<p>x</p>"
    assert htmltext.normalize("<p>x</p>") == htmltext.normalize("<p>x</p>  \r\n")


def test_first_diff():
    assert htmltext.first_diff("same", "same") is None
    d = htmltext.first_diff("abcdef", "abcXef", context=2)
    assert d == {"offset": 3, "a": "bcde", "b": "bcXe"}
    assert htmltext.first_diff("abc", "abcd")["offset"] == 3
    assert htmltext.first_diff(b"ab", b"ac")["offset"] == 1


def test_table_rows_cells_hrefs_and_nesting():
    html = ("<p>before</p><table><tr><th>Field</th><th>Value</th></tr>"
            "<tr><td>Link</td><td><a href='u1'>one</a> and <a href='u2'>two</a>"
            "<table><tr><td>inner</td></tr></table> tail</td></tr></table><p>after &amp; done</p>")
    rows = htmltext.table_rows(html)
    assert [[c["text"] for c in r] for r in rows] == [["Field", "Value"], ["Link", "one and two tail"], ["inner"]]
    assert rows[1][1]["hrefs"] == ["u1", "u2"]
    assert htmltext.text_outside_tables(html) == "before\nafter & done"
