import pytest

from cutover.economics.budget import BudgetExceededError, BudgetPolicy
from cutover.optimization.headroom import HeadroomOptimizer, HeadroomUnavailableError
from cutover.telemetry.events import CostEstimate, TokenUsage
from cutover.telemetry.sink import InMemoryTelemetrySink


def count_tokens(messages):
    return sum(len(message.get("content", "").split()) for message in messages)


def test_headroom_applies_when_savings_clear_gate():
    optimizer = HeadroomOptimizer(
        token_counter=count_tokens,
        budget_policy=BudgetPolicy(min_compression_savings_ratio=0.25),
        compressor=lambda messages: [{"role": "user", "content": "small payload"}],
    )
    result = optimizer.optimize(
        [{"role": "user", "content": "one two three four five six seven eight"}]
    )
    assert result.applied is True
    assert result.tokens_saved == 6


def test_headroom_falls_back_when_savings_are_too_small():
    original = [{"role": "user", "content": "one two three four"}]
    optimizer = HeadroomOptimizer(
        token_counter=count_tokens,
        budget_policy=BudgetPolicy(min_compression_savings_ratio=0.50),
        compressor=lambda messages: [{"role": "user", "content": "one two three"}],
    )
    result = optimizer.optimize(original)
    assert result.applied is False
    assert result.messages == original


def test_headroom_missing_dependency_is_explicit():
    optimizer = HeadroomOptimizer(token_counter=count_tokens)
    with pytest.raises(HeadroomUnavailableError):
        optimizer.optimize([{"role": "user", "content": "safe original context"}])


def test_budget_can_fail_closed():
    policy = BudgetPolicy(max_input_tokens_per_call=100, max_cost_per_call=0.25)
    with pytest.raises(BudgetExceededError):
        policy.validate(
            TokenUsage(input_tokens=120),
            CostEstimate(currency="USD", input_cost=0.30, output_cost=0.0),
        )


def test_in_memory_telemetry_aggregates_usage_and_cost():
    from cutover.telemetry.events import TelemetryEvent

    sink = InMemoryTelemetrySink()
    sink.emit(
        TelemetryEvent(
            name="llm.call.completed",
            run_id="run-1",
            agent_name="onboarding",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            cost=CostEstimate(currency="USD", input_cost=0.01, output_cost=0.02),
        )
    )
    totals = sink.totals_by_agent()["onboarding"]
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 20
    assert totals["cost"] == pytest.approx(0.03)
