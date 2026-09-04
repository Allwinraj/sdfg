from __future__ import annotations

import re

import pytest

from app.core.llm import _validate_json_schema
from app.core.storage import Storage
from app.models.knowledge import KnowledgeDocument, SessionKnowledge
from app.services.knowledge import (
    FACTS_JSON_SCHEMA,
    chunk_text,
    extract_facts,
    load_knowledge,
    rank_chunks,
    save_knowledge,
)


class FakeLLM:
    async def complete(self, model_role, prompt, temperature=0.0) -> str:
        return "{}"

    async def complete_json(self, model_role, prompt, schema, temperature=0.0):
        ids = re.findall(r"chunk_id=([^\s\]]+)", prompt)
        return {
            "facts": [
                {
                    "id": "tol-1",
                    "kind": "threshold",
                    "value": {"pct": "0.02", "amount": "50"},
                    "chunk_id": ids[0],
                }
            ]
        }


def test_chunk_and_retrieve() -> None:
    text = "TOLERANCE POLICY\nAllow 2 percent.\n\nAPPROVAL RULES\nFlag rush freight."
    chunks = chunk_text(text, file_id="pol")
    headings = {c.heading for c in chunks}
    assert "TOLERANCE POLICY" in headings
    first = chunks[0]
    assert first.text


@pytest.mark.asyncio
async def test_extract_facts_matches_schema() -> None:
    chunks = chunk_text(
        "TOLERANCE POLICY\nVariance of 2 percent or 50 is acceptable.",
        file_id="pol",
    )
    facts = await extract_facts(FakeLLM(), chunks)
    payload = {"facts": [f.model_dump(mode="json") for f in facts]}
    _validate_json_schema(payload, FACTS_JSON_SCHEMA)
    assert facts[0].chunk_id == chunks[0].id
    assert facts[0].kind == "threshold"


def test_rank_chunks_then_retrieve() -> None:
    chunks = chunk_text(
        "TOLERANCE POLICY\nAllow 2 percent or 50.\n\nRUSH FREIGHT\nFlag rush freight over 10 percent.",
        file_id="pol",
    )
    knowledge = SessionKnowledge(
        session_id="s1",
        documents=[
            KnowledgeDocument(
                file_id="pol",
                original_path="/tmp/pol.pdf",
                chunks=chunks,
            )
        ],
    )
    ranked = rank_chunks(knowledge, "rush freight surcharge", limit=1)
    assert ranked
    chunk = knowledge.retrieve(ranked[0][0])
    assert "freight" in chunk.text.lower() or "freight" in chunk.heading.lower()


def test_save_load_and_retrieve(tmp_path) -> None:
    chunks = chunk_text("SECTION A\nKeep original wording here.", file_id="doc")
    knowledge = SessionKnowledge(
        session_id="s1",
        documents=[
            KnowledgeDocument(
                file_id="doc",
                original_path="/tmp/doc.pdf",
                chunks=chunks,
            )
        ],
    )
    store = Storage(tmp_path)
    save_knowledge(store, knowledge)
    loaded = load_knowledge(store, "s1")
    assert loaded.retrieve(chunks[0].id).text == chunks[0].text
