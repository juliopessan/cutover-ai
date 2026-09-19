#!/usr/bin/env python3
"""Generates synthetic Oracle Exadata metadata and sample CSVs for Databricks testing.

Produces JSON artifacts under `outputs/oracle-databricks/synthetic_data`:
- account_metadata.json
- databases.json
- data_lineage.json
- rbac_grants.json

This is intentionally lightweight and deterministic for test runs.
"""

import json
import random
from pathlib import Path
from faker import Faker


def gen_account():
    fake = Faker()
    return {
        "account_name": f"oracle-exadata-{fake.domain_word()}",
        "instances": [
            {"name": f"exadata-{i}", "cpu": random.choice([32, 64, 96]), "storage_tb": random.choice([12, 24, 48])}
            for i in range(1, 3)
        ],
    }


ORACLE_TYPES = ["VARCHAR2", "NUMBER", "FLOAT", "DATE", "TIMESTAMP", "CLOB", "BLOB", "XMLTYPE"]


def gen_table(name_prefix: str, cols: int = 6) -> dict:
    cols_def = []
    for i in range(cols):
        col = {
            "name": f"c_{i}",
            "type": random.choice(ORACLE_TYPES),
            "nullable": random.choice([True, False]),
        }
        cols_def.append(col)

    row_count = random.choice([1000, 10000, 100000, 1000000])
    bytes_est = int(row_count * cols * 8)
    return {"table_name": name_prefix, "columns": cols_def, "row_count": row_count, "bytes": bytes_est}


def gen_schema(schema_name: str, tables_n: int = 3) -> dict:
    return {"name": schema_name, "tables": [gen_table(f"t_{i}") for i in range(tables_n)]}


def main():
    out = Path("outputs/oracle-databricks/synthetic_data")
    out.mkdir(parents=True, exist_ok=True)

    account = gen_account()
    databases = {"databases": []}

    for db_i in range(1, 4):
        db_name = f"ORCL_DB_{db_i}"
        schemas = [gen_schema(f"S{db_i}_{s}", tables_n=random.choice([2,3,4])) for s in range(1, random.choice([2,3]) + 1)]
        databases["databases"].append({"name": db_name, "schemas": schemas})

    lineage = {"lineage_graph": []}
    rbac = {"grants": [{"principal": "DBA_ROLE", "privilege": "ALL"}]}

    (out / "account_metadata.json").write_text(json.dumps(account, indent=2), encoding="utf-8")
    (out / "databases.json").write_text(json.dumps(databases, indent=2), encoding="utf-8")
    (out / "data_lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    (out / "rbac_grants.json").write_text(json.dumps(rbac, indent=2), encoding="utf-8")

    print("✅ Oracle Exadata synthetic metadata generated:")
    for p in out.iterdir():
        print(" -", p)


if __name__ == "__main__":
    main()
