from __future__ import annotations

import json
from typing import Any

from app.core.llm import LLMError, LLMProvider
from app.models.envelope import Envelope, EnvelopePort
from app.models.knowledge import SessionKnowledge
from app.services.knowledge import rank_chunks

VERDICT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "confidence", "explanation"],
    "properties": {
        "verdict": {"type": "string"},
        "confidence": {"type": "number"},
        "explanation": {"type": "string"},
        "remediation": {"type": "string"},
        "risk_category": {"type": "string"},
        "severity": {"type": "string"},
        "citation": {
            "type": "object",
            "properties": {
                "document": {"type": "string"},
                "section": {"type": "string"},
                "chunk_id": {"type": "string"},
            },
        },
    },
}

_MODE_ALIASES = {
    "anomaly": "anomaly",
    "anomaly_risk": "anomaly",
    "classification": "anomaly",
    "anomaly_and_risk": "anomaly",
    "policy": "policy",
    "policy_contract": "policy",
    "interpretation": "policy",
    "policy_and_contract": "policy",
    "approval": "approval",
    "approval_gateway": "approval",
    "gateway": "approval",
    "approval_and_escalation": "approval",
}

_VERDICT_ALIASES = {
    "approved": "approved",
    "approve": "approved",
    "ok": "approved",
    "flagged": "flagged",
    "flag": "flagged",
    "review": "flagged",
    "flagged_for_review": "flagged",
    "escalated": "escalated",
    "escalate": "escalated",
    "management": "escalated",
    "escalated_to_management": "escalated",
}

_MODE_PROMPTS = {
    "anomaly": (
        "Mode: Anomaly & Risk Classification. "
        "Detect unusual, suspicious, or structurally odd items. "
        "Set risk_category and severity. "
        "Map low risk to approved, medium to flagged, high/critical to escalated."
    ),
    "policy": (
        "Mode: Policy & Contract Interpretation. "
        "Judge the record against the decision policy and retrieved passages. "
        "Cite the passage that supports the verdict."
    ),
    "approval": (
        "Mode: Approval & Escalation Gateway. "
        "Render a governed verdict of approved, flagged, or escalated."
    ),
}


def collect_records(inputs: list[Envelope]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for env in inputs:
        payload = env.payload or {}
        if payload.get("kind") == "knowledge":
            continue
        if isinstance(payload.get("rows"), list):
            rows.extend(dict(row) for row in payload["rows"] if isinstance(row, dict))
        elif payload.get("kind") in {"data", "table", "matches"}:
            continue
        elif payload:
            rows.append(dict(payload))
    return rows


def passages_for(
    knowledge: SessionKnowledge | None,
    record: dict[str, Any],
    policy: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if knowledge is None:
        return []
    query = f"{policy}\n{json.dumps(record, default=str)}"
    ranked = rank_chunks(knowledge, query, limit=limit)
    out: list[dict[str, Any]] = []
    for chunk_id, _score in ranked:
        chunk = knowledge.retrieve(chunk_id)
        document = next(
            (doc for doc in knowledge.documents if any(c.id == chunk_id for c in doc.chunks)),
            None,
        )
        out.append(
            {
                "chunk_id": chunk.id,
                "section": chunk.heading,
                "text": chunk.text,
                "document": document.file_id if document else "",
                "path": document.original_path if document else "",
            }
        )
    return out


async def judge_record(
    llm: LLMProvider,
    record: dict[str, Any],
    *,
    mode: str,
    policy: str,
    passages: list[dict[str, Any]],
    temperature: float,
) -> dict[str, Any]:
    catalog = "\n\n".join(
        f"[chunk_id={p['chunk_id']} document={p['document']} section={p['section']}]\n{p['text']}"
        for p in passages
    ) or "(no retrieved passages)"
    prompt = (
        f"{_MODE_PROMPTS[mode]}\n"
        f"Decision policy:\n{policy or '(none provided)'}\n\n"
        f"Retrieved passages:\n{catalog}\n\n"
        f"Record:\n{json.dumps(record, default=str)}\n\n"
        "verdict must be one of: approved, flagged, escalated. "
        "confidence is 0.0–1.0. "
        "If you use a passage, set citation.chunk_id to that chunk_id. "
        "Do not invent chunk ids."
    )
    try:
        return await llm.complete_json("general", prompt, VERDICT_JSON_SCHEMA, temperature)
    except LLMError:
        return {
            "verdict": "flagged",
            "confidence": 0.0,
            "explanation": "Could not complete a model verdict for this row.",
        }


def enrich_record(
    record: dict[str, Any],
    raw: dict[str, Any],
    *,
    mode: str,
    authority: str,
    threshold: float,
    passages: list[dict[str, Any]],
    knowledge: SessionKnowledge | None,
) -> tuple[EnvelopePort, dict[str, Any]]:
    verdict = _normalize_verdict(raw.get("verdict"))
    confidence = _clamp_confidence(raw.get("confidence"))
    citation = _citation(raw.get("citation"), passages, knowledge)
    held = authority == "advisory"
    port = _route(verdict, confidence, authority, threshold)
    item = {
        "source": record,
        "verdict": verdict,
        "confidence": confidence,
        "explanation": str(raw.get("explanation") or ""),
        "remediation": raw.get("remediation") or None,
        "policy_citation": citation,
        "authority": authority,
        "held_for_review": held,
        "mode": mode,
    }
    if raw.get("risk_category"):
        item["risk_category"] = raw["risk_category"]
    if raw.get("severity"):
        item["severity"] = raw["severity"]
    return port, item


def split_ports(items: list[tuple[EnvelopePort, dict[str, Any]]]) -> dict[EnvelopePort, list[dict[str, Any]]]:
    ports: dict[EnvelopePort, list[dict[str, Any]]] = {
        "approved": [],
        "flagged": [],
        "escalated": [],
    }
    for port, row in items:
        ports[port].append(row)
    return ports


def resolve_mode(value: str | None) -> str:
    key = (value or "approval").lower().replace(" ", "_").replace("-", "_")
    return _MODE_ALIASES.get(key, "approval")


def resolve_authority(value: str | None) -> str:
    key = (value or "autonomous").lower()
    return "advisory" if key == "advisory" else "autonomous"


def _normalize_verdict(value: Any) -> str:
    key = str(value or "flagged").strip().lower().replace(" ", "_").replace("-", "_")
    if key in _VERDICT_ALIASES:
        return _VERDICT_ALIASES[key]
    if key in {"high", "critical", "severe"}:
        return "escalated"
    if key in {"medium", "moderate"}:
        return "flagged"
    if key in {"low"}:
        return "approved"
    return "flagged"


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _route(verdict: str, confidence: float, authority: str, threshold: float) -> EnvelopePort:
    if authority == "advisory":
        return "flagged"
    if verdict == "approved" and confidence < threshold:
        return "flagged"
    if verdict == "escalated":
        return "escalated"
    if verdict == "approved":
        return "approved"
    return "flagged"


def _citation(
    raw: Any,
    passages: list[dict[str, Any]],
    knowledge: SessionKnowledge | None,
) -> dict[str, Any] | None:
    cited: dict[str, Any] = {}
    if isinstance(raw, dict):
        cited = {k: raw[k] for k in ("document", "section", "chunk_id") if raw.get(k)}
    chunk_id = cited.get("chunk_id")
    if chunk_id and knowledge is not None:
        try:
            chunk = knowledge.retrieve(str(chunk_id))
        except KeyError:
            chunk_id = None
        else:
            cited["chunk_id"] = chunk.id
            cited.setdefault("section", chunk.heading)
    elif chunk_id:
        cited.pop("chunk_id", None)
        chunk_id = None
    if not chunk_id and passages:
        top = passages[0]
        cited.setdefault("chunk_id", top["chunk_id"])
        cited.setdefault("section", top["section"])
        cited.setdefault("document", top["document"])
        if knowledge is not None:
            knowledge.retrieve(top["chunk_id"])
    if not cited:
        return None
    return cited
