import pytest

from kbkit.paging import PageCapReached, next_cursor, offset_pages


def test_next_cursor_unquotes():
    resp = {"_links": {"next": "/api/items?limit=25&cursor=YWJj%2BZA%3D%3D&x=1"}}
    assert next_cursor(resp) == "YWJj+ZA=="
    assert next_cursor({"_links": {"next": "/api?cursor=a+b"}}) == "a+b"  # '+' is data
    assert next_cursor({"_links": {}}) is None
    assert next_cursor({}) is None
    assert next_cursor({"_links": {"next": "/api?page=2"}}) is None
    assert next_cursor({"_links": {"next": "/api?page=2"}}, param="page") == "2"


def make_fetch(n, cap=None, report_total=True, server_limit=None):
    calls = []

    def fetch(offset, limit):
        calls.append(offset)
        if cap is not None and offset >= cap:
            return [], 0  # silent-cap signature
        lim = min(limit, server_limit) if server_limit else limit
        items = list(range(offset, min(offset + lim, n)))
        return items, (n if report_total else None)

    return fetch, calls


def test_offset_pages_reads_everything():
    fetch, calls = make_fetch(23)
    assert list(offset_pages(fetch, page_size=10)) == list(range(23))
    assert calls == [0, 10, 20]


def test_offset_pages_stops_on_short_page_without_total():
    fetch, _ = make_fetch(23, report_total=False)
    assert list(offset_pages(fetch, page_size=10, start=5)) == list(range(5, 23))


def test_page_cap_raised_on_empty_total_zero_signature():
    fetch, _ = make_fetch(100, cap=30, report_total=False)
    got = []
    with pytest.raises(PageCapReached) as ei:
        for x in offset_pages(fetch, page_size=10):
            got.append(x)
    assert got == list(range(30))
    assert ei.value.offset == 30 and ei.value.items_seen == 30
    assert ei.value.reason == "empty_page_total_zero"


def test_empty_first_page_is_just_empty():
    fetch, _ = make_fetch(0)
    assert list(offset_pages(fetch, page_size=10)) == []


def test_max_offset_raises_instead_of_silent_stop():
    fetch, _ = make_fetch(100, report_total=False)
    with pytest.raises(PageCapReached) as ei:
        list(offset_pages(fetch, page_size=10, max_offset=40))
    assert ei.value.reason == "max_offset" and ei.value.items_seen == 40


def test_max_offset_not_raised_when_total_says_done():
    fetch, _ = make_fetch(40)
    assert len(list(offset_pages(fetch, page_size=10, max_offset=40))) == 40


def test_short_page_below_total_raises():
    fetch, _ = make_fetch(50, server_limit=5)
    with pytest.raises(PageCapReached) as ei:
        list(offset_pages(fetch, page_size=10))
    assert ei.value.reason == "short_page_below_total"
