from __future__ import annotations

from pathlib import Path

import pytest

from app.services.parser import ParseError, parse_file
from tests.unit.ingest_files import DATA_ROWS, POLICY_LINES, write_csv, write_pdf, write_xlsx


def test_csv_xlsx_pdf_data_schema(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "data.csv", DATA_ROWS)
    xlsx_path = write_xlsx(tmp_path / "data.xlsx", DATA_ROWS)
    pdf_path = write_pdf(
        tmp_path / "data.pdf",
        [",".join(row) for row in DATA_ROWS],
    )
    csv_res = parse_file(csv_path)
    xlsx_res = parse_file(xlsx_path)
    pdf_res = parse_file(pdf_path)

    for result in (csv_res, xlsx_res, pdf_res):
        table = result.tables[0]
        names = [c.name for c in table.columns]
        assert names == ["Vendor", "Amount", "Posted"]
        types = {c.name: c.type for c in table.columns}
        assert types["Vendor"] == "string"
        assert types["Amount"] == "decimal"
        assert types["Posted"] == "date"
        assert len(table.rows) == 2
        assert table.rows[0]["Vendor"] == "Acme"


def test_csv_xlsx_pdf_knowledge_keeps_full_text(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "policy.csv", [["Clause"], POLICY_LINES])
    xlsx_path = write_xlsx(tmp_path / "policy.xlsx", [["Clause"], *[[ln] for ln in POLICY_LINES]])
    pdf_path = write_pdf(tmp_path / "policy.pdf", POLICY_LINES)
    for path in (csv_path, xlsx_path, pdf_path):
        result = parse_file(path)
        assert "TOLERANCE POLICY" in result.text
        assert "2 percent" in result.text or "2 percent" in result.text.replace("\n", " ")


def test_malformed_files(tmp_path: Path) -> None:
    (tmp_path / "empty.csv").write_text("", encoding="utf-8")
    (tmp_path / "bad.xlsx").write_bytes(b"not-a-zip")
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    with pytest.raises(ParseError):
        parse_file(tmp_path / "empty.csv")
    with pytest.raises(ParseError):
        parse_file(tmp_path / "bad.xlsx")
    with pytest.raises(ParseError):
        parse_file(tmp_path / "bad.pdf")
    with pytest.raises(ParseError):
        parse_file(tmp_path / "missing.csv")
