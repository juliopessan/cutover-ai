#!/usr/bin/env python3
"""
Simulador de migração Cloudera → Microsoft Fabric.
Transforma metadados, gera plano de migração, valida compatibilidade.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def load_synthetic_data(artifacts_dir: Path) -> dict:
    """Carrega dados sintéticos gerados."""
    data = {}
    
    for json_file in ["cluster_metadata.json", "hive_databases.json", "data_lineage.json", "user_permissions.json"]:
        path = artifacts_dir / json_file
        if path.exists():
            with open(path) as f:
                data[json_file.replace(".json", "")] = json.load(f)
    
    return data


def map_hive_type_to_fabric(hive_type: str) -> tuple[str, dict]:
    """Mapeia tipos Hive para tipos Fabric/Spark SQL."""
    type_mapping = {
        "STRING": ("STRING", {}),
        "INT": ("INT", {}),
        "BIGINT": ("LONG", {}),
        "DOUBLE": ("DOUBLE", {}),
        "BOOLEAN": ("BOOLEAN", {}),
        "TIMESTAMP": ("TIMESTAMP", {}),
        "DECIMAL": ("DECIMAL", {"precision": 18, "scale": 4}),
        "DATE": ("DATE", {}),
        "ARRAY": ("ARRAY", {"element_type": "STRING"}),
        "MAP": ("MAP", {"key_type": "STRING", "value_type": "STRING"}),
        "STRUCT": ("STRUCT", {"fields": []}),
    }
    return type_mapping.get(hive_type, ("STRING", {}))


def build_migration_plan(source_data: dict) -> dict:
    """Constrói plano de migração com fases e tarefas."""
    
    if "hive_databases" not in source_data:
        return {"phase_0": "No data available"}
    
    hive_data = source_data["hive_databases"]
    databases = hive_data.get("databases", [])
    
    total_tables = sum(len(db["tables"]) for db in databases)
    total_size_gb = sum(
        sum(t["size_gb"] for t in db["tables"])
        for db in databases
    )
    
    migration_phases = {
        "phase_0_readiness": {
            "title": "Avaliação de Prontidão",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Validar compatibilidade de tipos de dados",
                    "status": "READY",
                    "compatibility_issues": 0,
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Analisar permissões e segurança",
                    "status": "READY",
                    "security_policies": len(source_data.get("user_permissions", {}).get("permissions", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Estimar tempo e custo de migração",
                    "status": "READY",
                    "estimated_duration_hours": int(total_size_gb / 100) + 2,  # ~100 GB/hora
                    "estimated_cost_usd": round(total_size_gb * 0.05, 2),  # ~$0.05/GB
                },
            ],
        },
        "phase_1_assessment": {
            "title": "Descoberta e Mapeamento",
            "databases_count": len(databases),
            "tables_count": total_tables,
            "total_data_volume_gb": round(total_size_gb, 2),
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Catalogar metadados Hive",
                    "status": "IN_PROGRESS",
                    "records_extracted": total_tables,
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Mapear tipos de dados Hive → Spark SQL",
                    "status": "IN_PROGRESS",
                    "type_mappings": len([c for db in databases for t in db["tables"] for c in t["columns"]]),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Analisar linhagem de dados",
                    "status": "IN_PROGRESS",
                    "lineage_jobs": len(source_data.get("lineage_graph", [])) if isinstance(source_data.get("data_lineage"), dict) else 0,
                },
            ],
        },
        "phase_2_infrastructure": {
            "title": "Provisionamento Fabric",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Criar workspace Fabric",
                    "status": "PENDING",
                    "workspace_config": {
                        "region": "eastus2",
                        "sku": "F2",
                        "capacity_units": 2,
                    },
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Provisionar Lakehouses",
                    "status": "PENDING",
                    "lakehouses": len(databases),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Configurar Data Factory pipelines",
                    "status": "PENDING",
                    "pipelines": len(source_data.get("data_lineage", {}).get("lineage_graph", [])),
                },
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Habilitar lineage tracking com Purview",
                    "status": "PENDING",
                    "purview_integration": True,
                },
            ],
        },
        "phase_3_data_migration": {
            "title": "Migração de Dados",
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": "Executar migração full-load",
                    "status": "PENDING",
                    "tables_to_migrate": total_tables,
                    "incremental_strategy": "MERGE",
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
                    "name": "Ativar aplicações em Fabric",
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
        "source_platform": "Cloudera",
        "target_platform": "Microsoft Fabric",
        "created_at": datetime.now().isoformat(),
        "phases": migration_phases,
        "summary": {
            "total_phases": len(migration_phases),
            "total_tasks": sum(len(p.get("tasks", [])) for p in migration_phases.values()),
            "estimated_effort_weeks": 6,
            "go_live_date": "2026-09-15",
        },
    }


def validate_migration_compatibility(source_data: dict) -> dict:
    """Valida compatibilidade da migração."""
    
    issues = []
    warnings = []
    
    if "hive_databases" in source_data:
        for db in source_data["hive_databases"].get("databases", []):
            for table in db.get("tables", []):
                for col in table.get("columns", []):
                    col_type = col.get("type", "STRING")
                    if col_type not in ["STRING", "INT", "BIGINT", "DOUBLE", "BOOLEAN", "TIMESTAMP", "DECIMAL"]:
                        warnings.append(f"Tipo não suportado em Spark SQL: {col_type} (coluna {col['name']})")
                
                if table.get("table_format") == "TEXTFILE":
                    warnings.append(f"Tabela {table['name']} em formato TEXT — converter para PARQUET é recomendado")
    
    return {
        "compatibility_status": "COMPATIBLE_WITH_WARNINGS" if warnings else "FULLY_COMPATIBLE",
        "issues_count": len(issues),
        "warnings_count": len(warnings),
        "issues": issues[:10],  # Top 10
        "warnings": warnings[:10],
        "validation_timestamp": datetime.now().isoformat(),
    }


def main():
    """Executa simulação de migração."""
    
    artifacts_dir = Path("outputs/cloudera-fabric/synthetic_data")
    output_dir = Path("outputs/cloudera-fabric/migration_plan")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🔄 Simulando migração Cloudera → Fabric...\n")
    
    # Carregar dados
    print("  ✓ Carregando dados sintéticos")
    source_data = load_synthetic_data(artifacts_dir)
    
    if not source_data:
        print("❌ Nenhum arquivo de dados sintéticos encontrado. Execute generate_cloudera_synthetic_data.py primeiro.")
        return
    
    # Validar compatibilidade
    print("  ✓ Validando compatibilidade")
    compat = validate_migration_compatibility(source_data)
    with open(output_dir / "compatibility_report.json", "w") as f:
        json.dump(compat, f, indent=2)
    
    # Construir plano de migração
    print("  ✓ Construindo plano de migração")
    plan = build_migration_plan(source_data)
    with open(output_dir / "migration_plan.json", "w") as f:
        json.dump(plan, f, indent=2)
    
    # Gerar summary
    summary = {
        "migration_id": plan["migration_id"],
        "source": source_data.get("cluster_metadata", {}).get("cluster_name", "Unknown"),
        "target": "Microsoft Fabric",
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
