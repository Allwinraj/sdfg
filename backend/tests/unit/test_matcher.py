from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from app.agents.base import AgentRegistry, RunContext
from app.agents.ingestor import Ingestor
from app.agents.matcher import Matcher
from app.core.storage import Storage
from app.engine.runner import PipelineRunner
from app.models.envelope import Envelope
from app.models.pipeline import Edge, Node, Pipeline
from tests.unit.ingest_files import write_csv


class NullLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise AssertionError("unused")

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise AssertionError("unused")


class NormalizeLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        return {
            "aliases": [
                {"raw": "ibm corp", "canonical": "ibm"},
                {"raw": "international business machines", "canonical": "ibm"},
            ]
        }


def _tables(*named_rows: tuple[str, list[dict]]) -> list[Envelope]:
    envs = []
    for name, rows in named_rows:
        envs.append(
            Envelope(
                run_id="r",
                node_id=name,
                payload={"kind": "data", "file_id": name, "rows": rows},
                emitted_by="ingestion@v1",
            )
        )
    return envs


def _ctx(config: dict, inputs: list[Envelope], llm=None) -> RunContext:
    return RunContext(
        run_id="r",
        llm=llm or NullLLM(),
        storage=Storage(Path(".")),
        logger=logging.getLogger("test"),
        node=Node(id="m", agent="matcher", mode=config.get("mode", "structural"), config=config),
        inputs=inputs,
    )


async def _run(config, inputs, llm=None):
    return await Matcher().execute(_ctx(config, inputs, llm), inputs[0])


def _by_port(envelopes):
    return {e.port: e.payload["rows"] for e in envelopes}


@pytest.mark.asyncio
async def test_composite_and_multiway() -> None:
    po = _tables(("po", [{"po": "1", "line": "A", "qty": 2}]))
    gr = _tables(("gr", [{"po": "1", "line": "A", "qty": 2}]))
    inv = _tables(("inv", [{"po": "1", "line": "A", "qty": 2}, {"po": "9", "line": "Z", "qty": 1}]))
    inputs = po + gr + inv
    out = _by_port(await _run({"mode": "structural", "keys": ["po", "line"]}, inputs))
    assert len(out["matched"]) == 1
    assert out["matched"][0]["confidence"] == 1.0
    assert len(out["exceptions"]) == 1
    assert out["exceptions"][0]["status"] == "unmatched"


@pytest.mark.asyncio
async def test_windowed_match() -> None:
    bank = _tables(("bank", [{"ref": "X", "date": "2024-01-31", "amount": "10"}]))
    gl = _tables(("gl", [{"ref": "X", "date": "2024-02-02", "amount": "10"}]))
    out = _by_port(
        await _run(
            {"mode": "structural", "keys": ["ref"], "window": {"column": "date", "days": 2}},
            bank + gl,
        )
    )
    assert out["matched"][0]["confidence"] == 0.9
    tight = _by_port(
        await _run(
            {"mode": "structural", "keys": ["ref"], "window": {"column": "date", "days": 1}},
            bank + gl,
        )
    )
    assert "matched" not in tight
    assert tight["exceptions"]


@pytest.mark.asyncio
async def test_dedupe_master_and_audit() -> None:
    src = _tables(
        (
            "vendors",
            [
                {"code": "A", "name": "Acme"},
                {"code": "A", "name": "Acme"},
                {"code": "B", "name": "Beta"},
            ],
        )
    )
    out = _by_port(await _run({"mode": "dedupe", "keys": ["code"]}, src))
    assert len(out["matched"]) == 2
    assert any(r["evidence"][0]["type"] == "dedupe_audit" for r in out["exceptions"])


@pytest.mark.asyncio
async def test_directional() -> None:
    a = _tables(("a", [{"from_entity": "A", "to_entity": "B", "amt": "5", "k": "1"}]))
    b = _tables(("b", [{"from_entity": "B", "to_entity": "A", "amt": "5", "k": "1"}]))
    out = _by_port(
        await _run(
            {
                "mode": "structural",
                "keys": ["k"],
                "flags": {"directional": True},
                "direction_fields": {"from": "from_entity", "to": "to_entity"},
            },
            a + b,
        )
    )
    assert out["matched"][0]["direction"] == "A → B"

    same = _tables(("b2", [{"from_entity": "A", "to_entity": "B", "amt": "5", "k": "1"}]))
    miss = _by_port(
        await _run(
            {
                "mode": "structural",
                "keys": ["k"],
                "flags": {"directional": True},
                "direction_fields": {"from": "from_entity", "to": "to_entity"},
            },
            a + same,
        )
    )
    assert "matched" not in miss


@pytest.mark.asyncio
async def test_allocation_and_residual() -> None:
    pays = _tables(("pay", [{"cust": "C", "amount": "1000"}]))
    invs = _tables(
        (
            "inv",
            [
                {"cust": "C", "amount": "400"},
                {"cust": "C", "amount": "600"},
            ],
        )
    )
    out = _by_port(
        await _run(
            {"flags": {"allocation": True}, "keys": ["cust"], "amount_column": "amount"},
            pays + invs,
        )
    )
    assert out["matched"][0]["allocation"]
    assert len(out["matched"][0]["allocation"]) == 2
    assert "residuals" not in out

    extra = _tables(("pay", [{"cust": "C", "amount": "1200"}]))
    out3 = _by_port(
        await _run(
            {"flags": {"allocation": True}, "keys": ["cust"], "amount_column": "amount"},
            extra + invs,
        )
    )
    assert out3["residuals"][0]["residual"]["amount"] == "200"


@pytest.mark.asyncio
async def test_does_not_apply_amount_tolerance() -> None:
    """$0.02 difference still matches; variance is evidence only."""
    po = _tables(("po", [{"k": "1", "amount": "100.00"}]))
    inv = _tables(("inv", [{"k": "1", "amount": "100.02"}]))
    out = _by_port(
        await _run(
            {"mode": "structural", "keys": ["k"], "amount_column": "amount"},
            po + inv,
        )
    )
    assert out["matched"][0]["status"] == "matched"
    assert out["matched"][0]["variance"]["delta"] == "-0.02"


@pytest.mark.asyncio
async def test_semantic_normalization() -> None:
    left = _tables(("erp_a", [{"k": "1", "vendor": "IBM Corp"}]))
    right = _tables(("erp_b", [{"k": "1", "vendor": "International Business Machines"}]))
    out = _by_port(
        await _run(
            {
                "mode": "semantic",
                "keys": ["vendor"],
                "normalize_fields": ["vendor"],
                "confidence_threshold": 0.8,
            },
            left + right,
            llm=NormalizeLLM(),
        )
    )
    assert out["matched"][0]["status"] == "matched"


@pytest.mark.asyncio
async def test_keyless_distinct_guard() -> None:
    a = _tables(("a", [{"name": "Acme LLC", "tax_id": "1", "address": "1 Main"}]))
    b = _tables(("b", [{"name": "Acme LLC", "tax_id": "2", "address": "1 Main"}]))
    out = _by_port(
        await _run(
            {
                "flags": {"keyless": True, "distinct_guard": True},
                "identity_fields": ["name", "address"],
                "distinct_fields": ["tax_id"],
            },
            a + b,
        )
    )
    assert out["exceptions"][0]["status"] == "distinct"


@pytest.mark.asyncio
async def test_reversal_relationship() -> None:
    left = _tables(("a", [{"k": "1", "amount": "50"}]))
    right = _tables(("b", [{"k": "1", "amount": "-50"}]))
    out = _by_port(
        await _run(
            {"mode": "structural", "keys": ["k"], "flags": {"reversal": True}, "amount_column": "amount"},
            left + right,
        )
    )
    assert out["matched"][0]["relationship"] == "reversal"


@pytest.mark.asyncio
async def test_runner_port_routing(tmp_path: Path) -> None:
    p1 = write_csv(tmp_path / "a.csv", [["k", "v"], ["1", "x"]])
    p2 = write_csv(tmp_path / "b.csv", [["k", "v"], ["1", "y"], ["2", "z"]])
    pipeline = Pipeline(
        id="mports",
        nodes=[
            Node(id="i1", agent="ingestion", config={"mode": "data", "path": str(p1)}),
            Node(id="i2", agent="ingestion", config={"mode": "data", "path": str(p2)}),
            Node(id="m", agent="matcher", config={"mode": "structural", "keys": ["k"]}),
            Node(id="ok", agent="math", config={"mode": "calculation", "ast": "1 + 1", "output_column": "n"}),
        ],
        edges=[
            Edge(id="e1", source="i1", target="m"),
            Edge(id="e2", source="i2", target="m"),
            Edge(id="e3", source="m", source_port="matched", target="ok"),
        ],
    )
    registry = AgentRegistry()
    from app.agents.math_engine import MathEngine

    registry.register(Ingestor)
    registry.register(Matcher)
    registry.register(MathEngine)
    runner = PipelineRunner(registry, Storage(tmp_path), NullLLM())
    run = await runner.run(pipeline)
    by = {s.node_id: s for s in run.steps}
    assert by["m"].status == "ok"
    assert any(e.port == "matched" for e in by["m"].outputs)
    assert any(e.port == "exceptions" for e in by["m"].outputs)
    assert by["ok"].status == "ok"


@pytest.mark.asyncio
async def test_keys_bind_aliases_and_date_window() -> None:
    left = _tables(
        (
            "bank",
            [
                {"amount": "10", "reference_number": "R1", "date": "2024-01-01"},
                {"amount": "10", "reference_number": "R1", "date": "2024-01-10"},
            ],
        )
    )
    right = _tables(("gl", [{"Amount": "10", "ref": "R1", "posted": "2024-01-02"}]))
    out = _by_port(
        await _run(
            {
                "mode": "structural",
                "keys": ["amount", "reference_number"],
                "window_days": 2,
            },
            left + right,
        )
    )
    assert len(out["matched"]) == 1
    assert out["matched"][0]["amount"] in {"10", 10} or str(out["matched"][0]["amount"]) == "10"
    assert out["matched"][0]["reference_number"] == "R1"
    assert len(out["exceptions"]) == 1


@pytest.mark.asyncio
async def test_math_runs_on_flattened_matches() -> None:
    from app.agents.math_engine import MathEngine

    left = _tables(("a", [{"actual": "30", "po": "1"}]))
    right = _tables(("b", [{"budget": "20", "po_number": "1"}]))
    matched = await _run({"mode": "structural", "keys": ["po"]}, left + right)
    rows = matched[0].payload["rows"]
    ctx = RunContext(
        run_id="r",
        llm=NullLLM(),
        storage=Storage(Path(".")),
        logger=logging.getLogger("test"),
        node=Node(
            id="math",
            agent="math",
            config={"mode": "calculation", "catalog_id": "variance_amount", "output_column": "variance_amount"},
        ),
        inputs=matched,
    )
    env = Envelope(
        run_id="r",
        node_id="m",
        port="matched",
        payload={"kind": "matches", "rows": rows},
        emitted_by="matcher@v1",
    )
    out = await MathEngine().execute(ctx, env)
    assert out[0].payload["rows"][0]["variance_amount"] == Decimal("10.00")

