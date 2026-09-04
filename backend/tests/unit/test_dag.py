from __future__ import annotations

import pytest

from app.engine.dag import DagError, topological_levels
from app.models.pipeline import Edge, Node, Pipeline


def _pipe(*pairs: tuple[str, str]) -> Pipeline:
    ids = []
    for src, dst in pairs:
        ids.extend([src, dst])
    nodes = [Node(id=i, agent="ingestion") for i in dict.fromkeys(ids)]
    edges = [
        Edge(id=f"e{n}", source=src, target=dst)
        for n, (src, dst) in enumerate(pairs)
    ]
    return Pipeline(id="p", nodes=nodes, edges=edges)


def test_topo_order() -> None:
    pipeline = _pipe(("a", "b"), ("b", "c"))
    levels = topological_levels(pipeline)
    assert levels == [["a"], ["b"], ["c"]]


def test_parallel_level() -> None:
    pipeline = _pipe(("a", "c"), ("b", "c"))
    levels = topological_levels(pipeline)
    assert set(levels[0]) == {"a", "b"}
    assert levels[1] == ["c"]


def test_cycle_rejected() -> None:
    pipeline = _pipe(("a", "b"), ("b", "a"))
    with pytest.raises(DagError):
        topological_levels(pipeline)
