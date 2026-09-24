from kbkit import io as kio


def test_read_text_utf8_bom_and_cp1252(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes("\ufeffcaf\u00e9".encode("utf-8"))
    assert kio.read_text(a) == "caf\u00e9"
    b = tmp_path / "b.txt"
    b.write_bytes(b"caf\xe9 \x93q\x94 \x81")
    assert kio.read_text(b) == "caf\u00e9 \u201cq\u201d \ufffd"


def test_utf8_stdout_is_safe_to_call():
    kio.utf8_stdout()
    kio.utf8_stdout()


def test_tee_writes_file_and_echoes(tmp_path, capsys):
    p = tmp_path / "r.txt"
    with kio.Tee(p) as out:
        out("rows:", 3)
        out.write("caf\u00e9\n")
    assert p.read_text(encoding="utf-8").splitlines() == ["rows: 3", "caf\u00e9"]
    assert "rows: 3" in capsys.readouterr().out
