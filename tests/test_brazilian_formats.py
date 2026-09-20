"""Brazilian file conventions: Windows-1252, dd/mm/yyyy dates and 1.234,56 numbers."""

import ast
import csv
import json
import re
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import sqlglot

pytest.importorskip("multipart")
pytest.importorskip("tollgate")

from fastapi.testclient import TestClient  # noqa: E402
from tollgate.governance.runtime.provider_gateway import ProviderResponse  # noqa: E402

from cutover.codegen import build_bundle, default_params  # noqa: E402
from cutover.plugins.mapping import correct_mapping, infer_type, safe_type, type_conflict  # noqa: E402
from cutover.providers.deepseek import DeepSeekPricing  # noqa: E402
from cutover.web import create_app  # noqa: E402
from cutover.web.profiling import profile_csv  # noqa: E402

BR = "pedido;data;valor;cliente\n1;01/02/2026;1.234,56;João\n2;15/03/2026;99,90;São José\n3;31/12/2025;5,5;Ana\n"


def profile(tmp_path: Path, text: str, encoding: str = "utf-8", name: str = "d.csv"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return profile_csv(path)


def column(p, name):
    return next(c for c in p.columns if c["name"] == name)


# ---- the case that started this ---------------------------------------------------------------

def test_a_brazilian_export_is_typed_instead_of_read_as_text(tmp_path):
    p = profile(tmp_path, BR)
    data, valor = column(p, "data"), column(p, "valor")
    assert (data["type"], data["date_format"], data["date_ambiguous"]) == ("date", "dd/MM/yyyy", False)
    assert (data["min"], data["max"]) == ("2025-12-31", "2026-03-15")  # ordered as dates, not as text
    assert (valor["type"], valor["number_style"], valor["min"], valor["max"]) == ("decimal", "br", "5.5", "1234.56")
    assert (valor["max_scale"], valor["max_int_digits"]) == (2, 4) and p.delimiter == ";" and p.flags == []
    assert column(p, "cliente")["type"] == "text"


# ---- encoding ----------------------------------------------------------------------------------

def test_windows_1252_is_detected_and_flagged_and_accents_survive(tmp_path):
    p = profile(tmp_path, "nome;cidade\nJoão;São Paulo\n", "windows-1252")
    assert p.encoding == "windows-1252" and [f.kind for f in p.flags] == ["encoding"]
    assert column(p, "cidade")["max_len"] == len("São Paulo")  # decoded as characters, not mojibake


def test_utf8_with_bom_is_plain_utf8_and_latin1_is_the_last_resort(tmp_path):
    assert profile(tmp_path, "a;b\n1;ã\n", "utf-8-sig").encoding == "utf-8"
    path = tmp_path / "raw.csv"
    path.write_bytes(b"a;b\n1;\x81\n")  # 0x81 is undefined in cp1252
    assert profile_csv(path).encoding == "latin-1"


# ---- dates -------------------------------------------------------------------------------------

def test_all_values_valid_both_ways_is_reported_as_ambiguous_not_guessed_silently(tmp_path):
    p = profile(tmp_path, "d\n01/02/2026\n03/04/2026\n05/06/2026\n")
    c = column(p, "d")
    assert c["date_ambiguous"] and c["date_format"] == "dd/MM/yyyy"  # Brazilian default, but disclosed
    assert [f.kind for f in p.flags] == ["ambiguous_dates"] and "dia e mês" in p.flags[0].action


def test_evidence_decides_the_order(tmp_path):
    assert column(profile(tmp_path, "d\n15/02/2026\n03/04/2026\n"), "d")["date_format"] == "dd/MM/yyyy"  # 15 can only be a day
    us = profile(tmp_path, "d\n02/15/2026\n03/04/2026\n", name="us.csv")
    assert column(us, "d")["date_format"] == "MM/dd/yyyy" and not column(us, "d")["date_ambiguous"] and us.flags == []
    contradiction = profile(tmp_path, "d\n15/02/2026\n02/15/2026\n", name="c.csv")
    assert column(contradiction, "d")["type"] == "mixed"


def test_impossible_dates_and_mixed_formats_are_not_typed_as_dates(tmp_path):
    assert column(profile(tmp_path, "d\n01/02/2026\n31/02/2026\n"), "d")["type"] == "mixed"
    assert column(profile(tmp_path, "d\n2026-01-02\n03/04/2026\n", name="m.csv"), "d")["type"] == "mixed"
    assert column(profile(tmp_path, "d\n2026-13-45\n", name="i.csv"), "d")["type"] == "text"


def test_time_and_padding_shape_the_spark_pattern(tmp_path):
    ts = column(profile(tmp_path, "d\n2026-01-02 10:30:00\n2026-01-03 11:45:59\n"), "d")
    assert ts["has_time"] and ts["date_format"] == "yyyy-MM-dd HH:mm:ss"
    loose = profile(tmp_path, "d\n1/2/2026\n15/3/2026\n", name="l.csv")
    assert column(loose, "d")["date_format"] == "d/M/yyyy"
    mixed_padding = column(profile(tmp_path, "d\n1/2/2026\n01/02/2026\n", name="p.csv"), "d")
    assert mixed_padding["distinct"] is None  # two spellings of one date: the raw count would not survive a typed load


# ---- numbers -----------------------------------------------------------------------------------

def test_brazilian_and_american_numbers_are_told_apart_by_the_evidence(tmp_path):
    def col(text, name):
        return column(profile(tmp_path, text, name=name), "v")

    assert col("id;v\n1;1.234,56\n2;12.5\n", "a.csv")["type"] == "mixed"  # both conventions in one column
    us = col("id;v\n1;1.234\n2;5.5\n", "b.csv")  # without a comma decimal, 1.234 stays a US decimal
    assert (us["type"], us["number_style"], us["max"]) == ("decimal", "us", "5.5") and us["min"] == "1.234"
    br = col("id;v\n1;1.234\n2;12,5\n", "c.csv")  # with one, 1.234 is one thousand two hundred thirty-four
    assert (br["type"], br["number_style"], br["max"]) == ("decimal", "br", "1234")
    neg = col("id;v\n1;-1.234,5\n2;3,25\n", "d.csv")
    assert (neg["min"], neg["max"], neg["max_scale"]) == ("-1234.5", "3.25", 2)


def test_distinct_counts_what_a_typed_load_would_see(tmp_path):
    assert column(profile(tmp_path, "id;v\n1;1,5\n2;1,50\n3;2,5\n"), "v")["distinct"] == 2  # 1,5 and 1,50 are one value
    assert column(profile(tmp_path, "id;v\n1;7\n2;007\n", name="i.csv"), "v")["distinct"] == 1


# ---- what the mapping rules do with it ---------------------------------------------------------

def test_type_rules_follow_the_measured_format():
    with_time = {"type": "date", "has_time": True, "date_format": "yyyy-MM-dd HH:mm:ss"}
    assert infer_type(with_time) == "timestamp" and infer_type({"type": "date"}) == "date"
    assert "hora" in type_conflict(with_time, "date") and type_conflict(with_time, "timestamp") is None
    assert safe_type(with_time, "date") == "timestamp"
    assert "formato de data" in type_conflict({"type": "text"}, "date")
    fixed, changes = correct_mapping([{"name": "quando", **with_time}], {"quando": {"target": "quando", "type": "date"}})
    assert fixed["quando"]["type"] == "timestamp" and changes[0]["field"] == "tipo"


# ---- the generated load and its reconciliation -------------------------------------------------

def approved_run(mappings):
    return {"id": 1, "decision": "approved", "decided_by": "t", "decided_at": "x", "mappings": mappings}


BR_MAPPING = {"pedido": {"target": "pedido", "type": "int"}, "data": {"target": "data", "type": "date"},
              "valor": {"target": "valor", "type": "decimal"}, "cliente": {"target": "cliente", "type": "string"}}


@pytest.mark.parametrize("target", ["databricks", "microsoft_fabric"])
def test_the_notebook_uses_the_measured_encoding_and_formats(tmp_path, target):
    p = profile(tmp_path, BR, "windows-1252").to_dict()
    files = build_bundle(target=target, dataset={"filename": "vendas.csv"}, profile=p, run=approved_run(BR_MAPPING),
                         params=default_params("vendas.csv", target))
    code = files["02_carga.py"] if target == "databricks" else "\n".join(
        "".join(cell["source"]) for cell in json.loads(files["02_carga_lakehouse.ipynb"])["cells"])
    ast.parse(code)
    assert 'ENCODING = "windows-1252"' in code and '"data": {"date": "dd/MM/yyyy"}' in code and '"valor": {"number": "br"}' in code
    assert "F.to_date(column, fmt[\"date\"])" in code and "regexp_replace" in code
    assert "convert(src, kind).isNull()" in code  # the lost-value guard uses the very same conversion
    manifest = json.loads(files["manifest.json"])
    assert manifest["codificacao_origem"] == "windows-1252" and manifest["formatos_medidos"]["data"] == {"date": "dd/MM/yyyy"}


SPARK_TO_STRPTIME = {"yyyy": "%Y", "MM": "%m", "M": "%m", "dd": "%d", "d": "%d", "HH": "%H", "H": "%H", "mm": "%M", "ss": "%S"}


def strptime_of(spark_format: str) -> str:
    return re.sub("yyyy|MM|M|dd|d|HH|H|mm|ss", lambda m: SPARK_TO_STRPTIME[m.group(0)], spark_format.replace("'T'", "T"))


def load_like_the_notebook(path: Path, encoding: str, delimiter: str, mapping: dict, formats: dict) -> sqlite3.Connection:
    """Re-implement the notebook's conversions (trim, empty to NULL, BR number, date pattern) in plain Python."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (" + ", ".join(f'"{m["target"]}"' for m in mapping.values()) + ")")
    with path.open(newline="", encoding=encoding) as handle:
        for row in csv.DictReader(handle, delimiter=delimiter):
            values = []
            for src, m in mapping.items():
                raw = (row[src] or "").strip()
                fmt = formats.get(src, {})
                if raw == "":
                    values.append(None)
                elif m["type"] == "date":
                    values.append(datetime.strptime(raw, strptime_of(fmt["date"])).date().isoformat())
                elif m["type"] in ("decimal", "double"):
                    values.append(float(Decimal(raw.replace(".", "").replace(",", ".") if fmt.get("number") == "br" else raw)))
                elif m["type"] in ("int", "bigint"):
                    values.append(int(raw))
                else:
                    values.append(raw)
            db.execute("INSERT INTO t VALUES (" + ",".join("?" * len(mapping)) + ")", values)
    return db


@pytest.mark.parametrize("target,dialect", [("databricks", "databricks"), ("microsoft_fabric", "tsql")])
def test_reconciliation_matches_a_real_load_of_a_brazilian_file(tmp_path, target, dialect):
    path = tmp_path / "vendas.csv"
    path.write_bytes(BR.encode("windows-1252"))
    prof = profile_csv(path).to_dict()
    files = build_bundle(target=target, dataset={"filename": "vendas.csv"}, profile=prof, run=approved_run(BR_MAPPING),
                         params=default_params("vendas.csv", target))
    formats = json.loads(files["manifest.json"])["formatos_medidos"]
    db = load_like_the_notebook(path, "cp1252", prof["delimiter"], BR_MAPPING, formats)
    tree = sqlglot.parse_one(files["03_reconciliacao.sql"], read=dialect)
    for table in tree.find_all(sqlglot.exp.Table):
        table.set("db", None), table.set("catalog", None), table.set("this", sqlglot.exp.to_identifier("t"))
    rows = db.execute(tree.sql(dialect="sqlite")).fetchall()
    assert len(rows) >= 10 and [r for r in rows if r[3] != "OK"] == []
    checks = {r[0] for r in rows}
    assert {"min(data)", "max(data)", "min(valor)", "max(valor)", "distintos(valor)"} <= checks


# ---- end to end through the app ----------------------------------------------------------------

ANSWER = json.dumps({c: {"target": c, "type": t} for c, t in (("pedido", "int"), ("data", "date"), ("valor", "decimal"), ("cliente", "string"))})


class Fake:
    def complete(self, *, model, payload, **kwargs):
        return ProviderResponse(ANSWER, 100, 50, 0.0001)


def test_a_brazilian_file_goes_from_upload_to_code_with_its_formats(tmp_path):
    client = TestClient(create_app(tmp_path, provider_factory=Fake, pricing=DeepSeekPricing(0.04, 0.08)), follow_redirects=False)
    client.post("/signup", data={"email": "a@example.com", "password": "correct-horse-1"})
    location = client.post("/app/datasets", files={"file": ("vendas.csv", BR.encode("windows-1252"))}, data={"target": "databricks"}).headers["location"]
    page = client.get(location).text
    assert "windows-1252" in client.get(location + "/report").text and "Arquivo fora de UTF-8" in client.get(location + "/report").text
    assert "dd/MM/yyyy" in client.get(location + "/report").text and page
    events = [json.loads(x) for x in client.post(location + "/mapping/run").text.splitlines() if x]
    run_id = next(e["run_id"] for e in events if e["type"] == "saved")
    assert next(e for e in events if e["type"] == "checks")["pass_rate"] == 1.0  # date and decimal fit the measured data
    assert client.post(f"{location}/mapping/runs/{run_id}/decision", data={"decision": "approved"}).json()["ok"]
    migration = client.get(location + "/migration?target=databricks").text
    assert "windows-1252" in migration and "dd/MM/yyyy" in migration
