from app.agents.base import AgentRegistry, RunContext
from app.core.storage import Storage
from app.models.envelope import Envelope


class EchoAgent:
    name = "echo"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        return [env.model_copy(update={"emitted_by": "echo@v1"})]


def test_registry_register_and_get(tmp_path) -> None:
    registry = AgentRegistry()
    registry.register(EchoAgent)
    assert registry.names() == ["echo"]
    assert registry.get("echo") is EchoAgent
    agent = registry.create("echo")
    assert isinstance(agent, EchoAgent)
