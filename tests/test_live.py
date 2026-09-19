import json

import pytest

pytest.importorskip("multipart")
pytest.importorskip("tollgate")

from fastapi.testclient import TestClient  # noqa: E402
from tollgate.governance.runtime.provider_gateway import ProviderResponse  # noqa: E402

from cutover.plugins.mapping import check_mapping, extract_json  # noqa: E402
from cutover.providers.deepseek import DeepSeekPricing  # noqa: E402
from cutover.web import create_app  # noqa: E402

CSV = "id,unit price,amount\n1,5,10.5\n2,6,11\n"
GOOD = '```json\n{"id": {"target": "id", "type": "int"}, "unit price": {"target": "unit_price", "type": "double"}, "amount": {"target": "amount", "type": "double"}}\n```'
PRICING = DeepSeekPricing(input_per_million_usd=0.04, output_per_million_usd=0.08)


class FakeProvider:
    def __init__(self, content=GOOD):
        self.content, self.calls = content, []

    def complete(self, *, model, payload, **kwargs):
        self.calls.append((model, payload, kwargs))
        return ProviderResponse(self.content, input_tokens=120, output_tokens=60, cost_usd=PRICING.calculate(120, 60))


def make(tmp_path, provider):
    client = TestClient(create_app(tmp_path, provider_factory=lambda: provider, pricing=PRICING), follow_redirects=False)
    client.post("/signup", data={"email": "a@example.com", "password": "correct-horse-1"})
    location = client.post("/app/datasets", files={"file": ("d.csv", CSV)}, data={"target": "databricks"}).headers["location"]
    return client, location


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_live_run_streams_every_gate_step_in_order(tmp_path):
    provider = FakeProvider()
    client, location = make(tmp_path, provider)
    types = [e["type"] for e in events(client.post(location + "/mapping/run"))]
    assert types == ["run.start", "payload.built", "gate.scored", "gate.admitted", "provider.call",
                     "provider.response", "gate.audited", "result", "checks", "policy", "summary", "done"]
    model, payload, kwargs = provider.calls[0]
    assert "unit price" in payload and "10.5" not in payload  # names and types only, never row values
    assert kwargs["max_tokens"] > 0


def test_live_run_reports_measured_cost_and_checks(tmp_path):
    client, location = make(tmp_path, FakeProvider())
    by_type = {e["type"]: e for e in events(client.post(location + "/mapping/run"))}
    assert by_type["summary"]["cost_usd"] == pytest.approx(PRICING.calculate(120, 60))
    assert by_type["checks"]["pass_rate"] == 1.0
    assert by_type["policy"]["action"] == "accept"


def test_bad_model_output_fails_checks_and_is_never_accepted(tmp_path):
    bad = '{"id": "same", "unit price": "same"}'
    client, location = make(tmp_path, FakeProvider(bad))
    by_type = {e["type"]: e for e in events(client.post(location + "/mapping/run"))}
    assert by_type["checks"]["pass_rate"] < 1.0
    assert by_type["policy"]["action"] != "accept"


def test_provider_failure_surfaces_as_an_error_event(tmp_path):
    class Broken:
        def complete(self, **kwargs):
            raise RuntimeError("upstream 500")

    client, location = make(tmp_path, Broken())
    evs = events(client.post(location + "/mapping/run"))
    assert any(e["type"] == "provider.error" for e in evs)
    assert evs[-1]["type"] == "done"


def test_daily_run_limit_and_ownership(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTOVER_LIVE_MAX_RUNS_PER_DAY", "1")
    client, location = make(tmp_path, FakeProvider())
    assert client.post(location + "/mapping/run").status_code == 200
    assert client.post(location + "/mapping/run").status_code == 429
    client.post("/logout")
    client.post("/signup", data={"email": "b@example.com", "password": "correct-horse-1"})
    assert client.post(location + "/mapping/run").status_code == 404
    assert client.get(location + "/mapping").status_code == 404


def test_run_requires_login_and_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path), follow_redirects=False)
    assert client.post("/app/datasets/1/mapping/run").headers["location"] == "/login"
    client.post("/signup", data={"email": "a@example.com", "password": "correct-horse-1"})
    location = client.post("/app/datasets", files={"file": ("d.csv", CSV)}, data={"target": "databricks"}).headers["location"]
    assert client.post(location + "/mapping/run").status_code == 503
    assert "Chave ausente" in client.get(location + "/mapping").text


def test_extract_json_and_checks():
    assert extract_json('noise ```json\n{"a": 1}\n``` tail') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")
    checks = {c["name"]: c for c in check_mapping(["a", "b"], {"a": {"target": "X y", "type": "text"}, "z": "q"})}
    assert checks["covers_all_columns"]["offenders"] == ["b"]
    assert checks["no_unknown_columns"]["offenders"] == ["z"]
    assert checks["delta_safe_names"]["status"] == "failed" and checks["valid_types"]["status"] == "failed"
