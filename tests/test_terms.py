from kbkit.terms import TermList


def test_word_boundary_not_substring():
    tl = TermList(["Scan"])
    assert tl.find("Scanned and rescanned") == []
    assert tl.find("a SCAN run") == [("Scan", 2, 6)]


def test_case_sensitive_option():
    tl = TermList(["Acme"], case_sensitive=True)
    assert tl.find("acme Acme") == [("Acme", 5, 9)]


def test_longest_match_first_and_punctuation():
    tl = TermList(["Acme", "Acme Health", "C++", "A.B."])
    text = "Acme Health uses C++ and A.B. but not Acme's C++x"
    assert [h[0] for h in tl.find(text)] == ["Acme Health", "C++", "A.B.", "Acme"]


def test_whitespace_in_term_matches_any_whitespace():
    tl = TermList(["Acme Health"])
    assert tl.find("Acme\u00a0Health") and tl.find("Acme\nHealth")


def test_report_wording_and_no_clean_attribute():
    tl = TermList(["Acme", "Globex", "Initech"])
    rep = tl.report(["Acme here", "nothing", "Globex and Acme", ""])
    assert str(rep) == "2 listed terms found in 2 of 4 texts"
    assert rep.counts == {"Acme": 2, "Globex": 1}
    assert not hasattr(rep, "clean") and not hasattr(rep, "is_clean")
    try:
        rep.clean = True
    except AttributeError:
        pass
    else:
        raise AssertionError("TermReport must not accept a clean attribute")


def test_report_mapping_ids():
    rep = TermList(["Acme"]).report({"doc-a": "x", "doc-b": "Acme"})
    assert list(rep.per_text) == ["doc-b"]
    assert str(rep) == "1 listed terms found in 1 of 2 texts"
