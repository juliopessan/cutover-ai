from __future__ import annotations

from dataclasses import dataclass

from cutover.telemetry.events import CostEstimate, TokenUsage


class BudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    max_input_tokens_per_call: int = 32_000
    max_output_tokens_per_call: int = 8_000
    max_cost_per_call: float = 1.0
    min_compression_savings_ratio: float = 0.10
    fail_closed: bool = True

    def validate(self, usage: TokenUsage, cost: CostEstimate | None = None) -> None:
        violations: list[str] = []
        if usage.input_tokens > self.max_input_tokens_per_call:
            violations.append("input token budget exceeded")
        if usage.output_tokens > self.max_output_tokens_per_call:
            violations.append("output token budget exceeded")
        if cost and cost.total_cost > self.max_cost_per_call:
            violations.append("cost budget exceeded")
        if violations and self.fail_closed:
            raise BudgetExceededError("; ".join(violations))

    def compression_is_economic(self, before: int, after: int) -> bool:
        if before <= 0 or after < 0 or after > before:
            return False
        savings_ratio = (before - after) / before
        return savings_ratio >= self.min_compression_savings_ratio
