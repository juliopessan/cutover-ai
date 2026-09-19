from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class CostEstimate:
    currency: str
    input_cost: float
    output_cost: float

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    name: str
    run_id: str
    agent_name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None
    usage: TokenUsage | None = None
    cost: CostEstimate | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
