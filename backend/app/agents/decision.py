from __future__ import annotations

from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.services.decision import (
    collect_records,
    enrich_record,
    judge_record,
    passages_for,
    resolve_authority,
    resolve_mode,
    split_ports,
)


class Decision:
    """Judgment, policy interpretation, and approval routing. Does not compute amounts."""

    name = "decision"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        mode = resolve_mode(config.get("mode") or (ctx.node.mode if ctx.node else None))
        authority = resolve_authority(config.get("authority"))
        threshold = float(config.get("confidence_threshold", 0.85))
        policy = str(config.get("policy") or "")
        temperature = float(config.get("temperature", 0.1))
        limit = int(config.get("max_chunks", 3))
        records = collect_records(ctx.inputs or [env])
        judged: list[tuple] = []
        for record in records:
            passages = passages_for(ctx.knowledge_store, record, policy, limit=limit)
            raw = await judge_record(
                ctx.llm,
                record,
                mode=mode,
                policy=policy,
                passages=passages,
                temperature=temperature,
            )
            judged.append(
                enrich_record(
                    record,
                    raw,
                    mode=mode,
                    authority=authority,
                    threshold=threshold,
                    passages=passages,
                    knowledge=ctx.knowledge_store,
                )
            )
        ports = split_ports(judged)
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
