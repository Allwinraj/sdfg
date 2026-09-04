from __future__ import annotations

from app.engine.schema_sync import apply_schema_overrides, propagate_schema
from app.models.pipeline import Edge, Node, Pipeline


def test_schema_override_propagates_to_matcher_keys() -> None:
    ingest = Node(
        id="in",
        agent="ingestion",
        config={
            "schema": [
                {"name": "InvNo", "type": "string"},
                {"name": "Amt", "type": "number"},
            ]
        },
    )
    matcher = Node(
        id="m",
        agent="matcher",
        config={"match_keys": ["InvNo", "Amt"]},
    )
    pipeline = Pipeline(
        id="p",
        nodes=[ingest, matcher, Node(id="out", agent="output")],
        edges=[
            Edge(id="e1", source="in", target="m"),
            Edge(id="e2", source="m", target="out"),
        ],
    )
    updated, renamed = apply_schema_overrides(
        ingest,
        {"InvNo": {"name": "invoice_no"}, "Amt": {"type": "decimal"}},
    )
    pipeline.nodes = [updated if n.id == "in" else n for n in pipeline.nodes]
    synced = propagate_schema(pipeline, "in")
    assert renamed == {"InvNo": "invoice_no"}
    matcher_cfg = synced.get_node("m").config
    assert matcher_cfg["match_keys"] == ["invoice_no", "Amt"]
    assert synced.get_node("in").config["schema"][1]["type"] == "decimal"
    assert synced.get_node("m").config["upstream_schema"][0]["name"] == "invoice_no"
    assert "upstream_schema" not in synced.get_node("in").config
