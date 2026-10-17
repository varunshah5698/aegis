"""CSV validation and safe parsing (spec #4.2).

Never trusts the filename or browser MIME type: we sniff the magic bytes,
detect encoding and delimiter, then parse with the stdlib csv module in a
bounded way so malformed files fail with descriptive messages instead of
crashing the worker.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

import chardet

from . import config

DELIMITER_CANDIDATES = [",", ";", "\t", "|"]
BAD_EXT_MSG = "File must have a .csv extension and contain delimited text."


@dataclass
class ValidationResult:
    ok: bool
    status: str                       # ok | warning | error
    delimiter: str = ","
    encoding: str = "utf-8"
    row_count: int = 0
    column_count: int = 0
    headers: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)   # human readable
    warnings: list[str] = field(default_factory=list)
    sample_rows: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "headers": self.headers,
            "messages": self.messages,
            "warnings": self.warnings,
            "sample_rows": self.sample_rows,
        }


def sniff_text(raw: bytes) -> tuple[str, str, list[str]]:
    """Return (encoding, delimiter, warnings) from raw bytes."""
    warnings: list[str] = []

    # BOM detection first — chardet sometimes mislabels BOM files.
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
        warnings.append("File starts with a UTF-8 BOM; it was stripped during parsing.")
    else:
        detected = chardet.detect(raw[:200_000]) or {}
        encoding = detected.get("encoding") or "utf-8"
        conf = float(detected.get("confidence") or 0)
        if conf < 0.5:
            warnings.append(
                f"Encoding detection was uncertain (detected {encoding}, confidence {conf:.0%}); "
                "override it if columns look garbled."
            )
        if encoding.lower() in ("utf-16", "utf-16-le", "utf-16-be"):
            warnings.append("UTF-16 encoded CSVs are parsed but may be slow for very large files.")

    try:
        text = raw[:512_000].decode(encoding, errors="replace")
    except LookupError:
        encoding = "utf-8"
        text = raw[:512_000].decode("utf-8", errors="replace")

    if text.count("\ufffd") > 20:
        warnings.append("Some bytes could not be decoded and were replaced with the U+FFFD character.")

    # Delimiter sniffing: pick the candidate with the most consistent counts.
    sample = text[:200_000]
    best, best_score = ",", -1.0
    for cand in DELIMITER_CANDIDATES:
        lines = [ln for ln in sample.splitlines()[:60] if ln.strip()]
        if not lines:
            continue
        counts = [ln.count(cand) for ln in lines]
        if not any(counts):
            continue
        first = counts[0]
        if first == 0:
            continue
        consistency = sum(1 for c in counts if c == first) / len(counts)
        score = consistency * min(first, 30)
        if score > best_score:
            best, best_score = cand, score

    if best == "\t":
        warnings.append("Tab delimiter detected.")
    return encoding, best, warnings


def validate_csv_bytes(raw: bytes, filename: str) -> ValidationResult:
    """Validate raw upload bytes and return a structured result."""
    res = ValidationResult(ok=False, status="error")

    if not filename.lower().endswith(".csv"):
        res.messages.append(BAD_EXT_MSG)
        return res

    if len(raw) == 0:
        res.messages.append("The file is empty (0 bytes).")
        return res

    # Magic-byte / binary guard: reject files that are clearly not text.
    head = raw[:4096]
    if b"\x00" in head:
        res.messages.append(
            "This does not look like a CSV file: binary data (null bytes) was found in the header. "
            "Excel workbooks (.xlsx) must be exported as CSV first."
        )
        return res
    if head.startswith(b"PK\x03\x04"):
        res.messages.append("This is a ZIP-based file (.xlsx/.zip). Export it as CSV and upload again.")
        return res

    if len(raw) > config.MAX_UPLOAD_BYTES:
        res.messages.append(
            f"File is larger than the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
        )
        return res

    encoding, delimiter, sniff_warnings = sniff_text(raw)
    res.encoding = encoding
    res.delimiter = delimiter
    res.warnings.extend(sniff_warnings)

    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
        res.encoding = "utf-8"

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)

    try:
        rows = []
        malformed = 0
        for i, row in enumerate(reader):
            if i > config.MAX_ROWS + 5:
                res.messages.append(
                    f"File exceeds the {config.MAX_ROWS:,} row limit for this deployment."
                )
                return res
            rows.append(row)
    except csv.Error as exc:
        res.messages.append(f"CSV parsing failed: {exc}")
        return res

    if not rows:
        res.messages.append("No rows found in the file.")
        return res

    headers = [h.strip() for h in rows[0]]
    data_rows = rows[1:]

    # Drop fully empty trailing rows (common export artifact).
    while data_rows and not any(c.strip() for c in data_rows[-1]):
        data_rows.pop()
        res.warnings.append("Trailing empty rows were ignored.")

    if not any(headers):
        res.messages.append("The first row does not contain any column names.")
        return res

    width = len(headers)
    ragged = 0
    for r in data_rows:
        if len(r) != width:
            ragged += 1
    if ragged:
        pct = ragged / max(len(data_rows), 1)
        msg = (
            f"{ragged:,} of {len(data_rows):,} rows have a different number of fields than the header "
            f"({pct:.1%}); short rows were padded and long rows truncated during parsing."
        )
        if pct > 0.2:
            res.messages.append(msg + " The delimiter may be wrong — try overriding it.")
        else:
            res.warnings.append(msg)

    # Duplicate headers
    seen: dict[str, int] = {}
    for h in headers:
        key = h.lower() or "(empty)"
        seen[key] = seen.get(key, 0) + 1
    dups = sorted({h for h, c in seen.items() if c > 1})
    if dups:
        res.warnings.append(
            f"Duplicate column names detected: {', '.join(dups[:6])}. "
            "They will be renamed with numeric suffixes."
        )

    empty_header_idx = [i for i, h in enumerate(headers) if not h.strip()]
    if empty_header_idx:
        res.warnings.append(
            f"{len(empty_header_idx)} column(s) have no header name and were named 'column_N'."
        )

    if len(data_rows) == 0:
        res.messages.append("The file has a header row but no data rows.")
        return res

    if len(data_rows) > config.MAX_ROWS:
        res.messages.append(f"File exceeds the {config.MAX_ROWS:,} row limit.")
        return res

    if width > config.MAX_COLUMNS:
        res.messages.append(f"File exceeds the {config.MAX_COLUMNS} column limit.")
        return res

    res.ok = True
    res.status = "warning" if res.warnings else "ok"
    res.headers = headers
    res.row_count = len(data_rows)
    res.column_count = width
    res.sample_rows = data_rows[: config.PREVIEW_ROWS]
    if malformed:
        res.warnings.append(f"{malformed} malformed records were repaired during parsing.")
    return res


def normalize_headers(headers: list[str]) -> list[str]:
    """Make headers unique, non-empty and safe identifiers."""
    out: list[str] = []
    counts: dict[str, int] = {}
    for i, h in enumerate(headers):
        name = re.sub(r"\s+", " ", (h or "").strip()) or f"column_{i + 1}"
        base = name
        if name.lower() in counts:
            counts[name.lower()] += 1
            name = f"{base}_{counts[name.lower()]}"
        else:
            counts[name.lower()] = 1
        out.append(name)
    return out


def read_csv(raw: bytes, delimiter: str = ",", encoding: str = "utf-8"):
    """Parse validated bytes into a list of dict rows with normalized headers."""
    text = raw.decode(encoding, errors="replace")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        rows = list(reader)
    except csv.Error:
        rows = []
    if not rows:
        return [], []
    headers = normalize_headers([h.strip() for h in rows[0]])
    width = len(headers)
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        if len(r) < width:
            r = r + [""] * (width - len(r))
        elif len(r) > width:
            r = r[:width]
        out.append(dict(zip(headers, r)))
    return headers, out
