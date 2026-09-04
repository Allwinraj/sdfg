from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from app.agents.base import AgentRegistry, RunContext
from app.agents.decision import Decision
from app.core.llm import _validate_json_schema
from app.core.storage import Storage
from app.engine.runner import PipelineRunner
from app.models.envelope import Envelope
from app.models.knowledge import KnowledgeDocument, SessionKnowledge
from app.models.pipeline import Edge, Node, Pipeline
from app.services.decision import VERDICT_JSON_SCHEMA
from app.services.knowledge import chunk_text, rank_chunks


class ScriptedLLM:
    def __init__(self, reply: dict | None = None, replies: list[dict] | None = None) -> None:
        self.replies = list(replies) if replies is not None else None
        self.reply = reply or {
            "verdict": "approved",
            "confidence": 0.95,
            "explanation": "Within policy.",
            "remediation": "None",
        }
        self.calls: list[tuple] = []

    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        self.calls.append((model_role, prompt, temperature))
        _validate_json_schema(self.reply if self.replies is None else self.replies[0], schema)
        if self.replies is not None:
            return dict(self.replies.pop(0))
        return dict(self.reply)


class PromptJudgeLLM:
    """Deterministic mock: weekend surcharge escalates; low confidence otherwise."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        assert model_role == "general"
        self.calls.append((model_role, prompt))
        ids = re.findall(r"chunk_id=([^\s\]]+)", prompt)
        citation = {"chunk_id": ids[0], "section": "Fee Structure", "document": "msa"} if ids else {}
        text = prompt.lower()
        if "weekend" in text:
            return {
                "verdict": "escalated",
                "confidence": 0.97,
                "explanation": "Weekend delivery surcharge is not in the MSA.",
                "remediation": "Buyer review before payment.",
                "citation": citation,
            }
        if "tokyo" in text or "hotel" in text:
            return {
                "verdict": "approved",
                "confidence": 0.92,
                "explanation": "Peak-city lodging exception applies.",
                "citation": citation,
            }
        if "first-class" in text or "first class" in text:
            return {
                "verdict": "flagged",
                "confidence": 0.88,
                "explanation": "Exceeds business class allowance.",
                "remediation": "Request VP pre-authorization.",
                "citation": citation,
            }
        return {
            "verdict": "approved",
            "confidence": 0.4,
            "explanation": "Likely fine but uncertain.",
            "citation": citation,
        }


def _knowledge() -> SessionKnowledge:
    text = (
        "SECTION 4.3.1 LODGING\n"
        "Tier-1 cities during peak events may exceed the hotel cap by 25 percent.\n\n"
        "MSA SCHEDULE B FEE STRUCTURE\n"
        "Fuel surcharges in the contract table are reimbursable. Weekend delivery "
        "surcharges are not listed and require buyer approval.\n"
    )
    chunks = chunk_text(text, file_id="msa")
    return SessionKnowledge(
        session_id="s1",
        documents=[
            KnowledgeDocument(
                file_id="msa",
                original_path="/tmp/msa.pdf",
                chunks=chunks,
            )
        ],
    )


def _rows(*records: dict) -> list[Envelope]:
    return [
        Envelope(
            run_id="r",
            node_id="up",
            port="exceptions",
            payload={"kind": "matches", "rows": list(records)},
            emitted_by="matcher@v1",
        )
    ]


def _ctx(config: dict, inputs: list[Envelope], llm=None, knowledge=None) -> RunContext:
    return RunContext(
        run_id="r",
        llm=llm or ScriptedLLM(),
        storage=Storage(Path(".")),
        logger=logging.getLogger("test"),
        knowledge_store=knowledge,
        node=Node(
            id="d",
            agent="decision",
            mode=config.get("mode", "approval"),
            config=config,
        ),
        inputs=inputs,
    )


async def _run(config, inputs, llm=None, knowledge=None):
    return await Decision().execute(_ctx(config, inputs, llm, knowledge), inputs[0])


def _by_port(envelopes):
    return {e.port: e.payload["rows"] for e in envelopes}


@pytest.mark.asyncio
async def test_verdict_contract_schema() -> None:
    out = _by_port(
        await _run(
            {"mode": "approval", "authority": "autonomous", "policy": "Approve in-policy items."},
            _rows({"invoice": "1", "amount": "100"}),
        )
    )
    row = out["approved"][0]
    assert set(row) >= {
        "source",
        "verdict",
        "confidence",
        "explanation",
        "remediation",
        "policy_citation",
        "authority",
        "held_for_review",
        "mode",
    }
    payload = {
        "verdict": row["verdict"],
        "confidence": row["confidence"],
        "explanation": row["explanation"],
    }
    _validate_json_schema(payload, VERDICT_JSON_SCHEMA)
    assert row["source"]["invoice"] == "1"


@pytest.mark.asyncio
async def test_autonomous_threshold_holds_uncertain_approve() -> None:
    llm = ScriptedLLM(
        {
            "verdict": "approved",
            "confidence": 0.7,
            "explanation": "Uncertain auto-approve.",
        }
    )
    out = _by_port(
        await _run(
            {"authority": "autonomous", "confidence_threshold": 0.85, "policy": "Hold uncertain approvals."},
            _rows({"id": "a"}),
            llm=llm,
        )
    )
    assert "approved" not in out
    assert out["flagged"][0]["verdict"] == "approved"
    assert out["flagged"][0]["held_for_review"] is False


@pytest.mark.asyncio
async def test_advisory_routes_all_to_flagged() -> None:
    llm = ScriptedLLM(
        {
            "verdict": "approved",
            "confidence": 0.99,
            "explanation": "Would auto-approve.",
        }
    )
    out = _by_port(
        await _run(
            {"authority": "advisory", "confidence_threshold": 0.5, "policy": "Advisory review."},
            _rows({"id": "a"}),
            llm=llm,
        )
    )
    assert list(out) == ["flagged"]
    row = out["flagged"][0]
    assert row["verdict"] == "approved"
    assert row["held_for_review"] is True
    assert row["authority"] == "advisory"


@pytest.mark.asyncio
async def test_three_verdict_ports() -> None:
    llm = PromptJudgeLLM()
    out = _by_port(
        await _run(
            {"mode": "approval", "authority": "autonomous", "confidence_threshold": 0.85, "policy": "Travel policy."},
            _rows(
                {"line": "hotel", "city": "Tokyo"},
                {"line": "first-class rail"},
                {"line": "weekend delivery surcharge"},
            ),
            llm=llm,
        )
    )
    assert len(out["approved"]) == 1
    assert len(out["flagged"]) == 1
    assert len(out["escalated"]) == 1
    assert all(role == "general" for role, _prompt in llm.calls)


@pytest.mark.asyncio
async def test_mocked_llm_is_deterministic() -> None:
    llm = PromptJudgeLLM()
    record = {"line": "hotel", "city": "Tokyo"}
    first = _by_port(await _run({"authority": "autonomous", "policy": "Travel policy."}, _rows(record), llm=llm))
    second = _by_port(
        await _run({"authority": "autonomous", "policy": "Travel policy."}, _rows(record), llm=PromptJudgeLLM())
    )
    assert first["approved"][0]["verdict"] == second["approved"][0]["verdict"]
    assert first["approved"][0]["confidence"] == second["approved"][0]["confidence"]
    assert first["approved"][0]["explanation"] == second["approved"][0]["explanation"]


@pytest.mark.asyncio
async def test_policy_citation_includes_retrieved_chunk_id() -> None:
    knowledge = _knowledge()
    ranked = rank_chunks(knowledge, "weekend delivery surcharge MSA", limit=3)
    assert ranked
    llm = PromptJudgeLLM()
    out = _by_port(
        await _run(
            {
                "mode": "policy",
                "policy": "Escalate fees not listed in the MSA.",
                "authority": "autonomous",
            },
            _rows({"fee": "weekend delivery surcharge"}),
            llm=llm,
            knowledge=knowledge,
        )
    )
    citation = out["escalated"][0]["policy_citation"]
    assert citation["chunk_id"]
    passage = knowledge.retrieve(citation["chunk_id"])
    assert passage.id == citation["chunk_id"]
    assert "weekend" in passage.text.lower() or "fee" in passage.heading.lower()
    assert all(role == "general" and "Retrieved passages" in prompt for role, prompt in llm.calls)


@pytest.mark.asyncio
async def test_anomaly_mode_severity_mapping() -> None:
    llm = ScriptedLLM(
        {
            "verdict": "high",
            "confidence": 0.91,
            "explanation": "Split-transaction pattern.",
            "risk_category": "structuring",
            "severity": "high",
        }
    )
    out = _by_port(
        await _run(
            {"mode": "anomaly", "authority": "autonomous", "policy": "Flag structuring."},
            _rows({"vendor": "X", "amount": "49.99"}),
            llm=llm,
        )
    )
    assert out["escalated"][0]["risk_category"] == "structuring"
    assert out["escalated"][0]["verdict"] == "escalated"


@pytest.mark.asyncio
async def test_runner_routes_decision_ports(tmp_path: Path) -> None:
    pipeline = Pipeline(
        id="dports",
        nodes=[
            Node(
                id="d",
                agent="decision",
                config={
                    "mode": "approval",
                    "authority": "autonomous",
                    "confidence_threshold": 0.85,
                    "policy": "Travel policy.",
                },
            ),
            Node(id="ok", agent="decision", config={"mode": "approval", "authority": "advisory"}),
        ],
        edges=[
            Edge(id="e1", source="d", source_port="approved", target="ok"),
        ],
    )
    registry = AgentRegistry()
    registry.register(Decision)
    llm = PromptJudgeLLM()
    runner = PipelineRunner(registry, Storage(tmp_path), llm)
    run = await runner.run(
        pipeline,
        seed={"rows": [{"line": "hotel", "city": "Tokyo"}, {"line": "weekend delivery surcharge"}]},
    )
    by = {s.node_id: s for s in run.steps}
    assert by["d"].status == "ok"
    ports = {e.port for e in by["d"].outputs}
    assert "approved" in ports
    assert "escalated" in ports
    assert by["ok"].status == "ok"
    assert by["ok"].outputs[0].port == "flagged"
    assert llm.calls
    assert all(role == "general" for role, _prompt in llm.calls)


@pytest.mark.asyncio
async def test_rules_flag_exceptions_and_math_without_llm() -> None:
    llm = ScriptedLLM()
    exceptions = [
        Envelope(
            run_id="r",
            node_id="match",
            port="exceptions",
            payload={"kind": "matches", "rows": [{"id": "u1"}]},
            emitted_by="matcher@v1",
        )
    ]
    math_ok = [
        Envelope(
            run_id="r",
            node_id="math",
            port="default",
            payload={"kind": "table", "rows": [{"id": "ok", "flag": False}, {"id": "bad", "flag": True}]},
            emitted_by="math@v1",
        )
    ]
    out = _by_port(await _run({"authority": "autonomous"}, exceptions + math_ok, llm=llm))
    assert llm.calls == []
    ids = {row["source"]["id"] for row in out["flagged"]}
    assert ids == {"u1", "bad"}
    assert out["approved"][0]["source"]["id"] == "ok"


@pytest.mark.asyncio
async def test_many_rows_without_policy_never_call_llm() -> None:
    llm = ScriptedLLM()
    rows = [{"id": i, "flag": False} for i in range(40)]
    env = [
        Envelope(
            run_id="r",
            node_id="math",
            port="default",
            payload={"kind": "table", "rows": rows},
            emitted_by="math@v1",
        )
    ]
    out = _by_port(await _run({"authority": "autonomous"}, env, llm=llm))
    assert llm.calls == []
    assert len(out["approved"]) == 40
