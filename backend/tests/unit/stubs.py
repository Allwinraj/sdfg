from __future__ import annotations

from app.agents.base import RunContext
from app.models.envelope import Envelope


class StubIngest:
    name = "ingestion"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        rows = (ctx.node.config if ctx.node else {}).get("rows") or env.payload.get("rows") or [{"id": 1}]
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=env.node_id,
                port="default",
                payload={"rows": rows, "kind": "data"},
                emitted_by="ingestion@stub",
            )
        ]


class StubOutput:
    name = "output"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                port="default",
                payload={"delivered": True, "from": env.payload},
                emitted_by="output@stub",
            )
        ]


class StubMatcher:
    name = "matcher"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        rows = []
        for incoming in ctx.inputs:
            rows.extend(incoming.payload.get("rows") or [])
        matched = []
        residuals = []
        exceptions = []
        for row in rows:
            bucket = row.get("bucket", "matched")
            if bucket == "residuals":
                residuals.append(row)
            elif bucket == "exceptions":
                exceptions.append(row)
            else:
                matched.append(row)
        out: list[Envelope] = []
        nid = ctx.node.id if ctx.node else env.node_id
        if matched:
            out.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=nid,
                    port="matched",
                    payload={"rows": matched},
                    emitted_by="matcher@stub",
                )
            )
        if residuals:
            out.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=nid,
                    port="residuals",
                    payload={"rows": residuals},
                    emitted_by="matcher@stub",
                )
            )
        if exceptions:
            out.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=nid,
                    port="exceptions",
                    payload={"rows": exceptions},
                    emitted_by="matcher@stub",
                )
            )
        return out


class StubMath:
    name = "math"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        rows = list(env.payload.get("rows") or [])
        for row in rows:
            if row.get("bad"):
                row["error"] = "isolated"
                continue
            row["flag"] = row.get("amount", 0) > 10
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                payload={"rows": rows},
                emitted_by="math@stub",
            )
        ]


class StubDecision:
    name = "decision"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                port="flagged",
                payload=env.payload,
                emitted_by="decision@stub",
            )
        ]


class BoomAgent:
    name = "math"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        raise RuntimeError("node exploded")


class SlowIngest:
    name = "ingestion"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        import asyncio
        import time

        started = time.perf_counter()
        await asyncio.sleep(0.05)
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=env.node_id,
                payload={"slept": time.perf_counter() - started, "label": env.node_id},
                emitted_by="ingestion@stub",
            )
        ]
