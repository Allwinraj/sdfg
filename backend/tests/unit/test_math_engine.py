from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from app.agents.base import AgentRegistry, RunContext
from app.agents.ingestor import Ingestor
from app.agents.math_engine import MathEngine
from app.core.llm import LLMError
from app.core.storage import Storage
from app.engine.runner import PipelineRunner
from app.models.envelope import Envelope
from app.models.pipeline import Edge, Node, Pipeline
from tests.unit.ingest_files import write_csv


class NullLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise AssertionError("not used")

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise AssertionError("compile should use catalog_id or ast")


class CatalogLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        return {
            "catalog_id": "variance_amount",
            "ast": "actual - budget",
            "gate_ast": "",
            "shape": "per_row",
            "output": "variance_amount",
            "mode": "calculation",
        }


class AstFallbackLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        return {
            "catalog_id": "",
            "ast": "a + b",
            "shape": "per_row",
            "output": "total",
            "mode": "calculation",
        }


def _ctx(config: dict, llm=None, rows=None) -> RunContext:
    env_rows = rows or []
    node = Node(id="math1", agent="math", mode=config.get("mode", "calculation"), config=config)
    env = Envelope(run_id="r", node_id="math1", payload={"rows": env_rows}, emitted_by="test")
    ctx = RunContext(
        run_id="r",
        llm=llm or NullLLM(),
        storage=Storage(Path(".")),
        logger=logging.getLogger("test"),
        node=node,
        inputs=[env],
    )
    return ctx, env


@pytest.mark.asyncio
async def test_decimal_no_float_drift() -> None:
    ctx, env = _ctx(
        {"mode": "calculation", "ast": "a + b", "output_column": "sum", "precision": 2},
        rows=[{"a": "0.1", "b": "0.2"}],
    )
    out = await MathEngine().execute(ctx, env)
    assert out[0].payload["rows"][0]["sum"] == Decimal("0.30")


@pytest.mark.asyncio
async def test_empty_zero_budget_skips_pct() -> None:
    ctx, env = _ctx(
        {
            "mode": "calculation",
            "catalog_id": "variance_pct",
            "input_map": {"variance_amount": "var", "budget": "budget"},
            "empty_rule": {"on": "budget", "when": "zero_or_missing", "result": "—"},
        },
        rows=[{"var": "10", "budget": "0"}, {"var": "10", "budget": "100"}],
    )
    rows = (await MathEngine().execute(ctx, env))[0].payload["rows"]
    assert rows[0]["variance_pct"] == "—"
    assert rows[0]["skipped"] is True
    assert rows[1]["variance_pct"] == Decimal("0.10")
    assert "error" not in rows[0]


@pytest.mark.asyncio
async def test_gate_and_or_truth() -> None:
    ctx, env = _ctx(
        {
            "mode": "rule",
            "ast": "(amount > 10000 and category == 'travel') or amount > 50000",
            "output_column": "flag",
        },
        rows=[
            {"amount": "12000", "category": "travel"},
            {"amount": "12000", "category": "office"},
            {"amount": "60000", "category": "office"},
        ],
    )
    flags = [r["flag"] for r in (await MathEngine().execute(ctx, env))[0].payload["rows"]]
    assert flags == [True, False, True]


@pytest.mark.asyncio
async def test_min_pct_amount_tolerance_gate() -> None:
    ctx, env = _ctx(
        {
            "mode": "hybrid",
            "catalog_id": "min_pct_amount_tolerance",
            "input_map": {"actual": "invoice", "expected": "po"},
            "constants": {"pct": "0.02", "amount": "50"},
            "precision": 2,
        },
        rows=[
            {"invoice": "102", "po": "100"},
            {"invoice": "200", "po": "100"},
        ],
    )
    rows = (await MathEngine().execute(ctx, env))[0].payload["rows"]
    # min(2, 50)=2; |102-100|=2 not greater; |200-100|=100 greater
    assert rows[0]["flag"] is False
    assert rows[1]["flag"] is True


@pytest.mark.asyncio
async def test_running_balance() -> None:
    ctx, env = _ctx(
        {
            "mode": "calculation",
            "catalog_id": "running_balance",
            "input_map": {"deposit": "in", "withdrawal": "out"},
            "opening_balance": "100",
            "precision": 2,
        },
        rows=[{"in": "20", "out": "5"}, {"in": "0", "out": "10"}],
    )
    rows = (await MathEngine().execute(ctx, env))[0].payload["rows"]
    assert rows[0]["running_balance"] == Decimal("115.00")
    assert rows[1]["running_balance"] == Decimal("105.00")


@pytest.mark.asyncio
async def test_aggregate_summary_and_window() -> None:
    rows = [
        {"dept": "A", "measure": "10"},
        {"dept": "A", "measure": "5"},
        {"dept": "B", "measure": "7"},
    ]
    ctx, env = _ctx(
        {
            "mode": "calculation",
            "catalog_id": "group_sum",
            "shape": "aggregate",
            "group_by": ["dept"],
            "aggregate_output": "summary",
            "input_map": {"measure": "measure"},
        },
        rows=rows,
    )
    summary = (await MathEngine().execute(ctx, env))[0].payload["rows"]
    by = {r["dept"]: r["group_total"] for r in summary}
    assert by["A"] == Decimal("15.00")
    assert by["B"] == Decimal("7.00")

    ctx2, env2 = _ctx(
        {
            "mode": "calculation",
            "catalog_id": "group_sum",
            "shape": "aggregate",
            "group_by": ["dept"],
            "aggregate_output": "window",
            "input_map": {"measure": "measure"},
        },
        rows=rows,
    )
    windowed = (await MathEngine().execute(ctx2, env2))[0].payload["rows"]
    assert len(windowed) == 3
    assert windowed[0]["group_total"] == Decimal("15.00")


@pytest.mark.asyncio
async def test_llm_picks_catalog_id_without_inventing_ast() -> None:
    class PickLLM:
        async def complete(self, model_role, prompt, temperature=0.0) -> str:
            return "{}"

        async def complete_json(self, model_role, prompt, schema, temperature=0.0):
            assert "ast" not in (schema.get("required") or [])
            assert "catalog_id" in (schema.get("required") or [])
            return {"catalog_id": "variance_amount", "constants": {}, "input_map": {}}

    ctx, env = _ctx(
        {"formula_en": "actual minus budget"},
        llm=PickLLM(),
        rows=[{"actual": "9", "budget": "4"}],
    )
    row = (await MathEngine().execute(ctx, env))[0].payload["rows"][0]
    assert row["variance_amount"] == Decimal("5.00")
    assert (await MathEngine().execute(ctx, env))[0].payload["logic"]["catalog_id"] == "variance_amount"


class BoomCompileLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise LLMError(
            "Client error '400 Bad Request' for url "
            "'https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com/v2/inference'"
        )

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise LLMError(
            "Client error '400 Bad Request' for url "
            "'https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com/v2/inference'"
        )


@pytest.mark.asyncio
async def test_llm_400_does_not_leak_url_and_uses_local_fallback() -> None:
    ctx, env = _ctx(
        {"formula_en": "keep a running cash position", "shape": "sequential"},
        llm=BoomCompileLLM(),
        rows=[{"amount": "5"}],
    )
    out = await MathEngine().execute(ctx, env)
    assert out[0].payload["logic"]["catalog_id"] == "running_balance"

    ctx2, env2 = _ctx(
        {"formula_en": "something the catalog does not know"},
        llm=BoomCompileLLM(),
        rows=[{"a": "1"}],
    )
    with pytest.raises(ValueError) as err:
        await MathEngine().execute(ctx2, env2)
    message = str(err.value)
    assert "400" not in message
    assert "hana.ondemand" not in message
    assert "library" in message.lower() or "formula" in message.lower()


@pytest.mark.asyncio
async def test_journey1_english_fills_min_pct_slots() -> None:
    from app.services.formulas import compile_math_value

    out = await compile_math_value(
        {"formula_en": "Allow up to 2% variance or $50, whichever is smaller."},
        NullLLM(),
    )
    assert out["catalog_id"] == "min_pct_amount_tolerance"
    assert float(out["constants"]["pct"]) == 0.02
    assert float(out["constants"]["amount"]) == 50
    assert out["ast"]
    assert out["gate_ast"]


@pytest.mark.asyncio
async def test_journey2_english_picks_running_balance() -> None:
    from app.services.formulas import compile_logic

    logic = await compile_logic(
        {"formula_en": "previous balance + deposit - withdrawal row-by-row"},
        NullLLM(),
    )
    assert logic.catalog_id == "running_balance"


@pytest.mark.asyncio
async def test_journey3_english_picks_net_and_material_break() -> None:
    from app.services.formulas import compile_logic, compile_math_value

    net = await compile_logic(
        {"formula_en": "Sum total receivables minus payables by entity pair"},
        NullLLM(),
    )
    assert net.catalog_id == "entity_pair_net"
    assert net.shape == "aggregate"
    break_cfg = await compile_math_value(
        {"formula_en": "highlight any material net break over $1,000"},
        NullLLM(),
    )
    assert break_cfg["catalog_id"] == "material_net_break"
    assert float(break_cfg["constants"]["amount"]) == 1000


@pytest.mark.asyncio
async def test_running_balance_english_skips_llm() -> None:
    ctx, env = _ctx(
        {"formula_en": "previous plus deposits minus withdrawals", "shape": "sequential"},
        llm=NullLLM(),
        rows=[{"amount": "10"}, {"amount": "-3"}],
    )
    out = await MathEngine().execute(ctx, env)
    logic = out[0].payload["logic"]
    assert logic["catalog_id"] == "running_balance"
    assert logic["ast"]


@pytest.mark.asyncio
async def test_conversation_formula_compiles_into_node_config() -> None:
    from app.services.formulas import compile_math_value

    out = await compile_math_value(
        {
            "formula_en": "allow 2% or $50, whichever is smaller",
            "catalog_id": "min_pct_amount_tolerance",
            "constants": {"pct": 0.02, "amount": 50},
        },
        NullLLM(),
    )
    assert out["catalog_id"] == "min_pct_amount_tolerance"
    assert out["ast"]
    assert out["gate_ast"]
    assert out["formula_en"].startswith("allow 2%")
    assert out["constants"]["amount"] == 50
    assert out["compiled_from"]


@pytest.mark.asyncio
async def test_ingest_then_math(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "ba.csv",
        [["actual", "budget"], ["30", "20"], ["8", "10"]],
    )
    pipeline = Pipeline(
        id="ingest-math",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(path)}),
            Node(
                id="m",
                agent="math",
                config={
                    "mode": "calculation",
                    "catalog_id": "variance_amount",
                    "input_map": {"actual": "actual", "budget": "budget"},
                },
            ),
        ],
        edges=[Edge(id="e1", source="in", target="m")],
    )
    registry = AgentRegistry()
    registry.register(Ingestor)
    registry.register(MathEngine)
    runner = PipelineRunner(registry, Storage(tmp_path), NullLLM())
    run = await runner.run(pipeline)
    assert run.status == "completed"
    math_step = next(s for s in run.steps if s.node_id == "m")
    values = [r["variance_amount"] for r in math_step.outputs[0].payload["rows"]]
    assert values == [Decimal("10.00"), Decimal("-2.00")]


@pytest.mark.asyncio
async def test_math_uses_ingest_when_matched_empty() -> None:
    ctx, env = _ctx(
        {"mode": "calculation", "ast": "a + b", "output_column": "sum", "precision": 2},
        rows=[],
    )
    ctx.inputs = [
        Envelope(
            run_id="r",
            node_id="match",
            port="matched",
            payload={"kind": "matches", "rows": []},
            emitted_by="matcher@v1",
        ),
        Envelope(
            run_id="r",
            node_id="in",
            port="default",
            payload={"kind": "data", "rows": [{"a": "1", "b": "2"}]},
            emitted_by="ingestion@v1",
        ),
    ]
    out = await MathEngine().execute(ctx, env)
    assert out[0].payload["rows"][0]["sum"] == Decimal("3.00")
