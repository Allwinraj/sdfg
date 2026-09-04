from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    path.write_text(
        "\n".join(",".join(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def write_xlsx(path: Path, rows: list[list[object]], sheet: str = "Sheet1") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


def write_pdf(path: Path, lines: list[str]) -> Path:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT /F1 11 Tf 50 740 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append("0 -14 Td")
        ops.append(f"({esc(line)}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")

    def obj(n: int, body: bytes) -> bytes:
        return f"{n} 0 obj\n".encode() + body + b"\nendobj\n"

    objects = [
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        obj(4, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"),
        obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    header = b"%PDF-1.4\n"
    offsets = []
    body = b""
    cursor = len(header)
    for block in objects:
        offsets.append(cursor)
        body += block
        cursor += len(block)
    xref_pos = len(header) + len(body)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for off in offsets:
        xref.append(f"{off:010d} 00000 n \n".encode())
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        + f"startxref\n{xref_pos}\n".encode()
        + b"%%EOF\n"
    )
    path.write_bytes(header + body + b"".join(xref) + trailer)
    return path


DATA_ROWS = [
    ["Vendor", "Amount", "Posted"],
    ["Acme", "12.50", "2024-01-15"],
    ["Globex", "80", "2024-01-16"],
]

POLICY_LINES = [
    "TOLERANCE POLICY",
    "Variance of 2 percent or 50 is acceptable.",
    "APPROVAL RULES",
    "Invoices without receipt under 500 may auto-approve for tier-1 vendors.",
]
