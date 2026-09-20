import ast
import csv
import json
import sqlite3
from pathlib import Path

import pytest
import sqlglot

from cutover.codegen import CodegenError, Params, build_bundle, default_params, plan_columns
from cutover.codegen.generate import spark_type, tsql_type
from cutover.web.profiling import profile_csv

FIXTURES = Path(__file__).parent / "fixtures" / "cloudera_covid"
COUNTRY = {"country": ("country", "string"), "alpha_2code": ("alpha_2code", "string"), "alpha_3code": ("alpha_3code", "string"),
           "numeric_code": ("numeric_code", "int"), "latitude_avg": ("latitude_avg", "decimal"), "longitude_avg": ("longitude_avg", "decimal")}
POP = {"country_code": ("country_code", "string"), "population": ("population", "bigint")}


def mapping(spec):
    return {src: {"target": t, "type": k} for src, (t, k) in spec.items()}


def bundle(name, spec, target, **overrides):
    profile = profile_csv(FIXTURES / name).to_dict()
    run = {"id": 7, "decision": "approved", "decided_by": "ana@x.com", "decided_at": "2026-01-01 10:00:00", "mappings": mapping(spec)}
    params = default_params(name, target)
    if overrides:
        params = Params(**{**params.__dict__, **overrides})
    return build_bundle(target=target, dataset={"filename": name}, profile=profile, run=run, params=params), profile


@pytest.mark.parametrize("target", ["databricks", "microsoft_fabric"])
def test_every_generated_file_is_syntactically_valid(target):
    files, _ = bundle("ref__country_codes.csv", COUNTRY, target)
    dialect = "databricks" if target == "databricks" else "tsql"
    for name, text in files.items():
        if name.endswith(".sql"):
            assert sqlglot.parse(text, read=dialect), name
        elif name.endswith(".py"):
            ast.parse(text)
        elif name.endswith(".ipynb"):
            for cell in json.loads(text)["cells"]:
                ast.parse("".join(cell["source"]))
    assert json.loads(files["manifest.json"])["executado"] is False


def test_manifest_records_traceability_and_file_hashes():
    import hashlib

    files, profile = bundle("ref__populations.csv", POP, "databricks")
    manifest = json.loads(files["manifest.json"])
    assert manifest["sha256_origem"] == profile["sha256"] and manifest["execucao"] == 7 and manifest["aprovado_por"] == "ana@x.com"
    for name, digest in manifest["arquivos"].items():
        assert hashlib.sha256(files[name].encode()).hexdigest() == digest


def test_types_are_derived_from_measured_data():
    profile = profile_csv(FIXTURES / "ref__country_codes.csv").to_dict()
    cols = {c.source: c for c in plan_columns(profile, mapping(COUNTRY))}
    assert spark_type(cols["latitude_avg"]).startswith("DECIMAL(") and spark_type(cols["numeric_code"]) == "INT"
    assert tsql_type(cols["numeric_code"]) == "INT" and tsql_type(cols["country"]) in {"VARCHAR(64)", "VARCHAR(128)", "VARCHAR(256)", "VARCHAR(32)"}
    assert tsql_type(cols["country"]).startswith("VARCHAR(") and int(tsql_type(cols["country"])[8:-1]) >= profile["columns"][0]["max_len"]


def test_unapproved_or_unsafe_mappings_are_refused():
    profile = profile_csv(FIXTURES / "ref__populations.csv").to_dict()
    run = {"id": 1, "decision": "pending", "mappings": mapping(POP)}
    with pytest.raises(CodegenError, match="aprovado"):
        build_bundle(target="databricks", dataset={"filename": "p.csv"}, profile=profile, run=run, params=default_params("p.csv", "databricks"))
    for bad in ({"country_code": {"target": "a b", "type": "string"}}, {"country_code": {"target": "Upper", "type": "string"}},
                {"country_code": {"target": "x", "type": "money"}}):
        with pytest.raises(CodegenError):
            plan_columns(profile, {**mapping(POP), **bad})
    with pytest.raises(CodegenError, match="repetido"):
        plan_columns(profile, {"country_code": {"target": "same", "type": "string"}, "population": {"target": "same", "type": "bigint"}})
    with pytest.raises(CodegenError, match="não tem destino"):
        plan_columns(profile, {"country_code": {"target": "x", "type": "string"}})


@pytest.mark.parametrize("field,value", [("table", "t; DROP TABLE x"), ("schema", "a-b"), ("catalog", "x`y"),
                                         ("source_path", "/v/a'; rm -rf /")])
def test_parameters_cannot_inject_code(field, value):
    with pytest.raises(CodegenError):
        bundle("ref__populations.csv", POP, "databricks", **{field: value})


def test_hostile_source_column_names_are_escaped_not_executed():
    profile = {"sha256": "0" * 64, "rows": 1, "duplicate_rows": 0, "delimiter": ",", "flags": [], "privacy_hints": [],
               "columns": [{"name": "a`b\"c'd", "type": "text", "nulls": 0, "distinct": 1, "max_len": 1}]}
    run = {"id": 1, "decision": "approved", "mappings": {"a`b\"c'd": {"target": "safe", "type": "string"}}}
    files = build_bundle(target="databricks", dataset={"filename": "x.csv"}, profile=profile, run=run, params=default_params("x.csv", "databricks"))
    ast.parse(files["02_carga.py"])
    sqlglot.parse(files["01_ddl.sql"], read="databricks")
    assert "a`b" in files["02_carga.py"] and "'a`b" not in files["02_carga.py"].split("COLUMNS")[0]


@pytest.mark.parametrize("target,dialect", [("databricks", "databricks"), ("microsoft_fabric", "tsql")])
def test_hostile_names_stay_valid_in_both_dialects(target, dialect):
    profile = {"sha256": "0" * 64, "rows": 1, "duplicate_rows": 0, "delimiter": ",", "flags": [], "privacy_hints": [],
               "columns": [{"name": "o'brien\\x", "type": "text", "nulls": 0, "distinct": 1, "max_len": 3}]}
    run = {"id": 1, "decision": "approved", "mappings": {"o'brien\\x": {"target": "safe", "type": "string"}}}
    files = build_bundle(target=target, dataset={"filename": "x.csv\nDROP TABLE users; --\r.csv"}, profile=profile, run=run,
                         params=default_params("x.csv", target))
    for name, text in files.items():
        if name.endswith(".sql"):
            statements = [s for s in sqlglot.parse(text, read=dialect) if s]
            assert len(statements) == 1  # the hostile filename never becomes a second statement
            assert not any(isinstance(node, sqlglot.exp.Drop) for s in statements for node in s.walk())
        if name.endswith(".py"):
            assert "DROP TABLE" not in "".join(line for line in text.splitlines() if not line.startswith("#"))
        if name.endswith(".ipynb"):
            for cell in json.loads(text)["cells"]:
                ast.parse("".join(cell["source"]))


def load_source(path: Path, spec: dict, tamper: bool = False) -> sqlite3.Connection:
    """Reproduce the load in an independent engine: rename, trim, empty to NULL, cast to the approved type."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (" + ", ".join(f'"{t}"' for t, _ in spec.values()) + ")")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            values = []
            for src, (_, kind) in spec.items():
                raw = (row[src] or "").strip()
                if tamper and i == 0 and kind in ("int", "bigint"):
                    raw = "999999999999"
                values.append(None if raw == "" else int(raw) if kind in ("int", "bigint") else float(raw) if kind in ("double", "decimal") else raw)
            db.execute("INSERT INTO t VALUES (" + ",".join("?" * len(spec)) + ")", values)
    return db


def reconcile(files: dict, db: sqlite3.Connection, dialect: str) -> list[tuple]:
    # Point every table reference at the in-memory table, then run the generated SQL for real.
    tree = sqlglot.parse_one(files["03_reconciliacao.sql"], read=dialect)
    for table in tree.find_all(sqlglot.exp.Table):
        table.set("db", None), table.set("catalog", None), table.set("this", sqlglot.exp.to_identifier("t"))
    return db.execute(tree.sql(dialect="sqlite")).fetchall()


@pytest.mark.parametrize("target,dialect", [("databricks", "databricks"), ("microsoft_fabric", "tsql")])
@pytest.mark.parametrize("name,spec", [("ref__country_codes.csv", COUNTRY), ("ref__populations.csv", POP)])
def test_reconciliation_matches_a_real_load_of_the_same_file(name, spec, target, dialect):
    files, _ = bundle(name, spec, target)
    rows = reconcile(files, load_source(FIXTURES / name, spec), dialect)
    assert len(rows) >= 8 and [r for r in rows if r[3] != "OK"] == []


def test_reconciliation_detects_tampered_data():
    files, _ = bundle("ref__populations.csv", POP, "databricks")
    rows = reconcile(files, load_source(FIXTURES / "ref__populations.csv", POP, tamper=True), "databricks")
    assert any(r[3] == "DIVERGE" for r in rows)  # a corrupted value must not reconcile


def test_duplicates_option_changes_expected_rows():
    path = FIXTURES.parent.parent / "fixtures"
    profile = {"sha256": "0" * 64, "rows": 10, "duplicate_rows": 3, "delimiter": ",", "flags": [], "privacy_hints": [],
               "columns": [{"name": "a", "type": "integer", "nulls": 0, "distinct": 7, "min": "1", "max": "9", "max_len": 1}]}
    run = {"id": 1, "decision": "approved", "mappings": {"a": {"target": "a", "type": "int"}}}
    keep = build_bundle(target="databricks", dataset={"filename": "d.csv"}, profile=profile, run=run, params=default_params("d.csv", "databricks"))
    drop = build_bundle(target="databricks", dataset={"filename": "d.csv"}, profile=profile, run=run,
                        params=Params(**{**default_params("d.csv", "databricks").__dict__, "drop_duplicates": True}))
    assert "EXPECTED_ROWS = 10" in keep["02_carga.py"] and "EXPECTED_ROWS = 7" in drop["02_carga.py"]
    assert "distintos(a)" in keep["03_reconciliacao.sql"] and "distintos(a)" not in drop["03_reconciliacao.sql"]
    assert path.exists()
