from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.base import AgentRegistry
from app.agents.decision import Decision
from app.agents.exporter import Exporter
from app.agents.ingestor import Ingestor
from app.agents.matcher import Matcher
from app.agents.math_engine import MathEngine
from app.core.storage import Storage
from app.engine.persist import load_run
from app.engine.runner import PipelineRunner
from app.models.envelope import Envelope
from app.models.pipeline import Edge, Node, Pipeline
from app.services.exporter import (
    collect_streams,
    inspect_pdf,
    inspect_workbook,
    resolve_theme,
    write_pdf,
    write_workbook,
)
from tests.unit.ingest_files import write_csv

GOLDENS = Path(__file__).parent / "goldens" / "exporter_themes.json"


class NullLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise AssertionError("unused")

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise AssertionError("unused")


class ApproveLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        return {
            "verdict": "approved",
            "confidence": 0.96,
            "explanation": "Within policy.",
            "remediation": "None",
        }


def _streams_envs() -> list[Envelope]:
    return [
        Envelope(
            run_id="r",
            node_id="m",
            port="matched",
            payload={
                "kind": "matches",
                "rows": [
                    {"vendor": "Acme", "amount": 100.0, "status": "matched", "variance": 2.0},
                    {"vendor": "Globex", "amount": 80.0, "status": "matched", "variance": 5.5},
                ],
            },
            emitted_by="matcher@v1",
        ),
        Envelope(
            run_id="r",
            node_id="m",
            port="exceptions",
            payload={
                "kind": "matches",
                "rows": [{"vendor": "Initech", "amount": 12.0, "status": "unmatched", "variance": 40.0}],
            },
            emitted_by="matcher@v1",
        ),
    ]


def test_theme_workbook_and_pdf_goldens() -> None:
    expected = json.loads(GOLDENS.read_text(encoding="utf-8"))
    streams = collect_streams(
        _streams_envs(),
        {"tabs": {"matched": "Matched Transactions", "exceptions": "Exception Audit"}},
    )
    for theme_id, meta in expected.items():
        theme = resolve_theme(theme_id)
        xlsx = write_workbook(streams, theme=theme, title="Month-end pack")
        info = inspect_workbook(xlsx)
        names = [s["name"] for s in info["sheets"]]
        assert names[0] == "Executive Summary"
        assert "Matched Transactions" in names
        assert "Exception Audit" in names
        assert all(s["freeze"] == "A2" for s in info["sheets"])
        assert any(f.startswith("=SUM(") for s in info["sheets"] for f in s["formulas"])
        assert meta["header"].upper() in info["header_fills"]
        pdf = write_pdf(streams, theme=theme, title="Month-end pack")
        text = inspect_pdf(pdf)["text"]
        assert theme.label in text
        assert "Sign-off" in text
        assert "Prepared by" in text


def test_multi_stream_tabs_and_formulas() -> None:
    streams = collect_streams(_streams_envs(), {})
    info = inspect_workbook(write_workbook(streams, theme=resolve_theme("audit"), title="A"))
    data_sheet = next(s for s in info["sheets"] if s["name"] != "Executive Summary")
    assert data_sheet["formulas"]
    assert data_sheet["max_row"] >= 3


@pytest.mark.asyncio
async def test_sparse_ingest_to_exporter(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "vendors.csv",
        [["Vendor", "Amount"], ["Acme", "12.50"], ["Globex", "80"]],
    )
    pipeline = Pipeline(
        id="sparse-out",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(
                id="out",
                agent="output",
                config={
                    "mode": "both",
                    "theme": "executive_classic",
                    "title": "Vendor dump",
                    "filename": "vendors",
                },
            ),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Exporter)
    store = Storage(tmp_path)
    run = await PipelineRunner(registry, store, NullLLM()).run(pipeline)
    assert run.status == "completed"
    assert [s.agent for s in run.steps] == ["ingestion", "output"]
    out = next(s for s in run.steps if s.agent == "output")
    assert out.outputs[0].emitted_by == "output@v1"
    arts = out.outputs[0].payload["artifacts"]
    assert arts == run.artifacts
    for rel in arts:
        assert store.exists(*rel.split("/"))
    saved = load_run(store, run.id)
    assert saved.artifacts == run.artifacts
    xlsx_rel = next(a for a in arts if a.endswith(".xlsx"))
    pdf_rel = next(a for a in arts if a.endswith(".pdf"))
    xlsx = store.path(*xlsx_rel.split("/")).read_bytes()
    pdf = store.path(*pdf_rel.split("/")).read_bytes()
    assert "Vendor dump" in inspect_pdf(pdf)["text"]
    assert "Executive Summary" in [s["name"] for s in inspect_workbook(xlsx)["sheets"]]


@pytest.mark.asyncio
async def test_full_chain_emitted_by(tmp_path: Path) -> None:
    left = write_csv(tmp_path / "a.csv", [["k", "amount"], ["1", "30"], ["2", "8"]])
    right = write_csv(tmp_path / "b.csv", [["k", "amount"], ["1", "20"], ["2", "10"]])
    pipeline = Pipeline(
        id="full-chain",
        nodes=[
            Node(id="i1", agent="ingestion", config={"mode": "data", "path": str(left)}),
            Node(id="i2", agent="ingestion", config={"mode": "data", "path": str(right)}),
            Node(id="m", agent="matcher", config={"mode": "structural", "keys": ["k"]}),
            Node(
                id="math",
                agent="math",
                config={"mode": "calculation", "ast": "1 + 1", "output_column": "n"},
            ),
            Node(
                id="dec",
                agent="decision",
                config={"mode": "approval", "authority": "autonomous", "confidence_threshold": 0.85},
            ),
            Node(
                id="out",
                agent="output",
                config={"formats": ["xlsx", "pdf"], "theme": "modern_slate", "filename": "full"},
            ),
        ],
        edges=[
            Edge(id="e1", source="i1", target="m"),
            Edge(id="e2", source="i2", target="m"),
            Edge(id="e3", source="m", source_port="matched", target="math"),
            Edge(id="e4", source="math", target="dec"),
            Edge(id="e5", source="dec", source_port="approved", target="out"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Matcher)
    registry.register(MathEngine)
    registry.register(Decision)
    registry.register(Exporter)
    store = Storage(tmp_path)
    run = await PipelineRunner(registry, store, ApproveLLM()).run(pipeline)
    assert run.status == "completed"
    by = {s.node_id: s for s in run.steps}
    assert by["i1"].outputs[0].emitted_by == "ingestion@v1"
    assert by["m"].outputs[0].emitted_by == "matcher@v1"
    assert by["math"].outputs[0].emitted_by == "math@v1"
    assert by["dec"].outputs[0].emitted_by == "decision@v1"
    assert by["out"].outputs[0].emitted_by == "output@v1"
    assert run.artifacts
    assert store.exists(*run.artifacts[0].split("/"))


@pytest.mark.asyncio
async def test_two_output_nodes(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", [["a"], ["1"]])
    pipeline = Pipeline(
        id="dual-out",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(id="xl", agent="output", config={"mode": "excel", "filename": "ops"}),
            Node(id="pdf", agent="output", config={"mode": "pdf", "filename": "cfo"}),
        ],
        edges=[
            Edge(id="e1", source="in", target="xl"),
            Edge(id="e2", source="in", target="pdf"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    suffixes = sorted(Path(a).suffix for a in run.artifacts)
    assert suffixes == [".pdf", ".xlsx"]


def test_mode_wins_over_stale_formats_list() -> None:
    from app.services.exporter import format_output_label, resolve_output_formats

    assert resolve_output_formats({"mode": "pdf", "formats": ["xlsx"]}) == ["pdf"]
    assert resolve_output_formats({"mode": "both", "formats": ["xlsx"]}) == ["xlsx", "pdf"]
    assert resolve_output_formats({"formats": ["excel", "pdf"]}) == ["xlsx", "pdf"]
    assert resolve_output_formats({}, node_mode="pdf") == ["pdf"]
    assert format_output_label(["pdf"]) == "PDF"
    assert format_output_label(["xlsx", "pdf"]) == "Excel+PDF"


@pytest.mark.asyncio
async def test_ingest_output_pdf_only(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", [["Vendor"], ["Acme"]])
    pipeline = Pipeline(
        id="pdf-only",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(id="out", agent="output", mode="pdf", config={"mode": "pdf", "filename": "pack"}),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    suffixes = [Path(a).suffix for a in run.artifacts]
    assert suffixes == [".pdf"]
    assert "output" in {s.agent for s in run.steps}


@pytest.mark.asyncio
async def test_ingest_output_both(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", [["Vendor"], ["Acme"]])
    pipeline = Pipeline(
        id="both-out",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(id="out", agent="output", mode="both", config={"mode": "both", "filename": "pack"}),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    assert sorted(Path(a).suffix for a in run.artifacts) == [".pdf", ".xlsx"]


@pytest.mark.asyncio
async def test_pdf_mode_ignores_stale_xlsx_formats(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", [["a"], ["1"]])
    pipeline = Pipeline(
        id="disagree",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(
                id="out",
                agent="output",
                mode="pdf",
                config={"mode": "pdf", "formats": ["xlsx"], "filename": "cfo"},
            ),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    assert [Path(a).suffix for a in run.artifacts] == [".pdf"]


@pytest.mark.asyncio
async def test_ingest_math_output_excel(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "ba.csv", [["actual", "budget"], ["30", "20"]])
    pipeline = Pipeline(
        id="math-out",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(
                id="m",
                agent="math",
                config={"mode": "calculation", "catalog_id": "variance_amount", "output_column": "variance_amount"},
            ),
            Node(id="out", agent="output", config={"mode": "excel", "filename": "var"}),
        ],
        edges=[
            Edge(id="e1", source="in", target="m"),
            Edge(id="e2", source="m", target="out"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(MathEngine)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    assert run.status == "completed"
    assert [Path(a).suffix for a in run.artifacts] == [".xlsx"]
    math = next(s for s in run.steps if s.agent == "math")
    assert math.status == "ok"


@pytest.mark.asyncio
async def test_matcher_exceptions_reach_output_without_math(tmp_path: Path) -> None:
    left = write_csv(tmp_path / "a.csv", [["k", "amount"], ["1", "10"]])
    right = write_csv(tmp_path / "b.csv", [["k", "amount"], ["9", "99"]])
    pipeline = Pipeline(
        id="match-out",
        nodes=[
            Node(id="i1", agent="ingestion", config={"mode": "data", "path": str(left)}),
            Node(id="i2", agent="ingestion", config={"mode": "data", "path": str(right)}),
            Node(id="m", agent="matcher", config={"mode": "structural", "keys": ["k"]}),
            Node(id="out", agent="output", config={"mode": "excel", "filename": "ex"}),
        ],
        edges=[
            Edge(id="e1", source="i1", target="m"),
            Edge(id="e2", source="i2", target="m"),
            Edge(id="e3", source="m", source_port="matched", target="out"),
            Edge(id="e4", source="m", source_port="exceptions", target="out"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Matcher)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    assert run.status == "completed"
    match = next(s for s in run.steps if s.agent == "matcher")
    ports = {e.port for e in match.outputs}
    assert "exceptions" in ports or "matched" in ports
    assert run.artifacts


@pytest.mark.asyncio
async def test_full_chain_decision_without_policy_skips_llm(tmp_path: Path) -> None:
    left = write_csv(tmp_path / "a.csv", [["k", "amount"], ["1", "30"]])
    right = write_csv(tmp_path / "b.csv", [["k", "amount"], ["1", "20"]])
    pipeline = Pipeline(
        id="rules-dec",
        nodes=[
            Node(id="i1", agent="ingestion", config={"mode": "data", "path": str(left)}),
            Node(id="i2", agent="ingestion", config={"mode": "data", "path": str(right)}),
            Node(id="m", agent="matcher", config={"mode": "structural", "keys": ["k"]}),
            Node(id="math", agent="math", config={"mode": "calculation", "ast": "1 + 1", "output_column": "n"}),
            Node(id="dec", agent="decision", config={"mode": "approval", "authority": "autonomous"}),
            Node(id="out", agent="output", config={"mode": "both", "filename": "pack"}),
        ],
        edges=[
            Edge(id="e1", source="i1", target="m"),
            Edge(id="e2", source="i2", target="m"),
            Edge(id="e3", source="m", source_port="matched", target="math"),
            Edge(id="e4", source="math", target="dec"),
            Edge(id="e5", source="m", source_port="exceptions", target="dec"),
            Edge(id="e6", source="dec", source_port="approved", target="out"),
            Edge(id="e7", source="dec", source_port="flagged", target="out"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(Matcher)
    registry.register(MathEngine)
    registry.register(Decision)
    registry.register(Exporter)
    run = await PipelineRunner(registry, Storage(tmp_path), NullLLM()).run(pipeline)
    assert run.status == "completed"
    assert {s.node_id: s.status for s in run.steps}["dec"] == "ok"
    assert sorted(Path(a).suffix for a in run.artifacts) == [".pdf", ".xlsx"]
