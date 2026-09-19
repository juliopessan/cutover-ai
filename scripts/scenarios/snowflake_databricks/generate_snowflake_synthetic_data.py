#!/usr/bin/env python3
"""
Gerador de dados sintéticos estilo Snowflake para teste de migração para Databricks.
Simula: conta/warehouses, databases/schemas/tabelas, linhagem (tasks/streams/pipes), RBAC (roles/grants).
"""

import json
import uuid
from datetime import datetime, timedelta
from faker import Faker
from pathlib import Path

fake = Faker()

SNOWFLAKE_TYPES = [
    "VARCHAR", "NUMBER", "FLOAT", "BOOLEAN", "DATE",
    "TIMESTAMP_NTZ", "TIMESTAMP_TZ", "VARIANT", "OBJECT", "ARRAY", "BINARY",
]

WAREHOUSE_SIZES = ["X-SMALL", "SMALL", "MEDIUM", "LARGE", "X-LARGE", "2X-LARGE"]


def generate_snowflake_account_metadata() -> dict:
    """Simula metadados de uma conta Snowflake."""
    num_warehouses = fake.random_int(2, 6)
    warehouses = []
    for _ in range(num_warehouses):
        warehouses.append({
            "name": f"WH_{fake.domain_word().upper()}",
            "size": fake.random.choice(WAREHOUSE_SIZES),
            "type": fake.random.choice(["STANDARD", "SNOWPARK-OPTIMIZED"]),
            "auto_suspend_seconds": fake.random.choice([60, 300, 600]),
            "auto_resume": True,
            "avg_credits_per_hour": round(fake.random.uniform(1, 128), 2),
        })

    return {
        "account_id": str(uuid.uuid4()),
        "account_name": f"snowflake-{fake.domain_word()}",
        "edition": fake.random.choice(["ENTERPRISE", "BUSINESS_CRITICAL"]),
        "cloud_provider": fake.random.choice(["AWS", "AZURE", "GCP"]),
        "region": fake.random.choice(["us-east-1", "eastus2", "us-central1", "westeurope"]),
        "deployed_at": (datetime.now() - timedelta(days=fake.random_int(60, 900))).isoformat(),
        "warehouses": warehouses,
        "total_storage_tb": round(fake.random.uniform(5, 200), 2),
        "total_credits_month": round(fake.random.uniform(500, 25000), 2),
    }


def generate_snowflake_database(db_name: str) -> dict:
    """Simula um banco de dados Snowflake com schemas e tabelas."""
    schemas = []
    num_schemas = fake.random_int(2, 5)

    for _ in range(num_schemas):
        schema_name = f"{fake.domain_word()}_schema"
        tables = []
        num_tables = fake.random_int(3, 10)

        for _ in range(num_tables):
            table_name = f"{fake.domain_word()}_{fake.domain_word()}"
            num_cols = fake.random_int(5, 25)

            columns = []
            for _ in range(num_cols):
                col_type = fake.random.choice(SNOWFLAKE_TYPES)
                columns.append({
                    "name": fake.word(),
                    "type": col_type,
                    "comment": fake.sentence(nb_words=5),
                    "nullable": fake.boolean(),
                })

            tables.append({
                "table_id": str(uuid.uuid4()),
                "name": table_name,
                "table_type": fake.random.choice(["PERMANENT", "TRANSIENT", "EXTERNAL", "VIEW"]),
                "owner": fake.user_name(),
                "created_at": (datetime.now() - timedelta(days=fake.random_int(1, 730))).isoformat(),
                "last_modified": (datetime.now() - timedelta(hours=fake.random_int(1, 720))).isoformat(),
                "row_count": fake.random_int(1000, 20000000),
                "bytes": fake.random_int(10_000_000, 500_000_000_000),
                "clustering_key": f"({fake.word()})" if fake.boolean(chance_of_getting_true=30) else None,
                "retention_time_days": fake.random.choice([0, 1, 7, 90]),
                "columns": columns,
            })

        schemas.append({
            "schema_id": str(uuid.uuid4()),
            "name": schema_name,
            "tables": tables,
        })

    return {
        "database_id": str(uuid.uuid4()),
        "name": db_name,
        "owner": fake.user_name(),
        "created_at": (datetime.now() - timedelta(days=fake.random_int(30, 1000))).isoformat(),
        "schemas": schemas,
    }


def generate_data_lineage() -> dict:
    """Simula linhagem de dados via Tasks, Streams e Pipes."""
    lineage_jobs = []

    for _ in range(fake.random_int(10, 25)):
        num_inputs = fake.random_int(1, 5)
        num_outputs = fake.random_int(1, 3)

        lineage_jobs.append({
            "job_id": str(uuid.uuid4()),
            "job_name": f"{fake.domain_word()}_pipeline_{fake.random_int(1, 9999)}",
            "job_type": fake.random.choice(["TASK", "STREAM", "PIPE", "DBT_MODEL"]),
            "owner": fake.user_name(),
            "warehouse": f"WH_{fake.domain_word().upper()}",
            "schedule": fake.random.choice(["1 MINUTE", "HOURLY", "DAILY", "WEEKLY", "ON_DEMAND"]),
            "inputs": [
                {
                    "source": fake.random.choice(["TABLE", "STAGE", "EXTERNAL_TABLE"]),
                    "name": f"{fake.domain_word()}.{fake.domain_word()}",
                    "record_count": fake.random_int(10000, 100000000),
                }
                for _ in range(num_inputs)
            ],
            "outputs": [
                {
                    "target": fake.random.choice(["TABLE", "MATERIALIZED_VIEW"]),
                    "name": f"{fake.domain_word()}.{fake.domain_word()}",
                }
                for _ in range(num_outputs)
            ],
            "transformations": [
                {
                    "type": fake.random.choice(["FILTER", "JOIN", "AGGREGATE", "MERGE", "UDF"]),
                    "description": fake.sentence(),
                }
                for _ in range(fake.random_int(1, 5))
            ],
            "last_run": (datetime.now() - timedelta(hours=fake.random_int(1, 168))).isoformat(),
            "avg_duration_minutes": fake.random_int(1, 240),
            "success_rate": round(fake.random.uniform(0.85, 1.0), 4),
        })

    return {
        "lineage_graph": lineage_jobs,
        "discovered_at": datetime.now().isoformat(),
    }


def generate_rbac_grants() -> dict:
    """Simula matriz de roles e grants (RBAC)."""
    grants = []

    for _ in range(fake.random_int(20, 50)):
        grants.append({
            "role_name": fake.random.choice(["SYSADMIN", "SECURITYADMIN", "ACCOUNTADMIN", f"{fake.domain_word().upper()}_ROLE"]),
            "granted_to": f"{fake.user_name()}@{fake.domain_name()}",
            "privileges": fake.random.sample(
                ["SELECT", "INSERT", "UPDATE", "DELETE", "USAGE", "OWNERSHIP", "CREATE TABLE"],
                k=fake.random_int(1, 4),
            ),
            "on_object_type": fake.random.choice(["DATABASE", "SCHEMA", "TABLE", "WAREHOUSE"]),
            "on_object_name": f"{fake.domain_word()}.{fake.domain_word()}",
            "granted_at": (datetime.now() - timedelta(days=fake.random_int(1, 365))).isoformat(),
            "granted_by": fake.user_name(),
        })

    return {
        "total_grants": len(grants),
        "grants": grants,
        "audit_timestamp": datetime.now().isoformat(),
    }


def main():
    """Gera e salva dados sintéticos completos."""

    output_dir = Path("outputs/snowflake-databricks/synthetic_data")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("🔄 Gerando dados sintéticos Snowflake...\n")

    # 1. Conta / Warehouses
    print("  ✓ Metadados de Conta e Warehouses")
    account = generate_snowflake_account_metadata()
    with open(output_dir / "account_metadata.json", "w") as f:
        json.dump(account, f, indent=2)

    # 2. Databases, Schemas e Tabelas
    print("  ✓ Databases, Schemas e Tabelas")
    databases = []
    for i in range(fake.random_int(3, 7)):
        db = generate_snowflake_database(f"db_{fake.domain_word()}_{i}")
        databases.append(db)

    with open(output_dir / "databases.json", "w") as f:
        json.dump({"databases": databases}, f, indent=2)

    total_schemas = sum(len(db["schemas"]) for db in databases)
    total_tables = sum(len(s["tables"]) for db in databases for s in db["schemas"])
    print(f"    └─ {total_schemas} schemas / {total_tables} tabelas criadas")

    # 3. Linhagem (Tasks/Streams/Pipes)
    print("  ✓ Linhagem de Dados (Tasks/Streams/Pipes)")
    lineage = generate_data_lineage()
    with open(output_dir / "data_lineage.json", "w") as f:
        json.dump(lineage, f, indent=2)

    # 4. RBAC (Roles e Grants)
    print("  ✓ RBAC (Roles e Grants)")
    rbac = generate_rbac_grants()
    with open(output_dir / "rbac_grants.json", "w") as f:
        json.dump(rbac, f, indent=2)

    # 5. Summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "account": account["account_name"],
        "edition": account["edition"],
        "cloud_provider": account["cloud_provider"],
        "total_databases": len(databases),
        "total_schemas": total_schemas,
        "total_tables": total_tables,
        "total_lineage_jobs": len(lineage["lineage_graph"]),
        "total_rbac_grants": rbac["total_grants"],
        "artifacts_location": str(output_dir),
    }

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n✅ Dados sintéticos Snowflake gerados com sucesso!")
    print(f"\n📊 Resumo:")
    print(f"   • Conta: {summary['account']} ({summary['edition']} / {summary['cloud_provider']})")
    print(f"   • Bancos de dados: {summary['total_databases']}")
    print(f"   • Schemas: {summary['total_schemas']}")
    print(f"   • Tabelas: {summary['total_tables']}")
    print(f"   • Jobs/Lineage: {summary['total_lineage_jobs']}")
    print(f"   • Grants RBAC: {summary['total_rbac_grants']}")
    print(f"\n📁 Arquivos salvos em: {summary['artifacts_location']}\n")

    return summary


if __name__ == "__main__":
    main()
