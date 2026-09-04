from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.storage import Storage
from app.main import app
from app.models.chat import ExtractedRequirement, InterviewSession
from app.services.interview import _advance_onboarding
from app.services.pipeline_builder import desired_pipeline


class JourneyLLM:
    """Scripted LLM for onboarding + interview tests."""

    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        if model_role == "extraction":
            return {"facts": []}
        if "Generate the next onboarding message" in prompt:
            return self._onboarding(prompt)
        return self._interview(prompt)

    def _field(self, prompt: str, name: str) -> str:
        match = re.search(rf'"{name}":\s*"([^"]*)"', prompt)
        return match.group(1) if match else ""

    def _onboarding(self, prompt: str) -> dict:
        trigger = self._field(prompt, "trigger")
        step = self._field(prompt, "onboarding_step") or "start"
        user = self._field(prompt, "user_text")
        lower = user.lower()
        desc = self._field(prompt, "description")

        if trigger == "session_start":
            return {
                "assistant_message": "Hi — I'm Nexus. What best describes your role?",
                "next_step": "role",
                "upload_offer": None,
                "capture": {},
                "virtual_sources": [],
            }

        if step == "role":
            return {
                "assistant_message": "Thanks. What industry are you in today?",
                "next_step": "industry",
                "capture": {"role": user},
                "virtual_sources": [],
            }
        if step == "industry":
            return {
                "assistant_message": "If AI could improve a few things in your work, what would they be?",
                "next_step": "ai_priorities",
                "capture": {"industry": user},
                "virtual_sources": [],
            }
        if step == "ai_priorities":
            return {
                "assistant_message": "What finance workflow should we build?",
                "next_step": "workflow",
                "capture": {"ai_priorities": user},
                "virtual_sources": [],
            }
        if step == "workflow":
            return {
                "assistant_message": "Do you have input files for this? Attach them below when ready.",
                "next_step": "data_prompt",
                "upload_offer": "data",
                "capture": {"description": user},
                "virtual_sources": [],
            }
        if step == "data_prompt":
            if any(p in lower for p in ("no", "none", "don't", "not yet")):
                return {
                    "assistant_message": "Describe your first data source — name and key columns?",
                    "next_step": "data_interview",
                    "upload_offer": None,
                    "virtual_sources": [],
                }
            return {
                "assistant_message": "Use the attach button below when your files are ready.",
                "next_step": "data_prompt",
                "upload_offer": "data",
                "virtual_sources": [],
            }
        if step == "data_interview":
            pack = self._pipeline_pack(desc or user)
            return {
                "assistant_message": "Got the data shape. Any policy or reference documents?",
                "next_step": "knowledge_prompt",
                "upload_offer": "knowledge",
                "virtual_sources": pack["virtual_sources"],
                "requirements": pack["requirements"],
                "capabilities": pack["capabilities"],
            }
        if step == "knowledge_prompt":
            if any(p in lower for p in ("no", "none", "skip")):
                pack = self._pipeline_pack(desc)
                return {
                    "assistant_message": "Understood. Let's refine the pipeline.",
                    "next_step": "done",
                    "upload_offer": None,
                    "requirements": pack["requirements"],
                    "capabilities": pack["capabilities"],
                }
            return {
                "assistant_message": 'Attach reference docs below, or reply "none" to continue.',
                "next_step": "knowledge_prompt",
                "upload_offer": "knowledge",
                "virtual_sources": [],
            }
        if trigger == "data_uploaded":
            return {
                "assistant_message": "Files received. Any policy or reference documents?",
                "next_step": "knowledge_prompt",
                "upload_offer": "knowledge",
                "virtual_sources": [],
            }
        return {"assistant_message": "Got it.", "next_step": step, "virtual_sources": []}

    def _pipeline_pack(self, text: str) -> dict:
        lower = text.lower()
        if "variance" in lower and "spreadsheet" in lower:
            return {
                "virtual_sources": [
                    {
                        "label": "budget",
                        "description": "Budget vs actual spreadsheet",
                        "columns": [{"name": "actual", "type": "decimal"}, {"name": "budget", "type": "decimal"}],
                    }
                ],
                "capabilities": {
                    "matcher": False,
                    "math": True,
                    "decision": False,
                    "output": True,
                    "output_formats": ["xlsx"],
                },
                "requirements": [
                    {"id": "math-var", "kind": "math", "value": {"catalog_id": "variance_pct", "output_column": "variance_pct"}},
                    {"id": "out-xlsx", "kind": "excel", "value": {"formats": ["xlsx"]}},
                ],
            }
        if "bank" in lower and "reconcil" in lower:
            return {
                "virtual_sources": [
                    {
                        "label": "bank",
                        "description": "Bank statement",
                        "columns": [{"name": "date", "type": "date"}, {"name": "amount", "type": "decimal"}],
                    },
                    {
                        "label": "ledger",
                        "description": "GL cash export",
                        "columns": [{"name": "date", "type": "date"}, {"name": "amount", "type": "decimal"}],
                    },
                ],
                "capabilities": {
                    "matcher": True,
                    "math": True,
                    "decision": False,
                    "output": True,
                    "keys": ["date", "amount"],
                },
                "requirements": [
                    {"id": "match-bank", "kind": "match", "value": {"keys": ["date", "amount"], "mode": "structural"}},
                    {"id": "math-bal", "kind": "math", "value": {"catalog_id": "running_balance", "output_column": "balance"}},
                    {"id": "out-xlsx", "kind": "excel", "value": {}},
                ],
            }
        return {
            "virtual_sources": [
                {"label": "po", "description": "PO file", "columns": [{"name": "po", "type": "string"}, {"name": "line", "type": "string"}]},
                {"label": "gr", "description": "Goods receipt", "columns": [{"name": "po", "type": "string"}, {"name": "line", "type": "string"}]},
                {"label": "invoice", "description": "Invoice file", "columns": [{"name": "po", "type": "string"}, {"name": "line", "type": "string"}]},
            ],
            "capabilities": {
                "matcher": True,
                "math": True,
                "decision": True,
                "output": True,
                "keys": ["po_number", "line"],
            },
            "requirements": [
                {"id": "match-3way", "kind": "match", "value": {"keys": ["po_number", "line"], "mode": "structural"}},
                {"id": "math-qty", "kind": "math", "value": {"ast": "1+1", "output_column": "n"}},
                {"id": "dec-1", "kind": "decision", "value": {"mode": "approval"}},
                {"id": "out-xlsx", "kind": "excel", "value": {}},
            ],
        }

    def _interview(self, prompt: str) -> dict:
        text = prompt.lower()
        q = _field_int(prompt, "question_count")
        force_cap = "handoff-cap" in text
        pack = self._pipeline_pack(text)
        keys = pack["capabilities"].get("keys") or ["po", "line"]
        decision = "drop the decision" not in text and "skip decision" not in text
        caps = dict(pack["capabilities"])
        caps["decision"] = decision and caps.get("decision", False)
        reqs = [r for r in pack["requirements"] if r["id"] != "dec-1" or caps["decision"]]
        if "po_number" in text and any(r["id"] == "match-3way" for r in reqs):
            for r in reqs:
                if r["id"] == "match-3way":
                    r["value"]["keys"] = ["po_number", "line"]
        user = self._field(prompt, "user_text").lower()
        summary = "Pipeline from conversation."
        ready = (not force_cap) and q >= 5
        return {
            "assistant_message": "Understood.",
            "requirements": reqs,
            "capabilities": caps,
            "ask_question": not ready,
            "question": None if ready else "Which exception handling do you prefer?",
            "ready": ready,
            "confidence": 0.4 if force_cap else 0.9,
            "summary": summary,
            "cannot_serve": "erp mutation" in user or "live slack" in user,
            "cannot_serve_reason": (
                "Nexus v1 cannot write back to ERP or send live Slack alerts."
                if "erp mutation" in user or "live slack" in user
                else None
            ),
            "answer_relevant": "pizza" not in user and "asdfgh" not in user,
            "is_description": True,
        }


def _field_int(prompt: str, name: str) -> int:
    match = re.search(rf'"{name}":\s*(\d+)', prompt)
    return int(match.group(1)) if match else 0


def _csv(*rows: list[str]) -> bytes:
    return ("\n".join(",".join(row) for row in rows) + "\n").encode()


@pytest.fixture
def api(tmp_path):
    with TestClient(app) as client:
        app.state.storage = Storage(tmp_path)
        app.state.llm = JourneyLLM()
        yield client, tmp_path


def _session(client) -> str:
    response = client.post("/chat/session")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "welcome"
    assert body["pipeline"] is None
    assert "role" in body["message"]["content"].lower()
    return body["session_id"]


def _onboard(client, session_id: str, *, workflow: str) -> None:
    for content in (
        "Accounts Payable manager",
        "Mid-market manufacturing",
        "Automate matching and cut manual rework",
        workflow,
    ):
        r = client.post("/chat/message", json={"session_id": session_id, "content": content})
        assert r.status_code == 200


def _upload(client, session_id: str, files: list[tuple[str, bytes]], kind: str = "data"):
    payload = [("files", (name, blob, "text/csv")) for name, blob in files]
    return client.post("/chat/upload", data={"session_id": session_id, "kind": kind}, files=payload)


def _agents(body: dict) -> list[str]:
    pipeline = body.get("pipeline") or {}
    return [n["agent"] for n in pipeline.get("nodes") or []]


def _until_ready(client, session_id: str) -> dict:
    body = {}
    for _ in range(8):
        body = client.post(
            "/chat/message", json={"session_id": session_id, "content": "looks right"}
        ).json()
        if body.get("ready_to_confirm") or body.get("status") == "ready_to_confirm":
            return body
        if body.get("question_count", 0) >= 15:
            return body
    return body


def test_invoice_journey_empty_upload_draft_remove_confirm(api) -> None:
    client, tmp_path = api
    sid = _session(client)
    _onboard(
        client,
        sid,
        workflow="Three-way invoice match of PO, goods receipt, and vendor invoice.",
    )
    offer = client.post("/chat/message", json={"session_id": sid, "content": "yes"}).json()
    assert offer.get("upload_offer") == "data"

    uploaded = _upload(
        client,
        sid,
        [
            ("po.csv", _csv(["po", "line", "qty"], ["1", "A", "2"])),
            ("gr.csv", _csv(["po", "line", "qty"], ["1", "A", "2"])),
            ("invoice.csv", _csv(["po", "line", "qty"], ["1", "A", "2"])),
        ],
    )
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["reveal"]
    assert body["reveal"]["upsert_nodes"]
    assert not body["reveal"]["remove_node_ids"]
    assert body.get("upload_offer") == "knowledge"
    assert (body.get("user_message") or {}).get("role") == "user"
    assert "po.csv" in ((body.get("user_message") or {}).get("content") or "")
    agents = _agents(body)
    assert agents.count("ingestion") == 3
    assert not any(n["id"].startswith("ingest_knowledge") for n in body["pipeline"]["nodes"])

    started = client.post("/chat/message", json={"session_id": sid, "content": "none"}).json()
    agents = _agents(started)
    assert "matcher" in agents
    assert "math" in agents
    assert "decision" in agents
    assert "output" in agents

    removed = client.post(
        "/chat/message",
        json={"session_id": sid, "content": "Drop the decision node; exceptions just go to Excel."},
    ).json()
    assert "decision" in removed["reveal"]["remove_node_ids"]
    assert "decision" not in _agents(removed)

    patched = client.post(
        "/chat/message",
        json={"session_id": sid, "content": "Join keys should be po_number and line."},
    ).json()
    matcher = next(n for n in patched["pipeline"]["nodes"] if n["agent"] == "matcher")
    assert matcher["config"]["keys"] == ["po_number", "line"]

    ready = _until_ready(client, sid)
    assert ready["question_count"] >= 5
    assert ready["question_count"] <= 15
    assert ready["ready_to_confirm"] is True
    assert "What each step does" in ready["message"]["content"]

    synced = client.post(
        "/chat/sync-node",
        json={"session_id": sid, "node_id": matcher["id"], "config": {"window_days": 3}},
    ).json()
    assert "Updated" in synced["message"]["content"]
    assert synced["reveal"]["config_patches"][0]["config"]["window_days"] == 3

    confirmed = client.post("/chat/confirm", json={"session_id": sid})
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    assert confirmed.json()["status"] == "confirmed"
    assert "Confirmed" in confirmed.json()["message"]["content"]
    assert "What each step does" in confirmed.json()["message"]["content"]
    assert not (tmp_path / "pipelines").exists() or not list((tmp_path / "pipelines").glob("*"))


def test_bank_recon_is_not_hardcoded_invoice(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Bank reconciliation of statement vs ledger.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    upload_body = _upload(
        client,
        sid,
        [
            ("bank.csv", _csv(["date", "amount"], ["2024-01-01", "10"])),
            ("ledger.csv", _csv(["date", "amount"], ["2024-01-01", "10"])),
        ],
    ).json()
    assert _agents(upload_body).count("ingestion") == 2
    labels = {n["label"] for n in upload_body["pipeline"]["nodes"] if n["agent"] == "ingestion"}
    assert labels == {"bank", "ledger"}
    body = client.post("/chat/message", json={"session_id": sid, "content": "none"}).json()
    agents = _agents(body)
    assert "matcher" in agents
    assert "math" in agents
    assert "output" in agents
    assert "decision" not in agents
    matcher = next(n for n in body["pipeline"]["nodes"] if n["agent"] == "matcher")
    assert matcher["config"]["keys"] == ["date", "amount"]


def test_no_files_builds_virtual_ingest_nodes(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Bank reconciliation of statement vs ledger.")
    client.post("/chat/message", json={"session_id": sid, "content": "I don't have files"})
    body = client.post(
        "/chat/message",
        json={
            "session_id": sid,
            "content": "Bank CSV with date and amount; ledger file with date and amount.",
        },
    ).json()
    assert body.get("upload_offer") == "knowledge"
    agents = _agents(body)
    assert agents.count("ingestion") == 2
    started = client.post("/chat/message", json={"session_id": sid, "content": "none"}).json()
    assert "matcher" in _agents(started)


def test_variance_subset_no_matcher_no_decision(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Compute variance % on one spreadsheet and export Excel.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    body = _upload(
        client,
        sid,
        [("budget.csv", _csv(["actual", "budget"], ["30", "20"]))],
    ).json()
    assert _agents(body) == ["ingestion"]
    body = client.post("/chat/message", json={"session_id": sid, "content": "none"}).json()
    agents = _agents(body)
    assert set(agents) == {"ingestion", "math", "output"}
    assert "matcher" not in agents
    assert "decision" not in agents
    assert not any("knowledge" in n["id"] for n in body["pipeline"]["nodes"])


def test_knowledge_upload_shows_user_attachment(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Three-way invoice match of PO, goods receipt, and vendor invoice.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    _upload(client, sid, [("po.csv", _csv(["po"], ["1"]))])
    policy = _upload(
        client,
        sid,
        [("Treasury_Recon_SOP.txt", b"Uncleared items past 30 days are high risk. Cite this SOP.")],
        kind="knowledge",
    )
    assert policy.status_code == 200, policy.text
    body = policy.json()
    user_msg = body.get("user_message") or {}
    assert user_msg.get("role") == "user"
    assert "Treasury_Recon_SOP.txt" in user_msg.get("content", "")
    assert user_msg.get("meta", {}).get("kind") == "upload"
    assert user_msg.get("meta", {}).get("upload_kind") == "knowledge"
    assert any("knowledge" in (n.get("id") or "") or n.get("mode") == "knowledge" for n in (body.get("pipeline") or {}).get("nodes") or [])


def test_confirm_gate_and_handoff_at_cap(api) -> None:
    client, tmp_path = api
    sid = _session(client)
    blocked = client.post("/chat/confirm", json={"session_id": sid})
    assert blocked.status_code == 400

    _onboard(client, sid, workflow="Handoff-cap process that never feels done.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    _upload(client, sid, [("a.csv", _csv(["k"], ["1"]))])
    client.post("/chat/message", json={"session_id": sid, "content": "none"})
    last = {}
    for i in range(20):
        last = client.post(
            "/chat/message", json={"session_id": sid, "content": f"more detail {i}"}
        ).json()
        if last["question_count"] >= 15:
            break
    assert last["question_count"] == 15
    assert "cap" in last["message"]["content"].lower() or "expert" in last["message"]["content"].lower()

    frozen = client.post("/chat/handoff", json={"session_id": sid})
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "handoff"
    assert (tmp_path / "sessions" / f"{sid}.json").exists()
    pipe = tmp_path / "pipelines"
    assert not pipe.exists() or not list(pipe.glob("*"))
    assert client.post("/chat/confirm", json={"session_id": sid}).status_code == 400


def test_builder_skips_knowledge_without_files() -> None:
    session = InterviewSession(
        id="s",
        extra={
            "description": "match two files",
            "capabilities": {"matcher": True, "math": False, "decision": False, "output": True},
        },
        requirements=[ExtractedRequirement(id="m", kind="match", value={"keys": ["id"]})],
        uploads=[
            {"kind": "data", "file_id": "a", "path": "/tmp/a.csv", "name": "a.csv", "label": "A", "schema": []},
            {"kind": "data", "file_id": "b", "path": "/tmp/b.csv", "name": "b.csv", "label": "B", "schema": []},
        ],
    )
    pipeline = desired_pipeline(session)
    agents = [n.agent for n in pipeline.nodes]
    assert agents.count("ingestion") == 2
    assert "matcher" in agents
    assert "output" in agents
    assert all(n.mode != "knowledge" for n in pipeline.nodes)


def test_builder_wires_matcher_exceptions_into_decision_and_output() -> None:
    session = InterviewSession(
        id="s3",
        extra={
            "description": "three way invoice match",
            "capabilities": {
                "matcher": True,
                "math": True,
                "decision": True,
                "output": True,
                "keys": ["po_number", "po_line_id"],
            },
        },
        requirements=[
            ExtractedRequirement(
                id="m",
                kind="match",
                value={"keys": ["po_number", "po_line_id"], "mode": "structural"},
            ),
            ExtractedRequirement(
                id="math1",
                kind="math",
                value={"formula_en": "min of 2 percent or 50 dollars", "threshold": 50},
            ),
            ExtractedRequirement(
                id="d",
                kind="decision",
                value={"policy": "Tier-1 under 500 auto-approve unreceived invoices"},
            ),
            ExtractedRequirement(id="o", kind="output", value={"formats": ["xlsx"]}),
        ],
        uploads=[
            {"kind": "data", "file_id": "po", "path": "/tmp/po.xlsx", "name": "PO.xlsx", "label": "PO", "schema": []},
            {"kind": "data", "file_id": "gr", "path": "/tmp/gr.csv", "name": "GR.csv", "label": "GR", "schema": []},
            {"kind": "data", "file_id": "inv", "path": "/tmp/inv.pdf", "name": "Inv.pdf", "label": "Invoices", "schema": []},
            {"kind": "knowledge", "file_id": "pol", "path": "/tmp/p.pdf", "name": "policy.pdf", "label": "Policy"},
        ],
    )
    pipeline = desired_pipeline(session)
    agents = [n.agent for n in pipeline.nodes]
    assert agents.count("ingestion") == 4
    assert "matcher" in agents and "math" in agents and "decision" in agents and "output" in agents
    edge_keys = {(e.source, e.source_port, e.target) for e in pipeline.edges}
    assert ("matcher", "matched", "math") in edge_keys
    assert ("math", "default", "decision") in edge_keys
    assert ("matcher", "exceptions", "decision") in edge_keys
    assert ("matcher", "residuals", "decision") in edge_keys
    assert ("ingest_knowledge_pol", "default", "matcher") in edge_keys
    assert ("ingest_knowledge_pol", "default", "decision") in edge_keys
    assert ("decision", "approved", "output") in edge_keys
    assert ("decision", "flagged", "output") in edge_keys


def test_builder_exceptions_reach_output_when_no_decision() -> None:
    session = InterviewSession(
        id="s4",
        extra={
            "description": "bank recon",
            "capabilities": {"matcher": True, "math": True, "decision": False, "output": True},
        },
        requirements=[
            ExtractedRequirement(id="m", kind="match", value={"keys": ["amount", "reference_number"], "window_days": 2}),
            ExtractedRequirement(id="math1", kind="math", value={"formula_en": "previous plus deposits minus withdrawals"}),
            ExtractedRequirement(id="o", kind="pdf", value={"formats": ["pdf"]}),
        ],
        uploads=[
            {"kind": "data", "file_id": "bank", "path": "/tmp/b.csv", "name": "bank.csv", "label": "Bank", "schema": []},
            {"kind": "data", "file_id": "gl", "path": "/tmp/g.xlsx", "name": "gl.xlsx", "label": "GL", "schema": []},
        ],
    )
    pipeline = desired_pipeline(session)
    assert all(n.agent != "decision" for n in pipeline.nodes)
    edge_keys = {(e.source, e.source_port, e.target) for e in pipeline.edges}
    assert ("matcher", "matched", "math") in edge_keys
    assert ("math", "default", "output") in edge_keys
    assert ("matcher", "exceptions", "output") in edge_keys
    assert ("matcher", "residuals", "output") in edge_keys
    assert ("ingest_bank", "default", "math") in edge_keys
    assert ("ingest_gl", "default", "math") in edge_keys
    assert sum(1 for e in pipeline.edges if e.source == "ingest_bank" and e.target == "math") == 1
    out = next(n for n in pipeline.nodes if n.agent == "output")
    assert out.mode == "pdf"
    assert out.config["formats"] == ["pdf"]
    assert out.config["mode"] == "pdf"


def test_onboarding_step_order_is_code_owned() -> None:
    assert _advance_onboarding("role", "Treasury analyst")["next_step"] == "industry"
    assert _advance_onboarding("industry", "Retail")["capture"]["industry"] == "Retail"
    assert _advance_onboarding("ai_priorities", "Faster close")["next_step"] == "workflow"
    assert _advance_onboarding("workflow", "Daily bank recon")["next_step"] == "data_prompt"
    assert _advance_onboarding("data_prompt", "none")["next_step"] == "data_interview"
    assert _advance_onboarding("knowledge_prompt", "skip")["next_step"] == "done"


def test_irrelevant_answer_retries_once_then_skips(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Three-way invoice match of PO, goods receipt, and vendor invoice.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    _upload(client, sid, [("po.csv", _csv(["po"], ["1"]))])
    started = client.post("/chat/message", json={"session_id": sid, "content": "none"}).json()
    count = started["question_count"]
    retry = client.post("/chat/message", json={"session_id": sid, "content": "I want pizza"}).json()
    assert retry["question_count"] == count
    assert "same question" in retry["message"]["content"].lower()
    skipped = client.post("/chat/message", json={"session_id": sid, "content": "still pizza"}).json()
    assert "skip" in skipped["message"]["content"].lower()
    assert _agents(skipped)


def test_cannot_serve_explains_and_offers_expert(api) -> None:
    client, _tmp = api
    sid = _session(client)
    _onboard(client, sid, workflow="Three-way invoice match of PO, goods receipt, and vendor invoice.")
    client.post("/chat/message", json={"session_id": sid, "content": "yes"})
    _upload(client, sid, [("po.csv", _csv(["po"], ["1"]))])
    client.post("/chat/message", json={"session_id": sid, "content": "none"})
    body = client.post(
        "/chat/message",
        json={"session_id": sid, "content": "Post every result as an ERP mutation and live Slack."},
    ).json()
    assert body["cannot_serve"] is True
    assert body["suggest_handoff"] is True
    text = body["message"]["content"].lower()
    assert "expert" in text
    assert "erp" in text or "cannot" in text

