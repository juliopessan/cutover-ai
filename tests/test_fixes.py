import io
import json
import sqlite3
import sys
import types
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("multipart")
pytest.importorskip("tollgate")

from fastapi.testclient import TestClient  # noqa: E402
from tollgate.governance.runtime.provider_gateway import ProviderResponse  # noqa: E402

from cutover.plugins.mapping import check_mapping, correct_mapping, infer_type, safe_type, snake_case  # noqa: E402
from cutover.providers.deepseek import DeepSeekPricing  # noqa: E402
from cutover.web import create_app  # noqa: E402
from cutover.web.profiling import profile_csv  # noqa: E402
from cutover.web.runs import csv_safe, mapping_csv  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "cloudera_covid"
PRICING = DeepSeekPricing(0.04, 0.08)
BIG = "id,population,label\n1,7761620146,a\n2,10,b\n3,20,c\n"
INT_ANSWER = '{"id": {"target": "id", "type": "int"}, "population": {"target": "population", "type": "int"}, "label": {"target": "label", "type": "string"}}'


class Fake:
    def __init__(self, content=INT_ANSWER):
        self.content = content

    def complete(self, *, model, payload, **kwargs):
        return ProviderResponse(self.content, 100, 50, 0.0001)


def boot(tmp_path, content=INT_ANSWER, csv_text=BIG):
    client = TestClient(create_app(tmp_path, provider_factory=lambda: Fake(content), pricing=PRICING), follow_redirects=False)
    client.post("/signup", data={"email": "a@example.com", "password": "correct-horse-1"})
    location = client.post("/app/datasets", files={"file": ("p.csv", csv_text)}, data={"target": "databricks"}).headers["location"]
    events = [json.loads(x) for x in client.post(location + "/mapping/run").text.splitlines() if x]
    return client, location, next(e["run_id"] for e in events if e["type"] == "saved")


def cols(name):
    return profile_csv(FIXTURES / name).to_dict()["columns"]


# ---- the rules ---------------------------------------------------------------------------------

def test_snake_case_and_type_inference():
    assert snake_case("Valor Total (R$)") == "valor_total_r" and snake_case("Data do Pedido") == "data_do_pedido"
    assert snake_case("São Paulo") == "sao_paulo" and snake_case("2024 vendas") == "c_2024_vendas" and snake_case("***") == "coluna"
    assert infer_type({"type": "integer", "min": "1", "max": "9"}) == "int"
    assert infer_type({"type": "integer", "min": "1", "max": "5000000000"}) == "bigint"
    assert infer_type({"type": "mixed"}) == "string" and infer_type({"type": "date"}) == "date"
    assert safe_type({"type": "decimal"}, "int") == "decimal" and safe_type({"type": "text"}, "int") == "string"


def test_correct_mapping_fixes_the_population_case_and_says_why():
    columns = cols("ref__populations.csv")
    model = {"country_code": {"target": "country_code", "type": "string"}, "population": {"target": "population", "type": "int"}}
    fixed, changes = correct_mapping(columns, model)
    assert fixed["population"]["type"] == "bigint" and len(changes) == 1
    assert changes[0]["field"] == "tipo" and "7761620146" in changes[0]["reason"]
    assert correct_mapping(columns, fixed)[1] == []  # idempotent: a corrected mapping needs no more fixes


def test_correct_mapping_handles_names_duplicates_gaps_and_ghosts():
    columns = [{"name": "Valor Total (R$)", "type": "decimal", "min": "1", "max": "9", "max_scale": 2, "max_int_digits": 1},
               {"name": "TOTAL_BRL", "type": "decimal"}, {"name": "extra", "type": "text"}]
    model = {"Valor Total (R$)": {"target": "Valor Total", "type": "decimal"}, "TOTAL_BRL": {"target": "valor_total", "type": "money"},
             "fantasma": {"target": "x", "type": "string"}}
    fixed, changes = correct_mapping(columns, model)
    targets = [v["target"] for v in fixed.values()]
    assert len(set(targets)) == 3 and all(t == t.lower() for t in targets)
    assert fixed["extra"] == {"target": "extra", "type": "string"} and "fantasma" not in fixed
    assert {c["field"] for c in changes} >= {"destino", "tipo", "coluna"}
    names = [c["name"] for c in columns]
    assert all(c["status"] == "passed" for c in check_mapping(names, fixed, {c["name"]: c for c in columns}))


@pytest.mark.parametrize("name", ["ref__populations.csv", "ref__country_codes.csv", "raw_covid__cases.csv"])
def test_a_corrected_mapping_always_passes_every_check(name):
    columns = cols(name)
    worst = {c["name"]: {"target": "Bad Name", "type": "int"} for c in columns}  # everything wrong at once
    fixed, _ = correct_mapping(columns, worst)
    checks = check_mapping([c["name"] for c in columns], fixed, {c["name"]: c for c in columns})
    assert [c["name"] for c in checks if c["status"] == "failed"] == []


# ---- the workflow ------------------------------------------------------------------------------

def test_blocked_suggestion_is_fixed_reapproved_and_generates_bigint(tmp_path):
    client, location, run_id = boot(tmp_path)
    base = f"{location}/mapping/runs/{run_id}"
    assert client.post(base + "/decision", data={"decision": "approved"}).status_code == 409  # gate blocks INT

    preview = client.get(base + "/fixes").json()
    assert preview["ok"] and preview["changes"][0]["to"] == "bigint"

    fixed = client.post(base + "/fix", json={"mode": "auto"}).json()
    assert fixed["ok"] and fixed["pass_rate"] == 1.0 and fixed["decision"] == "pending"
    assert client.post(base + "/fix", json={"mode": "auto"}).status_code == 409  # nothing left to fix
    assert client.post(base + "/decision", data={"decision": "approved"}).json()["ok"]

    files = zipfile.ZipFile(io.BytesIO(client.get(location + "/migration/download?target=databricks").content))
    assert "`population` BIGINT" in files.read("01_ddl.sql").decode()
    manifest = json.loads(files.read("manifest.json"))
    assert manifest["mapeamento_editado"] is True and manifest["edicoes"] == 1 and len(manifest["mapeamento_sha256"]) == 64


def test_editing_an_approved_mapping_cancels_the_approval_and_keeps_the_original(tmp_path):
    good = INT_ANSWER.replace('"population", "type": "int"', '"population", "type": "bigint"')
    client, location, run_id = boot(tmp_path, content=good)
    base = f"{location}/mapping/runs/{run_id}"
    assert client.post(base + "/decision", data={"decision": "approved"}).json()["ok"]
    entries = {"label": {"target": "rotulo", "type": "string"}}
    assert client.post(base + "/fix", json={"mode": "manual", "entries": entries}).json()["decision"] == "pending"

    row = sqlite3.connect(tmp_path / "cutover.db").execute(
        "SELECT decision, decided_by, edited, original_mappings_json, edit_log_json, mappings_json FROM mapping_runs WHERE id = ?", (run_id,)).fetchone()
    assert row[0] == "pending" and row[1] is None and row[2] == 1  # approval revoked
    assert json.loads(row[3])["label"]["target"] == "label" and json.loads(row[5])["label"]["target"] == "rotulo"
    log = json.loads(row[4])
    assert log[0]["by"] == "a@example.com" and log[0]["reset_decision"] is True and log[0]["changes"][0]["reason"] == "Edição manual."
    assert client.get(location + "/migration/download").status_code == 409  # code needs a fresh approval


def test_manual_edit_is_validated_and_a_bad_edit_cannot_be_approved(tmp_path):
    client, location, run_id = boot(tmp_path)
    base = f"{location}/mapping/runs/{run_id}"
    assert client.post(base + "/fix", json={"mode": "manual", "entries": {"nope": {"target": "x", "type": "string"}}}).status_code == 400
    assert client.post(base + "/fix", json={"mode": "manual", "entries": {}}).status_code == 409
    assert client.post(base + "/fix", json={"mode": "wat"}).status_code == 400
    bad = client.post(base + "/fix", json={"mode": "manual", "entries": {"id": {"target": "Bad Name", "type": "money"}}}).json()
    assert bad["ok"] and bad["pass_rate"] < 1
    assert client.post(base + "/decision", data={"decision": "approved"}).status_code == 409


def test_corrections_are_private_and_the_edit_page_renders(tmp_path):
    client, location, run_id = boot(tmp_path)
    base = f"{location}/mapping/runs/{run_id}"
    page = client.get(base + "/edit").text
    assert "Corrigir o mapeamento" in page and "Aplicar correções sugeridas por regra" in page and 'class="f-type"' in page
    assert page.count("<h1") == 1 and "type_fits_data" in page
    client.post(base + "/fix", json={"mode": "auto"})
    assert "Histórico de edições" in client.get(base + "/edit").text and "editada" in client.get(location + "/mapping").text
    client.post("/logout")
    assert client.post(base + "/fix", json={"mode": "auto"}).status_code == 401
    client.post("/signup", data={"email": "b@example.com", "password": "correct-horse-1"})
    assert client.post(base + "/fix", json={"mode": "auto"}).status_code == 404
    assert client.get(base + "/fixes").status_code == 404 and client.get(base + "/edit").status_code == 404


def test_report_discloses_that_the_mapping_was_corrected(tmp_path):
    client, location, run_id = boot(tmp_path)
    base = f"{location}/mapping/runs/{run_id}"
    client.post(base + "/fix", json={"mode": "auto"})
    client.post(base + "/decision", data={"decision": "approved"})
    report = client.get(location + "/report").text
    assert "Correções sobre a sugestão do modelo" in report and "corrigida" in report and "regras determinísticas" in report


# ---- hardening found on the way ----------------------------------------------------------------

def test_csv_cells_that_look_like_formulas_are_neutralized():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("@SUM(A1)") == "'@SUM(A1)" and csv_safe("-2+3") == "'-2+3"
    assert csv_safe("normal") == "normal" and csv_safe(None) == ""
    out = mapping_csv({"decision": "approved", "mappings": {'=HYPERLINK("http://x","a")': {"target": "col_a", "type": "string"}}})
    assert out.splitlines()[1].startswith("\"'=HYPERLINK(")


def test_provider_call_has_a_bounded_timeout_and_one_retry(monkeypatch):
    seen = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    from cutover.providers.deepseek import DeepSeekProvider

    DeepSeekProvider(pricing=PRICING)
    assert seen["timeout"] == 90.0 and seen["max_retries"] == 1
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_S", "20")
    DeepSeekProvider(pricing=PRICING)
    assert seen["timeout"] == 20.0
    DeepSeekProvider(pricing=PRICING, timeout_s=5)
    assert seen["timeout"] == 5
