import asyncio

import pytest

pytest.importorskip("tollgate")

from tollgate.governance.runtime.provider_gateway import ProviderResponse  # noqa: E402

from cutover.core.agent import AgentContext  # noqa: E402
from cutover.governance import GovernanceSettings, build_gateway  # noqa: E402
from cutover.plugins.mapping import MappingSuggestionAgent  # noqa: E402
from cutover.telemetry.sink import InMemoryTelemetrySink  # noqa: E402


class FakeClient:
    def __init__(self, content='{"cust_id": "customer_id"}'):
        self.content = content
        self.calls = 0

    def complete(self, *, model, payload, **kwargs):
        self.calls += 1
        return ProviderResponse(self.content, input_tokens=40, output_tokens=8, cost_usd=0.0005)


def make_agent(tmp_path, client, **kwargs):
    gateway = build_gateway(GovernanceSettings(db_path=tmp_path / "l.db"), client)
    sink = InMemoryTelemetrySink()
    return MappingSuggestionAgent(gateway, telemetry=sink, **kwargs), sink


PAYLOAD = {
    "artifact_id": "m1",
    "complexity_score": 20,
    "target": "databricks",
    "source_columns": ["cust_id"],
    "target_columns": ["customer_id"],
}


def run(agent, payload):
    return asyncio.run(agent.execute(AgentContext(run_id="r1"), payload))


def test_completed_call_requires_approval_and_emits_telemetry(tmp_path):
    client = FakeClient()
    agent, sink = make_agent(tmp_path, client)
    result = run(agent, PAYLOAD)
    assert result.status == "completed"
    assert result.payload["mappings"] == {"cust_id": "customer_id"}
    assert result.payload["requires_approval"] is True
    assert sink.totals_by_agent()["mapping_suggestion"]["output_tokens"] == 8


def test_missing_score_is_blocked_without_calling_provider(tmp_path):
    client = FakeClient()
    agent, _ = make_agent(tmp_path, client)
    result = run(agent, {k: v for k, v in PAYLOAD.items() if k != "complexity_score"})
    assert result.status == "blocked"
    assert client.calls == 0


def test_exhausted_budget_is_blocked_and_reported(tmp_path):
    client = FakeClient()
    agent, sink = make_agent(tmp_path, client, session_budget_usd=0.0)
    result = run(agent, PAYLOAD)
    assert result.status == "blocked"
    assert client.calls == 0
    assert sink.events()[-1].name == "llm.call.blocked"


def test_unparseable_model_output_is_not_trusted(tmp_path):
    agent, _ = make_agent(tmp_path, FakeClient(content="not json"))
    result = run(agent, PAYLOAD)
    assert result.payload["mappings"] == {}
