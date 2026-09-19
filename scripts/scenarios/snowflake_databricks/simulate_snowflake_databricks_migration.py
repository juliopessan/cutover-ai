#!/usr/bin/env python3
"""
Simulador de migração Snowflake → Databricks (Unity Catalog).
Transforma metadados, gera plano de migração, valida compatibilidade.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path


def load_synthetic_data(artifacts_dir: Path) -> dict:
    """Carrega dados sintéticos gerados."""
    data = {}

    for json_file in ["account_metadata.json", "databases.json", "data_lineage.json", "rbac_grants.json"]:
        path = artifacts_dir / json_file
        if path.exists():
            with open(path) as f:
                data[json_file.replace(".json", "")] = json.load(f)

    return data


def map_snowflake_type_to_databricks(sf_type: str) -> tuple[str, dict]:
    """Mapeia tipos Snowflake para tipos Databricks (Delta/Spark SQL)."""
    type_mapping = {
        "VARCHAR": ("STRING", {}),
        "NUMBER": ("DECIMAL", {"precision": 38, "scale": 10}),
        "FLOAT": ("DOUBLE", {}),
        "BOOLEAN": ("BOOLEAN", {}),
        "DATE": ("DATE", {}),
        "TIMESTAMP_NTZ": ("TIMESTAMP_NTZ", {}),
        "TIMESTAMP_TZ": ("TIMESTAMP", {"warning": "Timezone info collapsed to UTC — normalizar antes da migração"}),
        "VARIANT": ("VARIANT", {"warning": "Requer Databricks Runtime 15+ para tipo VARIANT nativo; fallback: STRING (JSON)"}),
        "OBJECT": ("STRUCT", {"warning": "Mapeamento manual de STRUCT recomendado; fallback: STRING (JSON)"}),
        "ARRAY": ("ARRAY<STRING>", {"warning": "Elemento assumido como STRING; validar tipo real"}),
        "BINARY": ("BINARY", {}),
    }
    return type_mapping.get(sf_type, ("STRING", {"warning": f"Tipo desconhecido: {sf_type}"}))


def build_migration_plan(source_data: dict) -> dict:
    """Constrói plano de migração com fases e tarefas."""

    if "databases" not in source_data:
        return {"phase_0": "No data available"}

    databases_payload = source_data["databases"]
    databases = databases_payload.get("databases", [])

    total_schemas = sum(len(db["schemas"]) for db in databases)
    total_tables = sum(len(s["tables"]) for db in databases for s in db["schemas"])
    total_bytes = sum(
        t["bytes"]
        for db in databases
        for s in db["schemas"]
        for t in s["tables"]
    )
    total_size_gb = total_bytes / (1024 ** 3)

    account = source_data.get("account_metadata", {})
    warehouses = account.get("warehouses", [])

    migration_phases = {
        "phase_0_readiness": {
            "title": "Avaliação de Prontidão",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Validar compatibilidade de tipos de dados (VARIANT/OBJECT/ARRAY)",
                    "status": "READY",
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Mapear roles/grants Snowflake para Unity Catalog RBAC",
                    "status": "READY",
                    "rbac_grants": len(source_data.get("rbac_grants", {}).get("grants", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Estimar tempo e custo de migração",
                    "status": "READY",
                    "estimated_duration_hours": int(total_size_gb / 150) + 2,  # ~150 GB/hora
                    "estimated_cost_usd": round(total_size_gb * 0.04, 2),  # ~$0.04/GB
                },
            ],
        },
        "phase_1_assessment": {
            "title": "Descoberta e Mapeamento",
            "databases_count": len(databases),
            "schemas_count": total_schemas,
            "tables_count": total_tables,
            "total_data_volume_gb": round(total_size_gb, 2),
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Catalogar metadados Snowflake (databases/schemas/tabelas)",
                    "status": "IN_PROGRESS",
                    "records_extracted": total_tables,
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Mapear tipos de dados Snowflake → Delta/Spark SQL",
                    "status": "IN_PROGRESS",
                    "type_mappings": sum(
                        len(t["columns"])
                        for db in databases
                        for s in db["schemas"]
                        for t in s["tables"]
                    ),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Analisar linhagem (Tasks/Streams/Pipes → Workflows/DLT)",
                    "status": "IN_PROGRESS",
                    "lineage_jobs": len(source_data.get("data_lineage", {}).get("lineage_graph", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Dimensionar warehouses Snowflake → SQL Warehouses/clusters Databricks",
                    "status": "IN_PROGRESS",
                    "warehouses_analyzed": len(warehouses),
                },
            ],
        },
        "phase_2_infrastructure": {
            "title": "Provisionamento Databricks (Unity Catalog)",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Configurar Unity Catalog metastore",
                    "status": "PENDING",
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Provisionar external locations e storage credentials",
                    "status": "PENDING",
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Criar catalogs e schemas (Delta Lake)",
                    "status": "PENDING",
                    "catalogs": len(databases),
                    "schemas": total_schemas,
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Provisionar SQL Warehouses / clusters",
                    "status": "PENDING",
                    "source_warehouses": len(warehouses),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Configurar lineage tracking com Unity Catalog + Purview",
                    "status": "PENDING",
                },
            ],
        },
        "phase_3_data_migration": {
            "title": "Migração de Dados",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Executar migração full-load (COPY INTO / conector Snowflake)",
                    "status": "PENDING",
                    "tables_to_migrate": total_tables,
                    "incremental_strategy": "MERGE",
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Converter Tasks/Streams/Pipes em Databricks Workflows/DLT",
                    "status": "PENDING",
                    "jobs_to_convert": len(source_data.get("data_lineage", {}).get("lineage_graph", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Validar reconciliação de dados",
                    "status": "PENDING",
                    "row_count_validation": True,
                    "checksum_validation": True,
                },
            ],
        },
        "phase_4_validation": {
            "title": "Teste e Validação",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Executar testes de performance",
                    "status": "PENDING",
                    "performance_gates": {
                        "query_latency_target_ms": 500,
                        "throughput_target_rowspersec": 100000,
                    },
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Validar RBAC / Unity Catalog ACLs",
                    "status": "PENDING",
                    "grants_to_validate": len(source_data.get("rbac_grants", {}).get("grants", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Validar conformidade LGPD/GDPR",
                    "status": "PENDING",
                    "compliance_checks": ["PII_masking", "retention_policies", "audit_logging"],
                },
            ],
        },
        "phase_5_cutover": {
            "title": "Cutover e Go-Live",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Executar sincronização final",
                    "status": "PENDING",
                    "sync_mode": "CDC_FINAL",
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Ativar aplicações em Databricks",
                    "status": "PENDING",
                    "applications": 3,
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Monitoramento pós-cutover (72h)",
                    "status": "PENDING",
                    "sla_monitoring": True,
                },
            ],
        },
    }

    return {
        "migration_id": str(uuid.uuid4()),
        "source_platform": "Snowflake",
        "target_platform": "Databricks (Unity Catalog)",
        "created_at": datetime.now().isoformat(),
        "phases": migration_phases,
        "summary": {
            "total_phases": len(migration_phases),
            "total_tasks": sum(len(p.get("tasks", [])) for p in migration_phases.values()),
            "estimated_effort_weeks": 7,
            "go_live_date": "2026-10-01",
        },
    }


def validate_migration_compatibility(source_data: dict) -> dict:
    """Valida compatibilidade da migração Snowflake → Databricks."""

    issues = []
    warnings = []

    if "databases" in source_data:
        for db in source_data["databases"].get("databases", []):
            for schema in db.get("schemas", []):
                for table in schema.get("tables", []):
                    for col in table.get("columns", []):
                        col_type = col.get("type", "VARCHAR")
                        _, meta = map_snowflake_type_to_databricks(col_type)
                        if meta.get("warning"):
                            warnings.append(
                                f"{db['name']}.{schema['name']}.{table['name']}.{col['name']} ({col_type}): {meta['warning']}"
                            )

                    if table.get("table_type") == "TRANSIENT":
                        warnings.append(
                            f"Tabela {schema['name']}.{table['name']} é TRANSIENT — sem Fail-safe; "
                            f"mapear para Delta table sem Time Travel estendido"
                        )
                    if table.get("clustering_key"):
                        warnings.append(
                            f"Tabela {schema['name']}.{table['name']} usa clustering_key "
                            f"{table['clustering_key']} — avaliar Z-ORDER/liquid clustering no Delta"
                        )

    return {
        "compatibility_status": "COMPATIBLE_WITH_WARNINGS" if warnings else "FULLY_COMPATIBLE",
        "issues_count": len(issues),
        "warnings_count": len(warnings),
        "issues": issues[:10],
        "warnings": warnings[:10],
        "validation_timestamp": datetime.now().isoformat(),
    }


def main():
    """Executa simulação de migração."""

    artifacts_dir = Path("outputs/snowflake-databricks/synthetic_data")
    output_dir = Path("outputs/snowflake-databricks/migration_plan")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("🔄 Simulando migração Snowflake → Databricks...\n")

    print("  ✓ Carregando dados sintéticos")
    source_data = load_synthetic_data(artifacts_dir)

    if not source_data:
        print("❌ Nenhum arquivo de dados sintéticos encontrado. Execute generate_snowflake_synthetic_data.py primeiro.")
        return

    print("  ✓ Validando compatibilidade")
    compat = validate_migration_compatibility(source_data)
    with open(output_dir / "compatibility_report.json", "w") as f:
        json.dump(compat, f, indent=2)

    print("  ✓ Construindo plano de migração")
    plan = build_migration_plan(source_data)
    with open(output_dir / "migration_plan.json", "w") as f:
        json.dump(plan, f, indent=2)

    summary = {
        "migration_id": plan["migration_id"],
        "source": source_data.get("account_metadata", {}).get("account_name", "Unknown"),
        "target": "Databricks (Unity Catalog)",
        "status": compat["compatibility_status"],
        "total_phases": plan["summary"]["total_phases"],
        "total_tasks": plan["summary"]["total_tasks"],
        "warnings": compat["warnings_count"],
        "migration_plan_file": str(output_dir / "migration_plan.json"),
        "compatibility_report_file": str(output_dir / "compatibility_report.json"),
    }

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n✅ Simulação de migração completa!")
    print(f"\n📋 Plano de Migração:")
    print(f"   • Status: {summary['status']}")
    print(f"   • Fases: {summary['total_phases']}")
    print(f"   • Tarefas: {summary['total_tasks']}")
    print(f"   • Avisos: {summary['warnings']}")
    print(f"\n📁 Arquivos salvos em: {output_dir}\n")

    return summary


if __name__ == "__main__":
    main()
