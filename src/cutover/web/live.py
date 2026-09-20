"""Live, observable governed run: one mapping suggestion, streamed step by step."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cutover.core.agent import AgentContext
from cutover.governance.bridge import (
    GovernanceSettings,
    build_gateway,
    load_dispatch_tiers,
    tier_for_score,
    tier_output_cap,
)
from cutover.plugins.mapping import MappingSuggestionAgent, check_mapping, correct_mapping
from cutover.refinement import ArtifactBranch, Attempt, RefinementPolicy, pass_rate_from_checks
from cutover.telemetry.sink import InMemoryTelemetrySink

SESSION_BUDGET_USD = 0.05


def complexity_score(columns: int, alerts: int) -> float:
    """Provisional heuristic: 36 + 2 per column + 4 per profile alert, capped at 100. Calibrate it."""
    return float(min(100, 36 + 2 * columns + 4 * alerts))


def run_mapping_stream(
    *,
    profile: dict[str, Any],
    target: str,
    dataset_id: int,
    db_path: Path,
    provider: Any,
    pricing: Any,
    model: str,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    """Run one governed mapping suggestion, calling ``emit`` with an event at every step."""
    started = time.perf_counter()

    def send(event: dict[str, Any]) -> None:
        event["t_ms"] = round((time.perf_counter() - started) * 1000)
        emit(event)

    try:
        columns = [{"name": c["name"], "type": c["type"]} for c in profile["columns"]]
        score = complexity_score(len(columns), len(profile["flags"]))
        tier = tier_for_score(score)
        caps = next(t for t in load_dispatch_tiers() if t["id"] == tier)
        send({"type": "run.start", "columns": len(columns), "target": target, "model": model})

        sink = InMemoryTelemetrySink()
        gateway = build_gateway(GovernanceSettings(db_path=db_path), provider, on_event=send)
        agent = MappingSuggestionAgent(
            gateway, provider="deepseek", model=model, session_budget_usd=SESSION_BUDGET_USD,
            telemetry=sink, pricing=pricing,
        )
        artifact_id = f"mapping-{dataset_id}"
        payload = {
            "artifact_id": artifact_id, "project_id": "cutover-web",
            "complexity_score": score, "target": target, "source_columns": columns,
        }
        prompt = agent.build_prompt(payload)

        from tollgate.context.tokens import estimate_tokens

        tokens = estimate_tokens(prompt)
        send({"type": "payload.built", "prompt": prompt, "tokens": tokens})
        send({
            "type": "gate.scored", "score": score, "tier": tier,
            "input_cap": caps["input_token_cap"], "output_cap": caps["output_token_cap"],
            "estimated_cost_usd": agent.estimate_cost_usd(tokens, tier_output_cap(tier)),
            "price_in": getattr(pricing, "input_per_million_usd", None),
            "price_out": getattr(pricing, "output_per_million_usd", None),
        })

        result = asyncio.run(agent.execute(AgentContext(run_id=uuid.uuid4().hex), payload))
        if result.status != "completed":
            send({"type": "result.blocked", "reason": str(result.payload.get("reason", "blocked"))})
            return

        mappings = dict(result.payload.get("mappings", {}))
        send({"type": "result", "mappings": mappings, "error": result.payload.get("error")})
        checks = check_mapping([c["name"] for c in columns], mappings, {c["name"]: c for c in profile["columns"]})
        pass_rate = pass_rate_from_checks(checks)
        send({"type": "checks", "checks": checks, "pass_rate": pass_rate})
        if pass_rate < 1 and not result.payload.get("error"):  # an unreadable answer is not a mapping to correct
            # Rule first: what a deterministic rule can fix costs nothing, so try it before any new model call.
            profile_by_name = {c["name"]: c for c in profile["columns"]}
            fixed, changes = correct_mapping(profile["columns"], mappings)
            if changes:
                fixed_checks = check_mapping([c["name"] for c in columns], fixed, profile_by_name)
                send({"type": "rule.corrected", "mappings": fixed, "changes": changes, "checks": fixed_checks,
                      "pass_rate": pass_rate_from_checks(fixed_checks), "pass_rate_before": pass_rate})

        totals = sink.totals_by_agent().get(agent.name, {"input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        policy = RefinementPolicy()
        branch = ArtifactBranch(artifact_id)
        branch.add(Attempt(tier, pass_rate, float(totals["cost"])))
        estimates = {t: agent.estimate_cost_usd(tokens, tier_output_cap(t)) for t in policy.tiers}
        decision = policy.decide(branch, estimates)
        send({"type": "policy", "action": decision.action.value, "tier": decision.tier, "reason": decision.reason})
        send({
            "type": "summary", "input_tokens": int(totals["input_tokens"]),
            "output_tokens": int(totals["output_tokens"]), "cost_usd": float(totals["cost"]),
        })
    except Exception as exc:  # the stream must always end with a readable reason
        send({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        send({"type": "done"})
