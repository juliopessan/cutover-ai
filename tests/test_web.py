import re

import pytest

pytest.importorskip("multipart")

from fastapi.testclient import TestClient  # noqa: E402

from cutover.web import create_app  # noqa: E402
from cutover.web.profiling import ProfileError, profile_csv  # noqa: E402

CSV = "id,name,amount\n1,Ana,10.5\n2,Bruno,\n2,Bruno,\n"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path), follow_redirects=False)


def signup(client, email="a@example.com", password="correct-horse-1"):
    return client.post("/signup", data={"email": email, "password": password})


def test_landing_is_public_and_reads_real_tiers(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "aurora" in page.text and "dispatch.yaml" in page.text


def test_app_requires_login(client):
    assert client.get("/app").headers["location"] == "/login"
    assert client.post("/app/datasets", files={"file": ("a.csv", CSV)}, data={"target": "databricks"}
                       ).headers["location"] == "/login"


def test_signup_login_logout_flow(client):
    assert signup(client).headers["location"] == "/app"
    assert client.get("/app").status_code == 200
    client.post("/logout")
    assert client.get("/app").headers["location"] == "/login"
    assert client.post("/login", data={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/login", data={"email": "a@example.com", "password": "correct-horse-1"}
                       ).headers["location"] == "/app"


def test_weak_password_and_duplicate_email_rejected(client):
    assert signup(client, password="short").status_code == 400
    assert signup(client).status_code == 303
    assert signup(client).status_code == 409


def test_login_locks_out_after_repeated_failures(client):
    signup(client)
    client.post("/logout")
    for _ in range(5):
        client.post("/login", data={"email": "a@example.com", "password": "nope-nope-nope"})
    assert client.post("/login", data={"email": "a@example.com", "password": "correct-horse-1"}).status_code == 429


def test_cross_origin_post_is_rejected(client):
    response = client.post("/login", data={"email": "a@b.co", "password": "x"}, headers={"origin": "https://evil.test"})
    assert response.status_code == 403


def test_upload_profiles_dataset_with_measured_figures(client):
    signup(client)
    response = client.post("/app/datasets", files={"file": ("sales.csv", CSV)}, data={"target": "databricks"})
    location = response.headers["location"]
    assert re.fullmatch(r"/app/datasets/\d+", location)
    page = client.get(location).text
    assert "sales.csv" in page and "duplicadas" in page
    assert re.search(r"[0-9a-f]{64}", page)


def test_datasets_are_private_to_their_owner(client):
    signup(client)
    location = client.post("/app/datasets", files={"file": ("a.csv", CSV)}, data={"target": "databricks"}
                           ).headers["location"]
    client.post("/logout")
    signup(client, email="other@example.com")
    assert client.get(location).status_code == 404


def test_upload_rejects_non_csv_and_bad_target(client):
    signup(client)
    assert client.post("/app/datasets", files={"file": ("a.txt", CSV)}, data={"target": "databricks"}).status_code == 400
    assert client.post("/app/datasets", files={"file": ("a.csv", CSV)}, data={"target": "oracle"}).status_code == 400


def test_filename_is_escaped_in_pages(client):
    signup(client)
    location = client.post("/app/datasets", files={"file": ("<script>x.csv", CSV)}, data={"target": "databricks"}
                           ).headers["location"]
    assert "<script>x" not in client.get(location).text


def test_profile_flags_name_specific_problems(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("id,unit price,ID,notes\n1,5,a,\n1,5,a,\n2,x,b,\n3\n", encoding="utf-8")
    profile = profile_csv(path)
    kinds = {f.kind: f for f in profile.flags}
    assert "'unit price'" in kinds["column_names"].items
    assert kinds["duplicate_columns"].items == ["id, ID"]
    assert kinds["malformed_rows"].items == ["linha 5"]
    assert kinds["duplicate_rows"].items
    assert profile.rows == 3 and profile.duplicate_rows == 1


def test_clean_profile_renders_no_flags(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("id,name\n1,a\n2,b\n", encoding="utf-8")
    assert profile_csv(path).flags == []


def test_profile_rejects_empty_and_non_utf8(tmp_path):
    path = tmp_path / "d.csv"
    path.write_bytes(b"   ")
    with pytest.raises(ProfileError):
        profile_csv(path)
    path.write_bytes("id,nome\n1,João\n".encode("latin-1"))
    with pytest.raises(ProfileError):
        profile_csv(path)


def test_landing_shows_proof_only_when_measurements_exist(tmp_path, monkeypatch):
    import json

    from cutover.web import app as app_module

    bench = tmp_path / "profile.json"
    bench.write_text(json.dumps({
        "generated_at": "2026-01-01 00:00 UTC", "git_commit": "abc1234",
        "environment": {"platform": "Test x", "python": "3.12"},
        "method": {"profile_runs_per_file": 2, "upload_runs_per_file": 1},
        "datasets": [{"file": "a.csv", "rows": 1234, "columns": 3, "profile_ms_median": 1.5,
                      "upload_to_page_ms_median": 9.0}],
        "totals": {"files": 1, "rows": 1234, "sha256_confirmed_on_page": "1/1", "false_alarms_on_clean_files": 0},
        "detection": {"defects_injected": 6, "defects_detected": 6},
    }))
    monkeypatch.setattr(app_module, "BENCHMARK", bench)
    page = TestClient(create_app(tmp_path / "d")).get("/").text
    assert "1.234" in page and "6/6" in page and "abc1234" in page

    bench.unlink()
    assert 'id="prova"' not in TestClient(create_app(tmp_path / "d2")).get("/").text


def test_favicon_is_served_for_every_page(client):
    ico = client.get("/favicon.ico")
    assert ico.status_code == 200 and ico.content[:4] == b"\x00\x00\x01\x00"
    for url in ("/", "/login", "/signup"):
        page = client.get(url).text
        assert 'href="/static/favicon.svg"' in page and 'rel="apple-touch-icon"' in page
    assert client.get("/static/site.webmanifest").status_code == 200


def test_roi_model_matches_hand_calculation():
    from cutover.web.report import ASSUMPTIONS, roi

    a = {k: v["value"] for k, v in ASSUMPTIONS.items()}
    out = roi(a, ai_cost_per_dataset_usd=0.0)
    assert out["manual_cost"] == 6000 and out["assisted_cost"] == 800 and out["saving"] == 5200
    assert out["hours_saved"] == 87.5 and out["roi_year_one"] == pytest.approx((5200 * 4 - 2400) / 2400)
    worse = roi({**a, "review_hours": 2.0}, 0.0)  # review as slow as doing it by hand: no saving, no payback
    assert worse["saving"] < 0 and worse["payback_assessments"] == float("inf")


def test_report_page_separates_measured_from_assumed(client):
    page = client.get("/relatorio")
    assert page.status_code == 200
    assert "Premissas não verificadas" in page.text and "Decisão pedida ao patrocinador" in page.text
    assert page.text.count("Handoff") == 7 and "Estimativa não verificada" in page.text
    assert 'src="/static/report.js"' in page.text


def test_profile_measures_ranges_keys_decimal_shape_and_privacy_hints(tmp_path):
    from cutover.web.profiling import privacy_hints

    path = tmp_path / "d.csv"
    path.write_text("order_id,customer_name,total,day,notes\n1,Ana,10.50,2025-01-03,abc\n2,Bruno,1234.5,2025-03-09,\n3,Ana,7.125,2025-02-01,x\n",
                    encoding="utf-8")
    cols = {c["name"]: c for c in profile_csv(path).columns}
    assert cols["order_id"]["is_key_candidate"] and cols["order_id"]["min"] == "1" and cols["order_id"]["max"] == "3"
    assert cols["customer_name"]["distinct"] == 2 and not cols["customer_name"]["is_key_candidate"]
    assert cols["total"]["max_scale"] == 3 and cols["total"]["max_int_digits"] == 4 and cols["total"]["max"] == "1234.5"
    assert cols["day"]["min"] == "2025-01-03" and cols["day"]["max"] == "2025-03-09"
    assert cols["notes"]["max_len"] == 3
    assert [h["column"] for h in privacy_hints(["cpf_cliente", "valor", "E-mail", "Telefone Celular", "quantidade"])] == [
        "cpf_cliente", "E-mail", "Telefone Celular"]


def test_type_fits_data_catches_unsafe_types_only_when_profile_is_given():
    from cutover.plugins.mapping import check_mapping, type_conflict

    profile = {"id": {"type": "integer", "min": "1", "max": "5000000000"}, "price": {"type": "decimal", "min": "1", "max": "9"},
               "city": {"type": "text"}, "d": {"type": "text"}}
    mappings = {"id": {"target": "id", "type": "int"}, "price": {"target": "price", "type": "int"},
                "city": {"target": "city", "type": "int"}, "d": {"target": "d", "type": "date"}}
    assert len(check_mapping(list(mappings), mappings)) == 5  # legacy call keeps the five checks
    fit = {c["name"]: c for c in check_mapping(list(mappings), mappings, profile)}["type_fits_data"]
    assert fit["status"] == "failed" and len(fit["offenders"]) == 3  # id overflows, price loses decimals, city is text
    assert type_conflict(profile["d"], "date") is None  # text to date is allowed (needs a source format, not unsafe)
    assert type_conflict(profile["id"], "bigint") is None


def test_db_migration_adds_missing_audit_columns(tmp_path):
    import sqlite3

    from cutover.web.db import Database

    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE mapping_runs(id INTEGER PRIMARY KEY, dataset_id INTEGER, user_id INTEGER, status TEXT)")
    conn.commit()
    conn.close()
    Database(old)
    cols = {r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(mapping_runs)")}
    assert {"prompt", "price_in", "price_out", "input_cap", "output_cap", "estimated_cost_usd"} <= cols


def test_identical_columns_are_flagged_by_content_not_by_name(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("a,b,c,e1,e2\n1,1,x,,\n2,2,y,,\n3,3,x,,\n", encoding="utf-8")
    kinds = {f.kind: f for f in profile_csv(path).flags}
    assert kinds["identical_columns"].items == ["a = b"]  # c differs; all-empty e1/e2 are not reported as twins
