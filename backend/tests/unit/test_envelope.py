from app.models.envelope import Envelope


def test_envelope_defaults() -> None:
    env = Envelope(run_id="r1", node_id="n1", emitted_by="ingestor@v1")
    assert env.port == "default"
    assert env.payload == {}
    assert env.knowledge_context is None
    dumped = env.model_dump()
    assert dumped["emitted_by"] == "ingestor@v1"
