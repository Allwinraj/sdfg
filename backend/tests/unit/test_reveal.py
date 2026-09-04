from __future__ import annotations

from app.engine.reveal import apply_reveal
from app.models.chat import ConfigPatch, ProgressiveReveal
from app.models.pipeline import Edge, Node, Pipeline


def test_upsert_remove_and_patch() -> None:
    pipeline = Pipeline(
        id="p",
        nodes=[
            Node(id="ingest", agent="ingestion", config={"k": 1}),
            Node(id="gone", agent="matcher"),
        ],
        edges=[Edge(id="e1", source="ingest", target="gone")],
    )
    delta = ProgressiveReveal(
        remove_node_ids=["gone"],
        remove_edge_ids=["e1"],
        upsert_nodes=[
            Node(id="math", agent="math", config={"shape": "per-row"}),
            Node(id="ingest", agent="ingestion", label="PO file"),
        ],
        upsert_edges=[Edge(id="e2", source="ingest", target="math")],
        config_patches=[ConfigPatch(node_id="ingest", config={"k": 2, "sheet": "A"})],
    )
    out = apply_reveal(pipeline, delta)
    ids = {n.id for n in out.nodes}
    assert ids == {"ingest", "math"}
    ingest = out.get_node("ingest")
    assert ingest.label == "PO file"
    assert ingest.config["k"] == 2
    assert ingest.config["sheet"] == "A"
    assert [e.id for e in out.edges] == ["e2"]
