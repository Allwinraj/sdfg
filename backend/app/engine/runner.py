from __future__ import annotations

import logging
import time
from typing import Any

from app.agents.base import AgentRegistry, RunContext
from app.core.llm import LLMProvider
from app.core.logging import bind_run, new_id
from app.core.storage import Storage
from app.engine.conditional import edge_accepts
from app.engine.dag import topological_levels
from app.engine.persist import save_run
from app.models.envelope import Envelope
from app.models.knowledge import SessionKnowledge
from app.models.pipeline import Node, Pipeline
from app.models.run import Run, RunStep


class PipelineRunner:
    def __init__(
        self,
        registry: AgentRegistry,
        storage: Storage,
        llm: LLMProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self.registry = registry
        self.storage = storage
        self.llm = llm
        self.logger = logger or logging.getLogger("nexus.runner")

    async def run(
        self,
        pipeline: Pipeline,
        *,
        run_id: str | None = None,
        knowledge: SessionKnowledge | None = None,
        seed: dict[str, Any] | None = None,
    ) -> Run:
        run = Run(
            id=run_id or new_id(),
            pipeline_id=pipeline.id,
            pipeline_version=pipeline.version,
        )
        run.mark_running()
        bind_run(run.id)
        outputs_by_node: dict[str, list[Envelope]] = {}
        failed = False

        try:
            for level in topological_levels(pipeline):
                steps = await self._run_level(
                    pipeline,
                    run,
                    level,
                    outputs_by_node,
                    knowledge,
                    seed or {},
                )
                run.steps.extend(steps)
                if any(step.status == "error" and pipeline.get_node(step.node_id).error_strategy == "fail_fast" for step in steps):
                    failed = True
                    break
                if any(step.status == "error" for step in steps):
                    failed = True
        except Exception as exc:
            failed = True
            run.error = str(exc)
            self.logger.exception("run %s crashed", run.id)

        run.mark_done(failed=failed)
        save_run(self.storage, run)
        return run

    async def _run_level(
        self,
        pipeline: Pipeline,
        run: Run,
        level: list[str],
        outputs_by_node: dict[str, list[Envelope]],
        knowledge: SessionKnowledge | None,
        seed: dict[str, Any],
    ) -> list[RunStep]:
        import asyncio

        tasks = [
            self._run_node(
                pipeline,
                run,
                pipeline.get_node(node_id),
                outputs_by_node,
                knowledge,
                seed,
            )
            for node_id in level
        ]
        steps = list(await asyncio.gather(*tasks))
        for step in steps:
            outputs_by_node[step.node_id] = list(step.outputs)
        return steps

    async def _run_node(
        self,
        pipeline: Pipeline,
        run: Run,
        node: Node,
        outputs_by_node: dict[str, list[Envelope]],
        knowledge: SessionKnowledge | None,
        seed: dict[str, Any],
    ) -> RunStep:
        incoming = pipeline.incoming(node.id)
        collected: list[Envelope] = []
        if incoming:
            for edge in incoming:
                produced = outputs_by_node.get(edge.source, [])
                matched = [env for env in produced if edge_accepts(edge, env)]
                collected.extend(matched)
            if not collected:
                return RunStep(
                    node_id=node.id,
                    agent=node.agent,
                    behavior_version=node.behavior_ref,
                    status="skipped",
                )
        else:
            collected = [
                Envelope(
                    run_id=run.id,
                    node_id=node.id,
                    emitted_by="runner",
                    payload=dict(seed),
                )
            ]

        ctx = RunContext(
            run_id=run.id,
            llm=self.llm,
            storage=self.storage,
            logger=self.logger,
            knowledge_store=knowledge,
            inputs=collected,
            node=node,
        )
        started = time.perf_counter()
        try:
            agent = self.registry.create(node.agent)
            outputs = await agent.execute(ctx, collected[0])
            duration = (time.perf_counter() - started) * 1000
            tagged = []
            for env in outputs:
                tagged.append(
                    env.model_copy(
                        update={
                            "run_id": run.id,
                            "node_id": node.id,
                            "emitted_by": env.emitted_by or node.behavior_ref or node.agent,
                        }
                    )
                )
            for env in tagged:
                for artifact in env.payload.get("artifacts") or []:
                    if artifact not in run.artifacts:
                        run.artifacts.append(str(artifact))
            return RunStep(
                node_id=node.id,
                agent=node.agent,
                behavior_version=node.behavior_ref,
                status="ok",
                inputs=collected,
                outputs=tagged,
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            error_env = Envelope(
                run_id=run.id,
                node_id=node.id,
                port="exceptions",
                payload={"error": str(exc)},
                emitted_by=node.behavior_ref or node.agent,
            )
            return RunStep(
                node_id=node.id,
                agent=node.agent,
                behavior_version=node.behavior_ref,
                status="error",
                inputs=collected,
                outputs=[] if node.error_strategy == "fail_fast" else [error_env],
                duration_ms=duration,
                error=str(exc),
            )
