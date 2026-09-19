#!/usr/bin/env python3
"""Simulate migration from Oracle Exadata to Databricks (Delta Lake / Unity Catalog).

Generates a migration plan and compatibility report under `outputs/oracle-databricks/migration_plan`.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path


def load_synthetic(artifacts_dir: Path) -> dict:
    data = {}
    for fn in ["account_metadata.json", "databases.json", "data_lineage.json", "rbac_grants.json"]:
        p = artifacts_dir / fn
        if p.exists():
            data[fn.replace('.json','')] = json.loads(p.read_text(encoding='utf-8'))
    return data


def map_oracle_type_to_databricks(oracle_type: str) -> tuple[str, dict]:
    mapping = {
        "VARCHAR2": ("STRING", {}),
        "NUMBER": ("DECIMAL", {"precision": 38}),
        "FLOAT": ("DOUBLE", {}),
        "DATE": ("DATE", {}),
        "TIMESTAMP": ("TIMESTAMP", {}),
        "CLOB": ("STRING", {"note": "Large text, consider compression"}),
        "BLOB": ("BINARY", {}),
        "XMLTYPE": ("STRING", {"note": "Store as STRING or external XML store"}),
    }
    return mapping.get(oracle_type, ("STRING", {"warning": "Unknown type, fallback STRING"}))


def build_plan(source_data: dict) -> dict:
    dbs = source_data.get('databases', {}).get('databases', [])
    total_tables = sum(len(s['tables']) for db in dbs for s in db.get('schemas', []))

    plan = {
        'migration_id': str(uuid.uuid4()),
        'source': 'Oracle Exadata',
        'target': 'Databricks (Delta/Unity Catalog)',
        'created_at': datetime.now().isoformat(),
        'tables_to_migrate': total_tables,
        'steps': [
            {'step': 1, 'name': 'Catalogar schemas e tabelas', 'status': 'READY'},
            {'step': 2, 'name': 'Mapear tipos Oracle → Delta', 'status': 'READY'},
            {'step': 3, 'name': 'Provisionar storage e Unity Catalog', 'status': 'PENDING'},
            {'step': 4, 'name': 'Exportar dados (expdp / connectors)', 'status': 'PENDING'},
            {'step': 5, 'name': 'Importar em Delta (COPY INTO / spark)', 'status': 'PENDING'},
            {'step': 6, 'name': 'Validar reconciliação (row counts / checksums)', 'status': 'PENDING'},
        ],
    }

    return plan


def validate_compat(source_data: dict) -> dict:
    warnings = []
    for db in source_data.get('databases', {}).get('databases', []):
        for schema in db.get('schemas', []):
            for table in schema.get('tables', []):
                for col in table.get('columns', []):
                    _, meta = map_oracle_type_to_databricks(col.get('type', 'VARCHAR2'))
                    if meta.get('warning'):
                        warnings.append(f"{db['name']}.{schema['name']}.{table['table_name']}.{col['name']}: {meta['warning']}")

    return {
        'compatibility_status': 'COMPATIBLE_WITH_WARNINGS' if warnings else 'FULLY_COMPATIBLE',
        'warnings': warnings,
        'validation_ts': datetime.now().isoformat(),
    }


def main():
    artifacts = Path('outputs/oracle-databricks/synthetic_data')
    out = Path('outputs/oracle-databricks/migration_plan')
    out.mkdir(parents=True, exist_ok=True)

    print('🔄 Simulating Oracle Exadata → Databricks migration...')
    src = load_synthetic(artifacts)
    if not src:
        print('❌ No synthetic artifacts found. Run generate_oracle_exadata_synthetic_data.py first.')
        return

    compat = validate_compat(src)
    plan = build_plan(src)

    (out / 'compatibility_report.json').write_text(json.dumps(compat, indent=2), encoding='utf-8')
    (out / 'migration_plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')

    print('✅ Simulation complete. Artifacts written to', out)


if __name__ == '__main__':
    main()
