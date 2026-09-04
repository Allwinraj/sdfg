from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.agents.base import AgentRegistry
from app.core.storage import Storage
from app.engine.persist import load_run
from app.engine.runner import PipelineRunner
from app.models.pipeline import Edge, Node, Pipeline
from tests.unit.stubs import (
    BoomAgent,
    SlowIngest,
    StubDecision,
    StubIngest,
    StubMatcher,
    StubMath,
    StubOutput,
)


class NullLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise AssertionError("stubs must not call the LLM")

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise AssertionError("stubs must not call the LLM")


def _runner(tmp_path: Path, *agent_cls) -> PipelineRunner:
    registry = AgentRegistry()
    for cls in agent_cls:
        registry.register(cls)
    return PipelineRunner(registry, Storage(tmp_path), NullLLM())


@pytest.mark.asyncio
async def test_sparse_ingest_to_output(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="sparse",
        nodes=[
            Node(id="in", agent="ingestion", config={"rows": [{"id": 1}]}),
            Node(id="out", agent="output"),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    runner = _runner(tmp_path, StubIngest, StubOutput)
    run = await runner.run(pipeline)
    assert run.status == "completed"
    assert [s.node_id for s in run.steps] == ["in", "out"]
    assert run.steps[-1].outputs[0].payload["delivered"] is True
    saved = load_run(Storage(tmp_path), run.id)
    assert saved.id == run.id


@pytest.mark.asyncio
async def test_matcher_ports_leave_idle_branch_dormant(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="ports",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                config={"rows": [{"id": 1, "bucket": "matched"}, {"id": 2, "bucket": "residuals"}]},
            ),
            Node(id="match", agent="matcher"),
            Node(id="math", agent="math"),
            Node(id="decide", agent="decision"),
        ],
        edges=[
            Edge(id="e1", source="in", target="match"),
            Edge(id="e2", source="match", source_port="matched", target="math"),
            Edge(id="e3", source="match", source_port="exceptions", target="decide"),
        ],
    )
    runner = _runner(tmp_path, StubIngest, StubMatcher, StubMath, StubDecision)
    run = await runner.run(pipeline)
    by_id = {s.node_id: s for s in run.steps}
    assert by_id["math"].status == "ok"
    assert by_id["decide"].status == "skipped"
    assert by_id["match"].outputs[0].port == "matched"


@pytest.mark.asyncio
async def test_decision_runs_when_one_incoming_port_is_empty(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="fanin",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                config={"rows": [{"id": 1, "bucket": "matched"}]},
            ),
            Node(id="match", agent="matcher"),
            Node(id="math", agent="math"),
            Node(id="decide", agent="decision"),
        ],
        edges=[
            Edge(id="e1", source="in", target="match"),
            Edge(id="e2", source="match", source_port="matched", target="math"),
            Edge(id="e3", source="math", target="decide"),
            Edge(id="e4", source="match", source_port="exceptions", target="decide"),
        ],
    )
    runner = _runner(tmp_path, StubIngest, StubMatcher, StubMath, StubDecision)
    run = await runner.run(pipeline)
    by_id = {s.node_id: s for s in run.steps}
    assert by_id["math"].status == "ok"
    assert by_id["decide"].status == "ok"


@pytest.mark.asyncio
async def test_conditional_edge(tmp_path: Path) -> None:
    class FlagMath:
        name = "math"

        async def execute(self, ctx, env):
            from app.models.envelope import Envelope

            return [
                Envelope(
                    run_id=ctx.run_id,
                    node_id="math",
                    payload={"variance": 5},
                    emitted_by="math@stub",
                )
            ]

    pipeline = Pipeline(
        id="cond",
        nodes=[
            Node(id="in", agent="ingestion"),
            Node(id="math", agent="math"),
            Node(id="out", agent="output"),
        ],
        edges=[
            Edge(id="e1", source="in", target="math"),
            Edge(
                id="e2",
                source="math",
                target="out",
                type="conditional",
                condition="variance > 0",
            ),
        ],
    )
    runner = _runner(tmp_path, StubIngest, FlagMath, StubOutput)
    run = await runner.run(pipeline)
    assert {s.node_id: s.status for s in run.steps}["out"] == "ok"

    class ZeroMath:
        name = "math"

        async def execute(self, ctx, env):
            from app.models.envelope import Envelope

            return [
                Envelope(
                    run_id=ctx.run_id,
                    node_id="math",
                    payload={"variance": 0},
                    emitted_by="math@stub",
                )
            ]

    runner2 = _runner(tmp_path, StubIngest, ZeroMath, StubOutput)
    run2 = await runner2.run(pipeline)
    assert {s.node_id: s.status for s in run2.steps}["out"] == "skipped"


@pytest.mark.asyncio
async def test_fail_fast_stops_downstream(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="boom",
        nodes=[
            Node(id="in", agent="ingestion"),
            Node(id="math", agent="math", error_strategy="fail_fast"),
            Node(id="out", agent="output"),
        ],
        edges=[
            Edge(id="e1", source="in", target="math"),
            Edge(id="e2", source="math", target="out"),
        ],
    )
    runner = _runner(tmp_path, StubIngest, BoomAgent, StubOutput)
    run = await runner.run(pipeline)
    assert run.status == "failed_with_exceptions"
    assert "out" not in {s.node_id for s in run.steps}


@pytest.mark.asyncio
async def test_emit_exceptions_continues(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="soft",
        nodes=[
            Node(id="in", agent="ingestion"),
            Node(id="math", agent="math", error_strategy="emit_exceptions"),
            Node(id="out", agent="output"),
        ],
        edges=[
            Edge(id="e1", source="in", target="math"),
            Edge(id="e2", source="math", source_port="exceptions", target="out"),
        ],
    )
    runner = _runner(tmp_path, StubIngest, BoomAgent, StubOutput)
    run = await runner.run(pipeline)
    assert run.status == "failed_with_exceptions"
    by_id = {s.node_id: s for s in run.steps}
    assert by_id["out"].status == "ok"
    assert by_id["math"].outputs[0].port == "exceptions"


@pytest.mark.asyncio
async def test_level_runs_in_parallel(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="par",
        nodes=[
            Node(id="a", agent="ingestion"),
            Node(id="b", agent="ingestion"),
            Node(id="out", agent="output"),
        ],
        edges=[
            Edge(id="e1", source="a", target="out"),
            Edge(id="e2", source="b", target="out"),
        ],
    )
    runner = _runner(tmp_path, SlowIngest, StubOutput)
    started = time.perf_counter()
    run = await runner.run(pipeline)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.09
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_per_record_isolation_does_not_fail_node(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="rows",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                config={"rows": [{"amount": 1}, {"amount": 2, "bad": True}]},
            ),
            Node(id="math", agent="math"),
        ],
        edges=[Edge(id="e1", source="in", target="math")],
    )
    runner = _runner(tmp_path, StubIngest, StubMath)
    run = await runner.run(pipeline)
    assert run.status == "completed"
    rows = run.steps[-1].outputs[0].payload["rows"]
    assert rows[1]["error"] == "isolated"
    assert rows[0].get("flag") is False


@pytest.mark.asyncio
async def test_skip_reason_and_events(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="ports",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                label="Bank file",
                config={"rows": [{"id": 1, "bucket": "matched"}], "filename": "bank.csv"},
            ),
            Node(id="match", agent="matcher", label="Matcher"),
            Node(id="math", agent="math", label="Math"),
            Node(id="decide", agent="decision", label="Decision"),
        ],
        edges=[
            Edge(id="e1", source="in", target="match"),
            Edge(id="e2", source="match", source_port="matched", target="math"),
            Edge(id="e3", source="match", source_port="exceptions", target="decide"),
        ],
    )
    events: list[dict] = []

    async def on_event(event):
        events.append(event)

    runner = _runner(tmp_path, StubIngest, StubMatcher, StubMath, StubDecision)
    run = await runner.run(pipeline, on_event=on_event)
    by_id = {s.node_id: s for s in run.steps}
    assert by_id["math"].status == "ok"
    assert by_id["decide"].status == "skipped"
    assert by_id["decide"].skip_reason
    assert "exceptions" in by_id["decide"].skip_reason.lower() or "nothing" in by_id["decide"].skip_reason.lower()
    assert by_id["decide"].summary
    kinds = [e["type"] for e in events]
    assert "node_start" in kinds
    assert "node_finish" in kinds
    assert events[-1]["type"] == "done"
    assert by_id["in"].duration_ms >= 0
    finish = next(e for e in events if e.get("node_id") == "decide" and e["type"] == "node_finish")
    assert finish["status"] == "skipped"
    assert finish.get("duration_ms") is not None
