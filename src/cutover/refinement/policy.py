from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .branch import ArtifactBranch


class Action(StrEnum):
    ACCEPT = "accept"
    REFINE = "refine"
    ESCALATE = "escalate"
    PARALLEL = "parallel"
    STOP_BUDGET = "stop_budget"
    STOP_STALLED = "stop_stalled"
    STOP_EXHAUSTED = "stop_exhausted"


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    tier: str | None
    candidates: int
    reason: str

    @property
    def stops(self) -> bool:
        return self.action in {Action.ACCEPT, Action.STOP_BUDGET, Action.STOP_STALLED, Action.STOP_EXHAUSTED}


@dataclass(frozen=True, slots=True)
class RefinementPolicy:
    """Deterministic, explainable policy trading quality against cost per artifact.

    Rules run in order and the first match wins. Every decision carries its reason so it can be
    audited. The defaults are starting points to calibrate against your own baseline, not results.
    """

    tiers: Sequence[str] = ("daylight", "horizon", "twilight", "starlight", "aurora")
    target_pass_rate: float = 0.95
    budget_usd: float = 50.0
    max_attempts: int = 4
    min_gain: float = 0.02
    parallel_width: int = 2
    parallel_below: float = 0.5

    def decide(self, branch: ArtifactBranch, cost_estimates: Mapping[str, float]) -> Decision:
        """Choose the next step. ``cost_estimates`` maps tier to the expected cost of one attempt."""
        if branch.attempts and branch.best_pass_rate >= self.target_pass_rate:
            return Decision(Action.ACCEPT, None, 0, f"pass rate {branch.best_pass_rate:.2f} meets target")
        if len(branch.attempts) >= self.max_attempts:
            return Decision(Action.STOP_EXHAUSTED, None, 0,
                            f"{self.max_attempts} attempts used; needs human review")

        remaining = self.budget_usd - branch.spent_usd
        current = branch.last_tier or self.tiers[0]
        gain = branch.last_gain()

        stalled = gain is not None and gain < self.min_gain
        tier = current
        action = Action.REFINE
        if not branch.attempts:
            reason = "first attempt"
        elif gain is None:
            reason = "one attempt so far; refining"
        else:
            reason = f"gain {gain:.2f} justifies another attempt"
        if stalled:
            higher = self.tiers[self.tiers.index(current) + 1:] if current in self.tiers else ()
            if not higher:
                return Decision(Action.STOP_STALLED, None, 0,
                                f"gain {gain:.2f} below {self.min_gain:.2f} and no higher tier")
            tier, action = higher[0], Action.ESCALATE
            reason = f"gain {gain:.2f} below {self.min_gain:.2f}; escalating"

        estimate = cost_estimates.get(tier)
        if estimate is None:
            raise KeyError(f"no cost estimate for tier {tier!r}")
        if estimate > remaining:
            return Decision(Action.STOP_BUDGET, None, 0,
                            f"next attempt ~${estimate:.2f} exceeds remaining ${remaining:.2f}")

        wide = (action is Action.REFINE and self.parallel_width > 1 and branch.attempts
                and branch.best_pass_rate < self.parallel_below
                and estimate * self.parallel_width <= remaining)
        if wide:
            return Decision(Action.PARALLEL, tier, self.parallel_width,
                            f"pass rate {branch.best_pass_rate:.2f} below {self.parallel_below:.2f}; "
                            f"sampling {self.parallel_width} candidates")
        return Decision(action, tier, 1, reason)
