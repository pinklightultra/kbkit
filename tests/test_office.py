import io
import zipfile

from kbkit import office

WNS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')


def build_docx():
    doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document {WNS}><w:body>
  <w:p><w:r><w:t>Hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>
  <w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p>
  <w:p><w:del><w:r><w:delText>gone</w:delText></w:r></w:del><w:r><w:t>kept</w:t></w:r></w:p>
  <w:p><w:r><w:sym w:font="Wingdings" w:char="F0FC"/></w:r></w:p>
  <w:p><w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:checkBox><w:default w:val="0"/>
       <w:checked/></w:checkBox></w:ffData></w:fldChar></w:r><w:r><w:t> Legacy yes</w:t></w:r></w:p>
  <w:sdt><w:sdtPr><w14:checkbox><w14:checked w14:val="0"/></w14:checkbox></w:sdtPr>
    <w:sdtContent><w:p><w:r><w:t> Modern no</w:t></w:r></w:p></w:sdtContent></w:sdt>
  <w:tbl><w:tr><w:tc><w:p><w:r><w:t>k1</w:t></w:r></w:p></w:tc>
             <w:tc><w:p><w:r><w:t>v1</w:t></w:r></w:p><w:p><w:r><w:t>v2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  <w:p/>
</w:body></w:document>"""
    header = f'<w:hdr {WNS}><w:p><w:r><w:t>Header text</w:t></w:r></w:p></w:hdr>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/header1.xml", header)
        z.writestr("word/styles.xml", f"<w:styles {WNS}/>")
    return buf.getvalue()


def test_docx_text():
    text = office.docx_text(build_docx())
    assert text.split("\n") == [
        "Hello world",
        "A\tB",
        "C",
        "[deleted: gone]kept",
        "[sym:F0FC]",
        "[x] Legacy yes",
        "[ ] Modern no",
        "k1 | v1 / v2",
        "",
        "Header text",
    ]


def test_docx_deleted_modes_and_path(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(build_docx())
    assert "gone" not in office.docx_text(str(p), deleted="drop")
    assert "gonekept" in office.docx_text(p, deleted="keep")
    assert list(office.docx_parts(p)) == ["word/document.xml", "word/header1.xml"]


SNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def build_xlsx():
    wb = f"""<workbook {SNS} {RNS}><sheets>
      <sheet name="Data" sheetId="1" r:id="rId1"/>
      <sheet name="Secret" sheetId="2" state="hidden" r:id="rId2"/>
    </sheets></workbook>"""
    rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/>
      <Relationship Id="rId2" Type="ws" Target="/xl/worksheets/sheet2.xml"/>
    </Relationships>"""
    sst = f"""<sst {SNS}><si><t>Name</t></si><si><r><t>Ac</t></r><r><t>me</t></r>
      <rPh><t>phonetic</t></rPh></si></sst>"""
    s1 = f"""<worksheet {SNS}><sheetData>
      <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>42</v></c></row>
      <row r="3"><c r="A3" t="s"><v>1</v></c><c r="B3" t="b"><v>1</v></c>
                 <c r="C3" t="inlineStr"><is><t>inline</t></is></c></row>
    </sheetData></worksheet>"""
    s2 = f'<worksheet {SNS}><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", s1)
        z.writestr("xl/worksheets/sheet2.xml", s2)
    return buf.getvalue()


def test_xlsx_rows_and_sheets():
    data = build_xlsx()
    assert office.xlsx_sheets(data) == [{"name": "Data", "state": "visible"},
                                        {"name": "Secret", "state": "hidden"}]
    rows = office.xlsx_rows(data)
    assert rows["Data"] == [["Name", "", "42"], [], ["Acme", "TRUE", "inline"]]
    assert rows["Secret"] == [["7"]]
