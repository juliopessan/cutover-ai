import pytest

from cutover.governance import GovernanceSettings, build_gateway, tier_for_score

pytest.importorskip("tollgate")

from tollgate.governance.runtime.guardian import CallEnvelope, GuardianBlocked  # noqa: E402
from tollgate.governance.runtime.provider_gateway import ProviderResponse  # noqa: E402

from cutover.providers.deepseek import DeepSeekPricing, DeepSeekProvider  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, *, model, payload, **kwargs):
        self.calls.append((model, payload))
        return ProviderResponse(content="ok", input_tokens=50, output_tokens=10, cost_usd=0.001)


def envelope(payload, tier="daylight", score=20.0, **overrides):
    values = dict(
        session_id="s1",
        project_id="proj",
        artifact_id="a1",
        payload=payload,
        candidate_tokens=len(payload) // 4,
        complexity_score=score,
        tier=tier,
        provider="deepseek",
        model="deepseek-chat",
        estimated_cost_usd=0.001,
    )
    values.update(overrides)
    return CallEnvelope(**values)


def test_tier_for_score_maps_bounds_and_fails_closed():
    assert tier_for_score(0) == "solar"
    assert tier_for_score(20) == "daylight"
    assert tier_for_score(100) == "aurora"
    with pytest.raises(ValueError):
        tier_for_score(101)


def test_gateway_admits_call_and_records_ledger(tmp_path):
    client = FakeClient()
    gateway = build_gateway(GovernanceSettings(db_path=tmp_path / "ledger.db"), client)
    response = gateway.complete(envelope("map column A to B"))
    assert response.content == "ok"
    assert len(client.calls) == 1


def test_gateway_blocks_call_without_score_before_provider(tmp_path):
    client = FakeClient()
    gateway = build_gateway(GovernanceSettings(db_path=tmp_path / "ledger.db"), client)
    with pytest.raises(GuardianBlocked):
        gateway.complete(envelope("payload", score=None))
    assert client.calls == []


def test_gateway_blocks_when_session_budget_exceeded(tmp_path):
    client = FakeClient()
    gateway = build_gateway(GovernanceSettings(db_path=tmp_path / "ledger.db"), client)
    with pytest.raises(GuardianBlocked):
        gateway.complete(envelope("payload", session_budget_usd=0.0001))
    assert client.calls == []


def test_deepseek_provider_reconciles_measured_usage():
    class Usage:
        prompt_tokens = 1_000_000
        completion_tokens = 500_000

    class Message:
        content = "done"

    class Choice:
        message = Message()

    class Completion:
        usage = Usage()
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return Completion()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    provider = DeepSeekProvider(
        pricing=DeepSeekPricing(input_per_million_usd=1.0, output_per_million_usd=2.0),
        client=Client(),
    )
    result = provider.complete(model="deepseek-chat", payload="hi", instructions="be brief")
    assert result.content == "done"
    assert result.cost_usd == pytest.approx(2.0)
    assert Client.chat.completions.kwargs["messages"][0] == {"role": "system", "content": "be brief"}


def test_deepseek_pricing_from_env(monkeypatch):
    from cutover.providers.deepseek import DeepSeekProviderError

    monkeypatch.setenv("DEEPSEEK_PRICE_INPUT_PER_M", "0.04")
    monkeypatch.setenv("DEEPSEEK_PRICE_OUTPUT_PER_M", "0.08")
    pricing = DeepSeekPricing.from_env()
    assert pricing.calculate(1_000_000, 1_000_000) == pytest.approx(0.12)
    monkeypatch.delenv("DEEPSEEK_PRICE_OUTPUT_PER_M")
    with pytest.raises(DeepSeekProviderError):
        DeepSeekPricing.from_env()


def _chunk(reasoning=None, content=None, usage=None):
    from types import SimpleNamespace as NS

    choices = [NS(delta=NS(reasoning_content=reasoning, content=content))] if (reasoning or content) else []
    return NS(choices=choices, usage=usage)


def _streaming_client(chunks):
    from types import SimpleNamespace as NS

    class Completions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return iter(chunks)

    return NS(chat=NS(completions=Completions()))


def test_deepseek_streams_deltas_and_reports_measured_usage():
    from types import SimpleNamespace as NS

    chunks = [_chunk(reasoning="thinking "), _chunk(content='{"a":'), _chunk(content=" 1}"),
              _chunk(usage=NS(prompt_tokens=1_000_000, completion_tokens=500_000))]
    client = _streaming_client(chunks)
    provider = DeepSeekProvider(pricing=DeepSeekPricing(1.0, 2.0), client=client)
    seen = []
    result = provider.complete(model="m", payload="hi", on_delta=lambda kind, text: seen.append((kind, text)))
    assert result.content == '{"a": 1}' and result.cost_usd == pytest.approx(2.0)
    assert seen[0] == ("reasoning", "thinking ") and client.chat.completions.kwargs["stream"] is True


def test_deepseek_stream_without_usage_is_rejected():
    from cutover.providers.deepseek import DeepSeekProviderError

    provider = DeepSeekProvider(pricing=DeepSeekPricing(1.0, 2.0), client=_streaming_client([_chunk(content="x")]))
    with pytest.raises(DeepSeekProviderError):
        provider.complete(model="m", payload="hi", on_delta=lambda *_: None)


def test_gateway_forwards_stream_deltas_as_events(tmp_path):
    class Streaming:
        def complete(self, *, model, payload, on_delta=None, **kwargs):
            on_delta("reasoning", "hmm")
            on_delta("content", "ok")
            return ProviderResponse("ok", 10, 5, 0.0001)

    seen = []
    gateway = build_gateway(GovernanceSettings(db_path=tmp_path / "l.db"), Streaming(), on_event=seen.append)
    gateway.complete(envelope("payload"))
    deltas = [e for e in seen if e["type"] == "provider.delta"]
    assert {(d["kind"], d["text"]) for d in deltas} == {("reasoning", "hmm"), ("content", "ok")}
    assert seen[-1]["type"] in {"gate.audited", "provider.response"}
