from __future__ import annotations

import asyncio

from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.services.decision import (
    POLICY_LLM_CAP,
    POLICY_LLM_TIMEOUT_SECONDS,
    collect_records,
    enrich_record,
    judge_record,
    passages_for,
    resolve_authority,
    resolve_mode,
    rule_verdict,
    split_ports,
    strip_meta,
)


class Decision:
    """Judgment, policy interpretation, and approval routing. Does not compute amounts."""

    name = "decision"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        mode = resolve_mode(config.get("mode") or (ctx.node.mode if ctx.node else None))
        authority = resolve_authority(config.get("authority"))
        threshold = float(config.get("confidence_threshold", 0.85))
        policy = str(config.get("policy") or "").strip()
        temperature = float(config.get("temperature", 0.1))
        limit = int(config.get("max_chunks", 3))
        records = collect_records(ctx.inputs or [env])
        judged: list[tuple | None] = [None] * len(records)

        async def _judge(index: int, record: dict) -> None:
            clean = strip_meta(record)
            passages = passages_for(ctx.knowledge_store, clean, policy, limit=limit)
            try:
                raw = await asyncio.wait_for(
                    judge_record(
                        ctx.llm,
                        clean,
                        mode=mode,
                        policy=policy,
                        passages=passages,
                        temperature=temperature,
                    ),
                    timeout=8.0,
                )
            except (TimeoutError, asyncio.TimeoutError):
                raw = rule_verdict(record, policy)
                passages = []
            judged[index] = enrich_record(
                clean,
                raw,
                mode=mode,
                authority=authority,
                threshold=threshold,
                passages=passages,
                knowledge=ctx.knowledge_store,
            )

        llm_indexes = list(range(min(len(records), POLICY_LLM_CAP))) if policy else []
        for i, record in enumerate(records):
            if i in llm_indexes:
                continue
            clean = strip_meta(record)
            judged[i] = enrich_record(
                clean,
                rule_verdict(record, policy),
                mode=mode,
                authority=authority,
                threshold=threshold,
                passages=[],
                knowledge=ctx.knowledge_store,
            )

        if llm_indexes:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(_judge(i, records[i]) for i in llm_indexes)),
                    timeout=POLICY_LLM_TIMEOUT_SECONDS,
                )
            except (TimeoutError, asyncio.TimeoutError):
                for i in llm_indexes:
                    if judged[i] is None:
                        clean = strip_meta(records[i])
                        judged[i] = enrich_record(
                            clean,
                            rule_verdict(records[i], policy),
                            mode=mode,
                            authority=authority,
                            threshold=threshold,
                            passages=[],
                            knowledge=ctx.knowledge_store,
                        )

        ports = split_ports([item for item in judged if item is not None])
        node_id = ctx.node.id if ctx.node else env.node_id
        envelopes: list[Envelope] = []
        for port, rows in ports.items():
            if not rows:
                continue
            envelopes.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=node_id,
                    port=port,
                    payload={
                        "kind": "decisions",
                        "rows": rows,
                        "mode": mode,
                        "authority": authority,
                    },
                    emitted_by="decision@v1",
                )
            )
        return envelopes


registry.register(Decision)
