from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.logging import new_id
from app.core.storage import Storage
from app.engine.persist import load_run
from app.main import app
from app.models.chat import InterviewSession
from app.models.pipeline import Edge, Node, Pipeline
from app.services.sessions import save_session
from tests.unit.ingest_files import write_csv


class NullLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        raise AssertionError("unused")

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        raise AssertionError("unused")


class ApproveLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        if model_role == "extraction":
            return {"facts": []}
        return {
            "verdict": "approved",
            "confidence": 0.96,
            "explanation": "Within policy.",
        }


def _put_session(storage: Storage, pipeline: Pipeline, *, confirmed: bool) -> str:
    session = InterviewSession(
        id=new_id(),
        status="confirmed" if confirmed else "interview",
        confirmed=confirmed,
        pipeline=pipeline.model_dump(mode="json"),
    )
    save_session(storage, session)
    return session.id


def test_agent_catalog_and_versions(tmp_path) -> None:
    with TestClient(app) as client:
        app.state.storage = Storage(tmp_path)
        app.state.llm = NullLLM()
        listing = client.get("/agents")
        assert listing.status_code == 200
        names = [a["name"] for a in listing.json()["agents"]]
        assert names == ["ingestion", "matcher", "math", "decision", "output"]
        matcher = next(a for a in listing.json()["agents"] if a["name"] == "matcher")
        schema = matcher["config_schema"]
        assert "keys" in schema
        assert "flags" in schema
        blob = str(schema).lower()
        assert "tolerance" not in blob
        assert "slack" not in str(listing.json()).lower()
        versions = client.get("/agents/matcher/versions")
        assert versions.status_code == 200
        assert versions.json()["versions"][0]["version"] == "v1"
        assert client.get("/agents/unknown/versions").status_code == 404


def test_save_to_library_requires_confirm_and_lists(tmp_path) -> None:
    storage = Storage(tmp_path)
    pipeline = Pipeline(
        id="draft",
        name="draft",
        nodes=[Node(id="in", agent="ingestion"), Node(id="out", agent="output")],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    with TestClient(app) as client:
        app.state.storage = storage
        app.state.llm = NullLLM()
        open_id = _put_session(storage, pipeline, confirmed=False)
        denied = client.post(
            "/pipelines",
            json={"session_id": open_id, "name": "nope", "version": "v1"},
        )
        assert denied.status_code == 400

        sid = _put_session(storage, pipeline, confirmed=True)
        created = client.post(
            "/pipelines",
            json={"session_id": sid, "name": "vendor_export", "version": "v1.0"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "vendor_export"
        assert body["version"] == "v1.0"
        assert body["id"] != sid
        listed = client.get("/pipelines").json()["pipelines"]
        assert any(p["id"] == body["id"] and p["name"] == "vendor_export" for p in listed)
        loaded = client.get(f"/pipelines/{body['id']}")
        assert loaded.status_code == 200
        assert [n["agent"] for n in loaded.json()["nodes"]] == ["ingestion", "output"]
        preview = client.post("/pipelines/preview", json={"session_id": sid})
        assert preview.status_code == 200
        assert preview.json()["confirmed"] is True
        assert client.post(f"/pipelines/{body['id']}/rerun").status_code == 404


def test_sparse_studio_run_and_artifact_download(tmp_path) -> None:
    storage = Storage(tmp_path)
    csv_path = write_csv(tmp_path / "vendors.csv", [["Vendor", "Amount"], ["Acme", "12.50"]])
    pipeline = Pipeline(
        id="sparse",
        name="sparse",
        version="v1",
        nodes=[
            Node(id="in", agent="ingestion", config={"mode": "data", "path": str(csv_path)}),
            Node(
                id="out",
                agent="output",
                config={"mode": "both", "filename": "sparse", "title": "Sparse pack"},
            ),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    with TestClient(app) as client:
        app.state.storage = storage
        app.state.llm = NullLLM()
        sid = _put_session(storage, pipeline, confirmed=True)
        assert (
            client.post(
                "/runs",
                json={"session_id": _put_session(storage, pipeline, confirmed=False)},
            ).status_code
            == 400
        )
        saved = client.post(
            "/pipelines", json={"session_id": sid, "name": "sparse_export", "version": "v1"}
        ).json()
        run = client.post("/runs", json={"pipeline_id": saved["id"]})
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "completed"
        by = {s["node_id"]: s for s in body["steps"]}
        assert by["in"]["emitted_by"] == ["ingestion@v1"]
        assert by["out"]["emitted_by"] == ["output@v1"]
        assert body["artifacts"]
        name = body["artifacts"][0]
        download = client.get(f"/runs/{body['id']}/artifacts/{name}")
        assert download.status_code == 200
        assert len(download.content) > 20
        snap = client.get(f"/runs/{body['id']}/snapshot")
        assert snap.status_code == 200
        assert snap.json()["run"]["id"] == body["id"]
        assert snap.json()["pipeline"]["id"] == saved["id"]


def test_full_chain_emitted_by_and_math_gate_edit(tmp_path) -> None:
    storage = Storage(tmp_path)
    left = write_csv(tmp_path / "a.csv", [["k", "amount"], ["1", "30"], ["2", "8"]])
    right = write_csv(tmp_path / "b.csv", [["k", "amount"], ["1", "20"], ["2", "10"]])
    pipeline = Pipeline(
        id="full",
        name="full",
        version="v1",
        nodes=[
            Node(id="i1", agent="ingestion", config={"mode": "data", "path": str(left)}),
            Node(id="i2", agent="ingestion", config={"mode": "data", "path": str(right)}),
            Node(id="m", agent="matcher", config={"mode": "structural", "keys": ["k"]}),
            Node(
                id="math",
                agent="math",
                config={
                    "mode": "hybrid",
                    "ast": "1 + 1",
                    "gate_ast": "1 > 2",
                    "output_column": "n",
                },
            ),
            Node(
                id="dec",
                agent="decision",
                config={"mode": "approval", "authority": "autonomous", "confidence_threshold": 0.5},
            ),
            Node(id="out", agent="output", config={"formats": ["xlsx"], "filename": "full"}),
        ],
        edges=[
            Edge(id="e1", source="i1", target="m"),
            Edge(id="e2", source="i2", target="m"),
            Edge(id="e3", source="m", source_port="matched", target="math"),
            Edge(id="e4", source="math", target="dec"),
            Edge(id="e5", source="dec", source_port="approved", target="out"),
        ],
    )
    with TestClient(app) as client:
        app.state.storage = storage
        app.state.llm = ApproveLLM()
        sid = _put_session(storage, pipeline, confirmed=True)
        first = client.post("/runs", json={"session_id": sid})
        assert first.status_code == 200
        assert first.json()["status"] == "completed"
        ok = [s for s in first.json()["steps"] if s["status"] == "ok"]
        by_agent = {s["agent"]: s for s in ok}
        assert "ingestion@v1" in by_agent["ingestion"]["emitted_by"]
        assert by_agent["matcher"]["emitted_by"] == ["matcher@v1"]
        assert by_agent["math"]["emitted_by"] == ["math@v1"]
        assert by_agent["decision"]["emitted_by"] == ["decision@v1"]
        assert by_agent["output"]["emitted_by"] == ["output@v1"]

        run = load_run(storage, first.json()["id"])
        math_step = next(s for s in run.steps if s.node_id == "math")
        first_flags = [row.get("flag") for row in math_step.outputs[0].payload["rows"]]
        assert first_flags and first_flags[0] is False

        synced = client.post(
            "/chat/sync-node",
            json={"session_id": sid, "node_id": "math", "config": {"gate_ast": "1 > 0"}},
        )
        assert synced.status_code == 200
        second = client.post("/runs", json={"session_id": sid})
        assert second.status_code == 200
        run2 = load_run(storage, second.json()["id"])
        math2 = next(s for s in run2.steps if s.node_id == "math")
        second_flags = [row.get("flag") for row in math2.outputs[0].payload["rows"]]
        assert second_flags and second_flags[0] is True
        assert first.json()["id"] != second.json()["id"]


class EchoLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "The math node adds 1+1 from the compiled formula."

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        return {"facts": []}


def test_library_same_filename_new_values_and_ask(tmp_path) -> None:
    storage = Storage(tmp_path)
    csv_path = write_csv(tmp_path / "vendors.csv", [["Vendor", "Amount"], ["Acme", "12.50"]])
    pipeline = Pipeline(
        id="draft",
        name="draft",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                mode="data",
                config={"mode": "data", "path": str(csv_path), "filename": "vendors.csv"},
            ),
            Node(id="out", agent="output", config={"mode": "excel", "filename": "pack", "title": "Vendors"}),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    with TestClient(app) as client:
        app.state.storage = storage
        app.state.llm = EchoLLM()
        sid = _put_session(storage, pipeline, confirmed=True)
        saved = client.post(
            "/pipelines", json={"session_id": sid, "name": "vendor_ops", "version": "v1"}
        )
        assert saved.status_code == 201
        pid = saved.json()["id"]
        slots = saved.json()["meta"]["file_slots"]
        assert slots[0]["filename"] == "vendors.csv"
        listed = client.get("/pipelines").json()["pipelines"]
        card = next(p for p in listed if p["id"] == pid)
        assert card["file_slots"][0]["filename"] == "vendors.csv"

        denied = client.post(
            f"/pipelines/{pid}/files",
            files=[("files", ("other.csv", b"Vendor,Amount\nX,1\n", "text/csv"))],
        )
        assert denied.status_code == 400

        swapped = write_csv(tmp_path / "vendors2.csv", [["Vendor", "Amount"], ["Beta", "99"]])
        uploaded = client.post(
            f"/pipelines/{pid}/files",
            files=[("files", ("vendors.csv", swapped.read_bytes(), "text/csv"))],
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["written"] == ["vendors.csv"]
        assert uploaded.json()["missing_files"] == []

        run = client.post(f"/pipelines/{pid}/run")
        assert run.status_code == 200
        assert run.json()["status"] == "completed"
        asked = client.post(
            f"/pipelines/{pid}/ask",
            json={"run_id": run.json()["id"], "question": "How was this calculated?"},
        )
        assert asked.status_code == 200
        assert "math" in asked.json()["answer"].lower() or "formula" in asked.json()["answer"].lower()


def test_library_run_stream_emits_node_events(tmp_path) -> None:
    storage = Storage(tmp_path)
    csv_path = write_csv(tmp_path / "vendors.csv", [["Vendor", "Amount"], ["Acme", "12.50"]])
    pipeline = Pipeline(
        id="draft",
        name="draft",
        nodes=[
            Node(
                id="in",
                agent="ingestion",
                mode="data",
                label="Vendors",
                config={"mode": "data", "path": str(csv_path), "filename": "vendors.csv"},
            ),
            Node(id="out", agent="output", config={"mode": "excel", "filename": "pack", "title": "Vendors"}),
        ],
        edges=[Edge(id="e1", source="in", target="out")],
    )
    with TestClient(app) as client:
        app.state.storage = storage
        app.state.llm = EchoLLM()
        sid = _put_session(storage, pipeline, confirmed=True)
        saved = client.post("/pipelines", json={"session_id": sid, "name": "vendor_ops", "version": "v1"})
        pid = saved.json()["id"]
        swapped = write_csv(tmp_path / "vendors2.csv", [["Vendor", "Amount"], ["Beta", "99"]])
        client.post(
            f"/pipelines/{pid}/files",
            files=[("files", ("vendors.csv", swapped.read_bytes(), "text/csv"))],
        )
        with client.stream("POST", f"/pipelines/{pid}/run/stream") as response:
            assert response.status_code == 200
            text = "".join(response.iter_text())
        assert "node_start" in text
        assert "node_finish" in text
        assert '"type": "result"' in text or '"type":"result"' in text
        assert "summary" in text

