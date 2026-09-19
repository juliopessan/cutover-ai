#!/usr/bin/env python3
"""
Gerador de dados sintéticos estilo Cloudera para teste de migração Fabric.
Simula: tabelas Hive, metadados Hadoop, permissões, linhagem de dados.
"""

import json
import uuid
from datetime import datetime, timedelta
from faker import Faker
from pathlib import Path

fake = Faker()

def generate_cloudera_cluster_metadata() -> dict:
    """Simula metadados de um cluster Cloudera."""
    return {
        "cluster_id": str(uuid.uuid4()),
        "cluster_name": f"cloudera-{fake.domain_word()}",
        "version": "7.1.9",
        "deployed_at": (datetime.now() - timedelta(days=fake.random_int(30, 365))).isoformat(),
        "region": fake.country(),
        "services": {
            "hdfs": {"status": "RUNNING", "namenode": fake.ipv4()},
            "hive": {"status": "RUNNING", "metastore_version": "3.1.2"},
            "impala": {"status": "RUNNING", "coordinators": fake.random_int(2, 5)},
            "hbase": {"status": "RUNNING", "region_servers": fake.random_int(3, 8)},
        },
        "total_nodes": fake.random_int(10, 50),
        "total_storage_gb": fake.random_int(1000, 100000),
    }


def generate_hive_database(db_name: str) -> dict:
    """Simula um banco de dados Hive com tabelas e permissões."""
    tables = []
    num_tables = fake.random_int(3, 12)
    
    for _ in range(num_tables):
        table_name = f"{fake.domain_word()}_{fake.domain_word()}"
        num_cols = fake.random_int(5, 30)
        
        columns = []
        for _ in range(num_cols):
            col_type = fake.random.choice(["STRING", "INT", "BIGINT", "DOUBLE", "BOOLEAN", "TIMESTAMP", "DECIMAL"])
            columns.append({
                "name": fake.word(),
                "type": col_type,
                "comment": fake.sentence(nb_words=5),
                "nullable": fake.boolean(),
            })
        
        tables.append({
            "table_id": str(uuid.uuid4()),
            "name": table_name,
            "location": f"hdfs:///user/hive/warehouse/{db_name}.db/{table_name}",
            "owner": fake.user_name(),
            "created_at": (datetime.now() - timedelta(days=fake.random_int(1, 730))).isoformat(),
            "last_modified": (datetime.now() - timedelta(hours=fake.random_int(1, 720))).isoformat(),
            "row_count": fake.random_int(1000, 10000000),
            "size_gb": fake.random.uniform(0.1, 500),
            "partitions": {
                "type": fake.random.choice(["RANGE", "HASH", None]),
                "columns": [c["name"] for c in fake.random.sample(columns, k=fake.random_int(0, 3))]
            } if fake.boolean(chance_of_getting_true=40) else None,
            "columns": columns,
            "table_format": fake.random.choice(["ORC", "PARQUET", "TEXTFILE"]),
            "compressed": fake.boolean(chance_of_getting_true=70),
        })
    
    return {
        "database_id": str(uuid.uuid4()),
        "name": db_name,
        "description": fake.sentence(),
        "owner": fake.user_name(),
        "created_at": (datetime.now() - timedelta(days=fake.random_int(30, 1000))).isoformat(),
        "tables": tables,
        "permissions": {
            "default_permissions": "GRANT SELECT ON DATABASE",
            "access_control_type": fake.random.choice(["ACL", "RANGER", "SENTRY"]),
        },
    }


def generate_data_lineage() -> dict:
    """Simula linhagem de dados (origem → transformação → destino)."""
    lineage_jobs = []
    
    for _ in range(fake.random_int(10, 25)):
        num_inputs = fake.random_int(1, 5)
        num_outputs = fake.random_int(1, 3)
        
        lineage_jobs.append({
            "job_id": str(uuid.uuid4()),
            "job_name": f"{fake.domain_word()}_etl_{fake.random_int(1, 9999)}",
            "job_type": fake.random.choice(["HIVE_QUERY", "IMPALA_QUERY", "SPARK_JOB", "PIG_JOB"]),
            "owner": fake.user_name(),
            "schedule": fake.random.choice(["HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ON_DEMAND"]),
            "inputs": [
                {
                    "source": fake.random.choice(["HIVE_TABLE", "HDFS_PATH", "HBASE_TABLE", "KAFKA_TOPIC"]),
                    "name": f"{fake.domain_word()}.{fake.domain_word()}",
                    "record_count": fake.random_int(10000, 100000000),
                }
                for _ in range(num_inputs)
            ],
            "outputs": [
                {
                    "target": fake.random.choice(["HIVE_TABLE", "HDFS_PATH", "HBASE_TABLE"]),
                    "name": f"{fake.domain_word()}.{fake.domain_word()}",
                }
                for _ in range(num_outputs)
            ],
            "transformations": [
                {
                    "type": fake.random.choice(["FILTER", "JOIN", "AGGREGATE", "WINDOW", "UDF"]),
                    "description": fake.sentence(),
                }
                for _ in range(fake.random_int(1, 5))
            ],
            "last_run": (datetime.now() - timedelta(hours=fake.random_int(1, 168))).isoformat(),
            "avg_duration_minutes": fake.random_int(5, 480),
            "success_rate": round(fake.random.uniform(0.8, 1.0), 4),
        })
    
    return {
        "lineage_graph": lineage_jobs,
        "discovered_at": datetime.now().isoformat(),
    }


def generate_user_permissions() -> dict:
    """Simula matriz de permissões de usuários e grupos."""
    permissions = []
    
    for _ in range(fake.random_int(20, 50)):
        permissions.append({
            "principal_type": fake.random.choice(["USER", "GROUP", "ROLE"]),
            "principal_name": f"{fake.user_name()}@{fake.domain_name()}",
            "resource_type": fake.random.choice(["DATABASE", "TABLE", "COLUMN", "PATH", "QUEUE"]),
            "resource_name": f"{fake.domain_word()}.{fake.domain_word()}",
            "permissions": fake.random.sample(
                ["SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE", "ADMIN"],
                k=fake.random_int(1, 4)
            ),
            "granted_at": (datetime.now() - timedelta(days=fake.random_int(1, 365))).isoformat(),
            "granted_by": fake.user_name(),
        })
    
    return {
        "total_principals": len(permissions),
        "permissions": permissions,
        "audit_timestamp": datetime.now().isoformat(),
    }


def main():
    """Gera e salva dados sintéticos completos."""
    
    output_dir = Path("outputs/cloudera-fabric/synthetic_data")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🔄 Gerando dados sintéticos Cloudera...\n")
    
    # 1. Cluster
    print("  ✓ Metadados de Cluster")
    cluster = generate_cloudera_cluster_metadata()
    with open(output_dir / "cluster_metadata.json", "w") as f:
        json.dump(cluster, f, indent=2)
    
    # 2. Databases e Tabelas
    print("  ✓ Bancos de dados Hive")
    databases = []
    for i in range(fake.random_int(3, 8)):
        db = generate_hive_database(f"db_{fake.domain_word()}_{i}")
        databases.append(db)
    
    with open(output_dir / "hive_databases.json", "w") as f:
        json.dump({"databases": databases}, f, indent=2)
    
    total_tables = sum(len(db["tables"]) for db in databases)
    print(f"    └─ {total_tables} tabelas criadas")
    
    # 3. Linhagem
    print("  ✓ Linhagem de Dados")
    lineage = generate_data_lineage()
    with open(output_dir / "data_lineage.json", "w") as f:
        json.dump(lineage, f, indent=2)
    
    # 4. Permissões
    print("  ✓ Permissões de Usuários")
    perms = generate_user_permissions()
    with open(output_dir / "user_permissions.json", "w") as f:
        json.dump(perms, f, indent=2)
    
    # 5. Summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "cluster": cluster["cluster_name"],
        "cluster_version": cluster["version"],
        "total_databases": len(databases),
        "total_tables": total_tables,
        "total_lineage_jobs": len(lineage["lineage_graph"]),
        "total_user_permissions": len(perms["permissions"]),
        "artifacts_location": str(output_dir),
    }
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    print("\n✅ Dados sintéticos Cloudera gerados com sucesso!")
    print(f"\n📊 Resumo:")
    print(f"   • Cluster: {summary['cluster']} (v{summary['cluster_version']})")
    print(f"   • Bancos de dados: {summary['total_databases']}")
    print(f"   • Tabelas Hive: {summary['total_tables']}")
    print(f"   • Jobs/Lineage: {summary['total_lineage_jobs']}")
    print(f"   • Permissões: {summary['total_user_permissions']}")
    print(f"\n📁 Arquivos salvos em: {summary['artifacts_location']}\n")
    
    return summary


if __name__ == "__main__":
    main()
