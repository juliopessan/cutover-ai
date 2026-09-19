from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Attempt:
    """One refinement step. ``pass_rate`` must come from deterministic checks, never from a model."""

    tier: str
    pass_rate: float
    cost_usd: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.pass_rate <= 1.0:
            raise ValueError("pass_rate must be within [0, 1]")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")


@dataclass(slots=True)
class ArtifactBranch:
    """A branch of refinements for one artifact, scored by pass rate and priced in USD."""

    artifact_id: str
    attempts: list[Attempt] = field(default_factory=list)

    def add(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    @property
    def spent_usd(self) -> float:
        return sum(a.cost_usd for a in self.attempts)

    @property
    def best_pass_rate(self) -> float:
        return max((a.pass_rate for a in self.attempts), default=0.0)

    @property
    def last_tier(self) -> str | None:
        return self.attempts[-1].tier if self.attempts else None

    def last_gain(self) -> float | None:
        """Improvement of the last attempt over the best earlier one, or None with fewer than two."""
        if len(self.attempts) < 2:
            return None
        earlier_best = max(a.pass_rate for a in self.attempts[:-1])
        return self.attempts[-1].pass_rate - earlier_best


def pass_rate_from_checks(checks: Sequence[dict[str, Any]]) -> float:
    """Pass rate over deterministic checks (``status == "passed"``).

    No checks means no evidence, so the rate is 0.0: an artifact cannot be accepted on silence.
    """
    if not checks:
        return 0.0
    return sum(1 for c in checks if c.get("status") == "passed") / len(checks)
