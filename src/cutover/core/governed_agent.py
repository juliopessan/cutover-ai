from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Mapping
from typing import Any

from cutover.core.agent import AgentContext, AgentResult, MigrationAgent
from cutover.governance.bridge import tier_for_score
from cutover.telemetry.events import CostEstimate, TelemetryEvent, TokenUsage
from cutover.telemetry.sink import NullTelemetrySink, TelemetrySink


class GovernedAgent(MigrationAgent):
    """Base class for agents whose LLM calls must pass the Tollgate gateway.

    Subclasses implement ``build_prompt`` and ``interpret``; this class handles scoring,
    admission, budgets, blocking and telemetry. A blocked call returns an
    ``AgentResult`` with status ``blocked`` and never reaches the provider.
    """

    provider: str = "deepseek"
    model: str = "deepseek-chat"

    def __init__(
        self,
        gateway: Any,
        *,
        provider: str | None = None,
        model: str | None = None,
        session_budget_usd: float | None = None,
        artifact_budget_usd: float | None = None,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.gateway = gateway
        self.provider = provider or self.provider
        self.model = model or self.model
        self.session_budget_usd = session_budget_usd
        self.artifact_budget_usd = artifact_budget_usd
        self.telemetry = telemetry or NullTelemetrySink()

    @abstractmethod
    def build_prompt(self, payload: Mapping[str, Any]) -> str: ...

    @abstractmethod
    def interpret(self, content: str) -> Mapping[str, Any]: ...

    def estimate_cost_usd(self, candidate_tokens: int) -> float:
        """Conservative pre-call estimate. Override with real pricing for tighter budgets."""
        return round(candidate_tokens / 1_000_000 * 1.0, 8)

    async def execute(self, context: AgentContext, payload: Mapping[str, Any]) -> AgentResult:
        from tollgate.context.tokens import estimate_tokens
        from tollgate.governance.runtime.guardian import CallEnvelope, GuardianBlocked

        score = payload.get("complexity_score")
        artifact_id = str(payload.get("artifact_id", ""))
        if score is None or not artifact_id:
            return AgentResult(
                status="blocked",
                payload={"reason": "complexity_score and artifact_id are required"},
            )
        prompt = self.build_prompt(payload)
        candidate_tokens = estimate_tokens(prompt)
        try:
            envelope = CallEnvelope(
                session_id=context.run_id,
                project_id=str(payload.get("project_id", self.name)),
                artifact_id=artifact_id,
                payload=prompt,
                candidate_tokens=candidate_tokens,
                complexity_score=float(score),
                tier=tier_for_score(float(score)),
                provider=self.provider,
                model=self.model,
                estimated_cost_usd=self.estimate_cost_usd(candidate_tokens),
                artifact_budget_usd=self.artifact_budget_usd,
                session_budget_usd=self.session_budget_usd,
            )
            response = await asyncio.to_thread(self.gateway.complete, envelope)
        except (GuardianBlocked, ValueError) as exc:
            self.telemetry.emit(
                TelemetryEvent(
                    name="llm.call.blocked",
                    run_id=context.run_id,
                    agent_name=self.name,
                    attributes={"reason": str(exc)},
                )
            )
            return AgentResult(status="blocked", payload={"reason": str(exc)})
        self.telemetry.emit(
            TelemetryEvent(
                name="llm.call.completed",
                run_id=context.run_id,
                agent_name=self.name,
                usage=TokenUsage(response.input_tokens, response.output_tokens),
                cost=CostEstimate("USD", response.cost_usd, 0.0),
                attributes={"model": self.model, "tier": envelope.tier},
            )
        )
        return AgentResult(status="completed", payload=self.interpret(response.content))
