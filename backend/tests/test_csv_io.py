"""CSV sniffing, validation and header normalization."""
from __future__ import annotations

from app.csv_io import normalize_headers, read_csv, sniff_text, validate_csv_bytes


def test_sniff_semicolon_delimiter():
    raw = b"a;b;c\n1;2;3\n4;5;6\n7;8;9\n"
    encoding, delim, _warnings = sniff_text(raw)
    assert delim == ";"
    assert encoding.lower().startswith(("utf-8", "iso", "ascii"))


def test_sniff_utf8_bom():
    raw = b"\xef\xbb\xbfa,b\n1,2\n"
    encoding, delim, warnings = sniff_text(raw)
    assert encoding == "utf-8-sig"
    assert delim == ","
    assert any("BOM" in w for w in warnings)


def test_validate_ok_csv():
    raw = b"id,amount,label\n1,10.5,0\n2,20.5,1\n3,30.5,0\n"
    res = validate_csv_bytes(raw, "data.csv")
    assert res.ok
    assert res.status in ("ok", "warning")
    assert res.row_count == 3
    assert res.column_count == 3
    assert res.headers == ["id", "amount", "label"]
    assert len(res.sample_rows) == 3


def test_validate_rejects_non_csv_extension():
    res = validate_csv_bytes(b"a,b\n1,2\n", "book.xlsx")
    assert not res.ok
    assert res.status == "error"


def test_validate_rejects_empty_file():
    res = validate_csv_bytes(b"", "empty.csv")
    assert not res.ok
    assert any("empty" in m.lower() for m in res.messages)


def test_validate_rejects_binary_content():
    res = validate_csv_bytes(b"id,name\x00\x01\x02\n1,zz\n", "bin.csv")
    assert not res.ok
    assert any("binary" in m.lower() for m in res.messages)


def test_validate_rejects_zip_magic_bytes():
    res = validate_csv_bytes(b"PK\x03\x04rest-of-zip", "book.csv")
    assert not res.ok


def test_read_csv_roundtrip():
    raw = b"x,y\n1,2\n3,4\n"
    headers, records = read_csv(raw, delimiter=",", encoding="utf-8")
    assert headers == ["x", "y"]
    assert len(records) == 2
    assert records[0] == {"x": "1", "y": "2"}
    assert records[1] == {"x": "3", "y": "4"}


def test_normalize_headers_unique_and_non_empty():
    out = normalize_headers(["a b", "", "a b", "x"])
    assert out == ["a b", "column_2", "a b_2", "x"]
    assert len(set(h.lower() for h in out)) == len(out)
