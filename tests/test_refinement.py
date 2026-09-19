import pytest

from cutover.refinement import Action, ArtifactBranch, Attempt, RefinementPolicy, pass_rate_from_checks

COSTS = {"daylight": 1.0, "horizon": 3.0, "twilight": 8.0, "starlight": 20.0, "aurora": 40.0}


def branch(*attempts):
    b = ArtifactBranch("a1")
    for tier, rate, cost in attempts:
        b.add(Attempt(tier, rate, cost))
    return b


def test_first_attempt_starts_at_cheapest_tier():
    decision = RefinementPolicy().decide(branch(), COSTS)
    assert (decision.action, decision.tier) == (Action.REFINE, "daylight")


def test_accepts_when_target_met_and_never_on_no_attempts():
    policy = RefinementPolicy(target_pass_rate=0.9)
    assert policy.decide(branch(("daylight", 0.95, 1.0)), COSTS).action is Action.ACCEPT
    assert policy.decide(branch(), COSTS).action is not Action.ACCEPT


def test_refines_same_tier_while_gaining():
    decision = RefinementPolicy().decide(branch(("daylight", 0.6, 1), ("daylight", 0.8, 1)), COSTS)
    assert (decision.action, decision.tier) == (Action.REFINE, "daylight")


def test_escalates_on_stall():
    decision = RefinementPolicy().decide(branch(("daylight", 0.7, 1), ("daylight", 0.71, 1)), COSTS)
    assert (decision.action, decision.tier) == (Action.ESCALATE, "horizon")


def test_regression_counts_as_stall():
    decision = RefinementPolicy().decide(branch(("daylight", 0.7, 1), ("daylight", 0.6, 1)), COSTS)
    assert decision.action is Action.ESCALATE


def test_stops_stalled_at_top_tier():
    policy = RefinementPolicy(tiers=("daylight",))
    decision = policy.decide(branch(("daylight", 0.7, 1), ("daylight", 0.7, 1)), COSTS)
    assert decision.action is Action.STOP_STALLED


def test_budget_is_a_hard_stop_including_escalation_cost():
    policy = RefinementPolicy(budget_usd=10.0)
    decision = policy.decide(branch(("daylight", 0.7, 4), ("daylight", 0.7, 4)), COSTS)
    assert decision.action is Action.STOP_BUDGET  # escalating to horizon (~$3) exceeds remaining $2


def test_exhausted_attempts_need_human_review():
    policy = RefinementPolicy(max_attempts=2)
    assert policy.decide(branch(("daylight", 0.6, 1), ("daylight", 0.8, 1)), COSTS).action is Action.STOP_EXHAUSTED


def test_parallel_only_when_low_and_budget_covers_all_candidates():
    policy = RefinementPolicy()
    low = branch(("daylight", 0.2, 1))
    decision = policy.decide(low, COSTS)
    assert (decision.action, decision.candidates) == (Action.PARALLEL, 2)
    tight = RefinementPolicy(budget_usd=2.5)
    assert tight.decide(low, COSTS).action is Action.REFINE


def test_missing_cost_estimate_fails_loudly():
    with pytest.raises(KeyError):
        RefinementPolicy().decide(branch(), {})


def test_pass_rate_from_checks_fails_closed_without_evidence():
    assert pass_rate_from_checks([]) == 0.0
    checks = [{"status": "passed"}, {"status": "failed"}, {"status": "passed"}, {"status": "passed"}]
    assert pass_rate_from_checks(checks) == 0.75


def test_attempt_validates_ranges():
    with pytest.raises(ValueError):
        Attempt("daylight", 1.5, 1.0)
