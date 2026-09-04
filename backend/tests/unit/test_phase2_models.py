from __future__ import annotations

from pathlib import Path

from app.core.storage import Storage
from app.models.behavior import load_behavior
from app.models.chat import InterviewSession
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, SessionKnowledge


def test_behavior_yaml_roundtrip(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    store.write_yaml(
        {
            "name": "matcher",
            "version": "1.0",
            "modes": ["structural", "semantic"],
            "config": {"window_days": 2},
        },
        "agents",
        "matcher",
        "1.0.yaml",
    )
    loaded = load_behavior(store, "matcher", "1.0")
    assert loaded.ref == "matcher@1.0"
    assert loaded.behavior.modes == ["structural", "semantic"]
    assert loaded.behavior.config["window_days"] == 2


def test_session_starts_empty() -> None:
    session = InterviewSession(id="s1")
    assert session.status == "welcome"
    assert session.confirmed is False
    assert session.messages == []
    assert session.pipeline is None


def test_knowledge_retrieve_by_chunk_id() -> None:
    store = SessionKnowledge(
        session_id="s1",
        documents=[
            KnowledgeDocument(
                file_id="f1",
                original_path="/tmp/policy.pdf",
                chunks=[
                    KnowledgeChunk(id="c1", heading="Tolerance", text="2% or $50"),
                ],
            )
        ],
    )
    assert store.retrieve("c1").text == "2% or $50"
