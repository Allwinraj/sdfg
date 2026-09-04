from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.agents.base import RunContext
from app.agents.ingestor import Ingestor
from app.core.storage import Storage
from app.models.envelope import Envelope
from app.models.pipeline import Node
from app.services.knowledge import load_knowledge
from app.services.parser import ParseError
from tests.unit.ingest_files import DATA_ROWS, POLICY_LINES, write_csv, write_pdf, write_xlsx
from tests.unit.test_knowledge import FakeLLM


def _ctx(tmp_path: Path, config: dict, llm=None) -> RunContext:
    node = Node(id="in1", agent="ingestion", mode=config.get("mode", "data"), config=config)
    return RunContext(
        run_id="run-1",
        llm=llm or FakeLLM(),
        storage=Storage(tmp_path),
        logger=logging.getLogger("test"),
        node=node,
    )


def _env() -> Envelope:
    return Envelope(run_id="run-1", node_id="in1", emitted_by="test")


@pytest.mark.asyncio
@pytest.mark.parametrize("writer,name", [("csv", "d.csv"), ("xlsx", "d.xlsx"), ("pdf", "d.pdf")])
async def test_data_mode_all_formats(tmp_path: Path, writer: str, name: str) -> None:
    path = tmp_path / name
    if writer == "csv":
        write_csv(path, DATA_ROWS)
    elif writer == "xlsx":
        write_xlsx(path, DATA_ROWS)
    else:
        write_pdf(path, [",".join(r) for r in DATA_ROWS])
    ctx = _ctx(tmp_path, {"mode": "data", "path": str(path), "file_id": "src"})
    out = await Ingestor().execute(ctx, _env())
    payload = out[0].payload
    assert payload["kind"] == "data"
    assert payload["schema"][0]["name"] == "Vendor"
    assert out[0].knowledge_context is None
    assert out[0].emitted_by == "ingestion@v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("writer,name", [("csv", "p.csv"), ("xlsx", "p.xlsx"), ("pdf", "p.pdf")])
async def test_knowledge_mode_all_formats(tmp_path: Path, writer: str, name: str) -> None:
    path = tmp_path / name
    if writer == "csv":
        write_csv(path, [["Line"], *[[ln] for ln in POLICY_LINES]])
    elif writer == "xlsx":
        write_xlsx(path, [["Line"], *[[ln] for ln in POLICY_LINES]])
    else:
        write_pdf(path, POLICY_LINES)
    ctx = _ctx(
        tmp_path,
        {"mode": "knowledge", "path": str(path), "file_id": "pol", "session_id": "sess-1"},
    )
    out = await Ingestor().execute(ctx, _env())
    payload = out[0].payload
    assert payload["kind"] == "knowledge"
    assert payload["facts"]
    assert payload["original_path"]
    store = load_knowledge(ctx.storage, "sess-1")
    chunk_id = payload["chunk_ids"][0]
    assert "TOLERANCE" in store.retrieve(chunk_id).text or store.retrieve(chunk_id).heading
    assert out[0].knowledge_context["facts"]


@pytest.mark.asyncio
async def test_schema_overrides_rename(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "d.csv", DATA_ROWS)
    ctx = _ctx(
        tmp_path,
        {
            "mode": "data",
            "path": str(path),
            "schema_overrides": {"Vendor": {"name": "counterparty"}},
        },
    )
    out = await Ingestor().execute(ctx, _env())
    names = [c["name"] for c in out[0].payload["schema"]]
    assert "counterparty" in names
    assert "Vendor" not in out[0].payload["rows"][0]


@pytest.mark.asyncio
async def test_malformed_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"nope")
    ctx = _ctx(tmp_path, {"mode": "data", "path": str(bad)})
    with pytest.raises(ParseError):
        await Ingestor().execute(ctx, _env())
