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
                     "provider.response", "gate.audited", "result", "checks", "policy", "summary", "saved", "done"]
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


def run_once(client, location):
    evs = events(client.post(location + "/mapping/run"))
    return next(e["run_id"] for e in evs if e["type"] == "saved"), evs


def test_run_is_persisted_and_survives_reload(tmp_path):
    client, location = make(tmp_path, FakeProvider())
    run_id, _ = run_once(client, location)
    page = client.get(location + "/mapping").text
    assert "Execuções anteriores" in page and f'<td class="num">{run_id}</td>' in page


def test_approve_then_report_and_download(tmp_path):
    client, location = make(tmp_path, FakeProvider())
    run_id, _ = run_once(client, location)
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved", "note": "ok"}).json()["ok"]
    csv_text = client.get(f"{location}/mapping/runs/{run_id}/download")
    assert csv_text.headers["content-type"].startswith("text/csv")
    assert "unit price,unit_price,double,approved" in csv_text.text
    report = client.get(location + "/report").text
    assert "Relatório de assessment AS-IS" in report and "Aprovado" in report and "unit_price" in report
    assert "a@example.com" in report
    assert "Aprovado" in client.get("/app").text


def test_cannot_approve_when_checks_failed(tmp_path):
    client, location = make(tmp_path, FakeProvider('{"id": "same", "unit price": "same"}'))
    run_id, _ = run_once(client, location)
    response = client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"})
    assert response.status_code == 409 and not response.json()["ok"]
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "rejected"}).json()["ok"]
    assert "Rejeitado" in client.get(location + "/report").text


def test_failed_run_is_saved_but_cannot_be_decided(tmp_path):
    class Broken:
        def complete(self, **kwargs):
            raise RuntimeError("upstream 500")

    client, location = make(tmp_path, Broken())
    run_id, _ = run_once(client, location)
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"}).status_code == 409
    assert client.get(f"{location}/mapping/runs/{run_id}/download").status_code == 404
    assert "Falhou" in client.get(location + "/mapping").text


def test_report_without_a_run_and_ownership(tmp_path):
    client, location = make(tmp_path, FakeProvider())
    assert "Sem sugestão" in client.get(location + "/report").text
    run_id, _ = run_once(client, location)
    client.post("/logout")
    client.post("/signup", data={"email": "b@example.com", "password": "correct-horse-1"})
    assert client.get(location + "/report").status_code == 404
    assert client.get(f"{location}/mapping/runs/{run_id}/download").status_code == 404
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"}).status_code == 409


def test_report_includes_stats_audit_privacy_and_economy(tmp_path):
    client, location = make(tmp_path, FakeProvider())
    run_id, _ = run_once(client, location)
    client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"})
    report = client.get(location + "/report").text
    for expected in ("Indicadores de qualidade", "Payload enviado ao modelo", "Esforço e economia",
                     "Preço (US$ por milhão de tokens", "Tetos do nível", "Premissas não verificadas",
                     "Sensibilidade dos dados", "Medido nos dados", "type_fits_data"):
        assert expected in report, expected
    assert "Tratar os alertas e usar o mapeamento aprovado." in report.split("Handoff")[1]  # this CSV has an alert


def test_handoff_does_not_ask_to_treat_alerts_when_there_are_none(tmp_path):
    client = TestClient(create_app(tmp_path, provider_factory=lambda: FakeProvider('{"id": {"target": "id", "type": "int"}, "name": {"target": "name", "type": "string"}}'), pricing=PRICING), follow_redirects=False)
    client.post("/signup", data={"email": "a@example.com", "password": "correct-horse-1"})
    location = client.post("/app/datasets", files={"file": ("clean.csv", "id,name\n1,a\n2,b\n")}, data={"target": "databricks"}).headers["location"]
    run_id, _ = run_once(client, location)
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"}).json()["ok"]
    handoff = client.get(location + "/report").text.split("Handoff")[1]
    assert "Usar o mapeamento aprovado." in handoff and "Tratar os alertas" not in handoff


def test_report_reprofiles_datasets_stored_with_an_older_profile(tmp_path):
    import json
    import sqlite3

    client, location = make(tmp_path, FakeProvider())
    dataset_id = int(location.rsplit("/", 1)[1])
    db_path = tmp_path / "cutover.db"
    conn = sqlite3.connect(db_path)
    profile = json.loads(conn.execute("SELECT profile_json FROM datasets WHERE id = ?", (dataset_id,)).fetchone()[0])
    profile.pop("profile_version"), profile.pop("privacy_hints")
    for column in profile["columns"]:
        column.pop("distinct")
    conn.execute("UPDATE datasets SET profile_json = ? WHERE id = ?", (json.dumps(profile), dataset_id))
    conn.commit()
    conn.close()
    assert "Este perfil é de uma versão anterior" not in client.get(location + "/report").text
    stored = json.loads(sqlite3.connect(db_path).execute("SELECT profile_json FROM datasets").fetchone()[0])
    assert stored["profile_version"] == 2 and "distinct" in stored["columns"][0]
