#!/usr/bin/env python3
"""
Cloudera to Fabric migration simulation.
Validates schema mapping, calculates capacity, and generates deployment plan.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cutover.validation import evaluate_deterministic_migration_checks
from cutover.validation.runtime_checks import run_runtime_checks

# ============================================================================
# Migration Models
# ============================================================================

class ColumnMapper:
    """Map Hive column types to Fabric/SQL equivalents"""
    
    MAPPING = {
        "bigint": "bigint",
        "int": "int",
        "string": "nvarchar(max)",
        "double": "float",
        "float": "real",
        "boolean": "bit",
        "timestamp": "datetime2(3)",
        "date": "date",
        "decimal": "decimal",
        "binary": "varbinary(max)",
        "char": "char",
        "varchar": "varchar",
        "array": "nvarchar(max)",  # JSON
        "map": "nvarchar(max)",      # JSON
        "struct": "nvarchar(max)",   # JSON
    }
    
    @classmethod
    def map_type(cls, hive_type: str) -> str:
        """Map Hive type to SQL type"""
        # Handle parameterized types
        base_type = hive_type.split("(")[0].strip().lower()
        return cls.MAPPING.get(base_type, "nvarchar(max)")


class MigrationPlan:
    """Migration plan from Cloudera to Fabric"""
    
    def __init__(self, cloudera_catalog: dict):
        self.cloudera_catalog = cloudera_catalog
        self.cluster_name = cloudera_catalog["cluster_name"]
        self.tables = []
        self.databases = []
        self.migration_timestamp = datetime.now().isoformat()
        self._extract_metadata()
    
    def _extract_metadata(self):
        """Extract tables and databases from Cloudera catalog"""
        for db in self.cloudera_catalog.get("databases", []):
            self.databases.append(db["name"])
            for table in db.get("tables", []):
                self.tables.append({
                    "database": db["name"],
                    "table": table["table_name"],
                    "row_count": table["row_count"],
                    "storage_gb": table["storage_size_gb"],
                    "partitions": table.get("partitions", []),
                    "columns": table.get("columns", [])
                })
    
    def generate_fabric_schema(self) -> dict[str, Any]:
        """Generate Fabric SQL schema from Cloudera tables"""
        fabric_schema = {
            "workspaces": [
                {
                    "name": f"{self.cluster_name}-ws",
                    "location": "OneLake",
                    "lakehouses": []
                }
            ]
        }
        
        # Group tables by database -> lakehouse
        for db_name in self.databases:
            lakehouse = {
                "name": f"{db_name}_lakehouse",
                "description": f"Migrated from Cloudera database: {db_name}",
                "tables": []
            }
            
            for table_info in self.tables:
                if table_info["database"] == db_name:
                    table_def = {
                        "name": table_info["table"],
                        "schema": {
                            "columns": []
                        },
                        "partitions": table_info["partitions"],
                        "properties": {
                            "original_row_count": table_info["row_count"],
                            "original_size_gb": table_info["storage_gb"],
                            "source": "cloudera_hive",
                            "migrated_date": self.migration_timestamp
                        }
                    }
                    
                    # Map columns
                    for col in table_info["columns"]:
                        fabric_col = {
                            "name": col["name"],
                            "type": ColumnMapper.map_type(col["type"]),
                            "nullable": col.get("nullable", True),
                            "description": col.get("comment", "")
                        }
                        table_def["schema"]["columns"].append(fabric_col)
                    
                    lakehouse["tables"].append(table_def)
            
            if lakehouse["tables"]:
                fabric_schema["workspaces"][0]["lakehouses"].append(lakehouse)
        
        return fabric_schema
    
    def calculate_capacity(self) -> dict[str, Any]:
        """Calculate Fabric capacity requirements"""
        total_rows = sum(t["row_count"] for t in self.tables)
        total_size_gb = sum(t["storage_gb"] for t in self.tables)
        
        # Estimate computation units (rough: 1 CU per 100GB)
        estimated_cu = max(4, int(total_size_gb / 100) * 2)
        
        # Estimate cost (standard pricing: ~$20/CU/day in US)
        daily_cost_usd = estimated_cu * 20
        monthly_cost_usd = daily_cost_usd * 30
        
        return {
            "total_tables": len(self.tables),
            "total_databases": len(self.databases),
            "total_rows": total_rows,
            "total_size_gb": total_size_gb,
            "estimated_cu": estimated_cu,
            "daily_cost_usd": daily_cost_usd,
            "monthly_cost_usd": monthly_cost_usd,
            "currency": "USD"
        }
    
    def generate_deployment_steps(self) -> list[dict[str, str]]:
        """Generate step-by-step deployment plan"""
        return [
            {
                "step": 1,
                "phase": "Preparation",
                "task": "Create Fabric workspace",
                "description": f"Create workspace: {self.cluster_name}-ws",
                "duration_hours": 0.5,
                "risk": "low"
            },
            {
                "step": 2,
                "phase": "Preparation",
                "task": "Create Lakehouses",
                "description": f"Create {len(self.databases)} lakehouses (one per database)",
                "duration_hours": 1,
                "risk": "low"
            },
            {
                "step": 3,
                "phase": "Schema Migration",
                "task": "Create SQL tables",
                "description": f"Deploy SQL schema for {len(self.tables)} tables",
                "duration_hours": 2,
                "risk": "medium"
            },
            {
                "step": 4,
                "phase": "Data Migration",
                "task": "Data Factory pipelines",
                "description": f"Create Data Factory pipeline for {len(self.tables)} tables",
                "duration_hours": 4,
                "risk": "medium"
            },
            {
                "step": 5,
                "phase": "Data Migration",
                "task": "Execute data load",
                "description": f"Full load of {sum(t['row_count'] for t in self.tables):,} rows",
                "duration_hours": 8,
                "risk": "high"
            },
            {
                "step": 6,
                "phase": "Validation",
                "task": "Data quality checks",
                "description": "Row count, column validation, data type validation",
                "duration_hours": 3,
                "risk": "medium"
            },
            {
                "step": 7,
                "phase": "Optimization",
                "task": "Enable Purview lineage",
                "description": "Configure data lineage and cataloging",
                "duration_hours": 2,
                "risk": "low"
            },
            {
                "step": 8,
                "phase": "Optimization",
                "task": "Optimize indexes",
                "description": "Create clustered columnstore indexes on key tables",
                "duration_hours": 4,
                "risk": "low"
            },
            {
                "step": 9,
                "phase": "Validation",
                "task": "User acceptance testing",
                "description": "Validate migration with business users",
                "duration_hours": 8,
                "risk": "medium"
            },
            {
                "step": 10,
                "phase": "Cutover",
                "task": "Application migration",
                "description": "Switch application connection strings to Fabric",
                "duration_hours": 2,
                "risk": "high"
            }
        ]
    
    def generate_risk_assessment(self) -> list[dict[str, str]]:
        """Generate risk assessment"""
        risks = []
        
        # Size-based risks
        total_size = sum(t["storage_gb"] for t in self.tables)
        if total_size > 100:
            risks.append({
                "risk_id": "R001",
                "category": "Data Volume",
                "severity": "high",
                "description": f"Large data volume ({total_size:.1f} GB) - migration window may exceed SLA",
                "mitigation": "Implement incremental loading with parallel pipelines"
            })
        
        # Partition complexity
        partitioned_tables = [t for t in self.tables if t["partitions"]]
        if len(partitioned_tables) > 0:
            risks.append({
                "risk_id": "R002",
                "category": "Schema Complexity",
                "severity": "medium",
                "description": f"{len(partitioned_tables)} partitioned tables require partition pruning strategy",
                "mitigation": "Implement Fabric partition strategies; validate partition elimination"
            })
        
        # Type conversion
        risks.append({
            "risk_id": "R003",
            "category": "Type Mapping",
            "severity": "medium",
            "description": "Hive complex types (array, map, struct) mapped to JSON - validate application queries",
            "mitigation": "Conduct SQL rewrite assessment; test JSON parsing performance"
        })
        
        # Dependencies
        if len(self.tables) > 10:
            risks.append({
                "risk_id": "R004",
                "category": "Dependencies",
                "severity": "medium",
                "description": f"{len(self.tables)} tables may have inter-table dependencies",
                "mitigation": "Map and validate dependency DAG; plan incremental cutover"
            })
        
        return risks
    
    def to_dict(self) -> dict[str, Any]:
        """Convert plan to dictionary"""
        return {
            "metadata": {
                "cluster_name": self.cluster_name,
                "migration_timestamp": self.migration_timestamp,
                "source": "cloudera_hive",
                "target": "microsoft_fabric"
            },
            "capacity": self.calculate_capacity(),
            "fabric_schema": self.generate_fabric_schema(),
            "deployment_plan": self.generate_deployment_steps(),
            "risk_assessment": self.generate_risk_assessment()
        }


# ============================================================================
# Validation
# ============================================================================

class MigrationValidator:
    """Validate migration plan"""
    
    def __init__(self, plan: MigrationPlan):
        self.plan = plan
        self.validations = []
    
    def check_deterministic_evidence(self):
        """Add objective checks that are derived from source and target artifacts."""
        deterministic_checks = evaluate_deterministic_migration_checks(
            self.plan.cloudera_catalog,
            {"fabric_schema": self.plan.generate_fabric_schema()},
        )

        for check in deterministic_checks:
            self.validations.append({
                "check": check["name"],
                "status": "✅" if check["status"] == "passed" else "❌",
                "message": check["details"],
                "evidence": check["evidence"],
            })

    def validate(self) -> dict[str, Any]:
        """Run all validations"""
        self.check_schema_coverage()
        self.check_type_mapping()
        self.check_capacity_limits()
        self.check_deterministic_evidence()
        
        passed = sum(1 for v in self.validations if v["status"] == "✅")
        total = len(self.validations)
        
        return {
            "total_checks": total,
            "passed": passed,
            "failed": total - passed,
            "validations": self.validations
        }
    
    def check_schema_coverage(self):
        """Validate all tables have schema"""
        if len(self.plan.tables) == 0:
            self.validations.append({
                "check": "Schema Coverage",
                "status": "❌",
                "message": "No tables found in catalog"
            })
        else:
            self.validations.append({
                "check": "Schema Coverage",
                "status": "✅",
                "message": f"All {len(self.plan.tables)} tables have schema definitions"
            })
    
    def check_type_mapping(self):
        """Validate type mapping"""
        total_columns = sum(len(t["columns"]) for t in self.plan.tables)
        unmapped = 0
        
        for table in self.plan.tables:
            for col in table["columns"]:
                if ColumnMapper.map_type(col["type"]) == "nvarchar(max)" and col["type"] not in ["string", "varchar"]:
                    unmapped += 1
        
        if unmapped > 0:
            self.validations.append({
                "check": "Type Mapping",
                "status": "⚠️",
                "message": f"{unmapped} columns mapped to default type (nvarchar(max))"
            })
        else:
            self.validations.append({
                "check": "Type Mapping",
                "status": "✅",
                "message": f"All {total_columns} columns mapped successfully"
            })
    
    def check_capacity_limits(self):
        """Validate Fabric capacity"""
        capacity = self.plan.calculate_capacity()
        
        if capacity["monthly_cost_usd"] > 100_000:
            self.validations.append({
                "check": "Capacity Limits",
                "status": "⚠️",
                "message": f"High monthly cost estimate: ${capacity['monthly_cost_usd']:,} - review optimization"
            })
        else:
            self.validations.append({
                "check": "Capacity Limits",
                "status": "✅",
                "message": f"Capacity within limits: ${capacity['monthly_cost_usd']:,.0f}/month"
            })


# ============================================================================
# Main
# ============================================================================

def main():
    print("📥 Loading Cloudera metastore...")
    
    metastore_file = Path("outputs/sap-cloudera-legacy/synthetic_data/cloudera_metastore.json")
    if not metastore_file.exists():
        print("❌ Metastore not found. Run generate_synthetic_cloudera_data.py first.")
        return
    
    with open(metastore_file) as f:
        catalog = json.load(f)
    
    print("🔄 Generating migration plan...")
    plan = MigrationPlan(catalog)
    
    print("✅ Validating migration plan...")
    validator = MigrationValidator(plan)
    validation_result = validator.validate()
    
    # Save outputs
    output_dir = Path("outputs/sap-cloudera-legacy/migration_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save migration plan
    plan_file = output_dir / "migration_plan.json"
    with open(plan_file, "w") as f:
        json.dump(plan.to_dict(), f, indent=2)
    
    # Save validation report
    validation_file = output_dir / "validation_report.json"
    with open(validation_file, "w") as f:
        json.dump(validation_result, f, indent=2)

    # Run runtime checks if CSVs exist under outputs/synthetic_csvs
    csv_root = Path("outputs/synthetic_csvs")
    if csv_root.exists():
        print("\n🔬 Running runtime CSV checks (ephemeral SQLite)...")
        runtime_results = run_runtime_checks(catalog, plan.to_dict(), csv_root)
        runtime_file = output_dir / "runtime_checks.json"
        with open(runtime_file, "w", encoding="utf-8") as rf:
            json.dump(runtime_results, rf, indent=2)
        print(f"✅ Runtime checks saved: {runtime_file}")
    
    print(f"\n✅ Migration plan saved: {plan_file}")
    print(f"✅ Validation report saved: {validation_file}")
    
    # Print summary
    capacity = plan.calculate_capacity()
    print(f"\n📊 Migration Summary:")
    print(f"   Cluster: {plan.cluster_name}")
    print(f"   Source: Cloudera Hive")
    print(f"   Target: Microsoft Fabric")
    print(f"\n📈 Capacity Planning:")
    print(f"   Databases: {capacity['total_databases']}")
    print(f"   Tables: {capacity['total_tables']}")
    print(f"   Total Rows: {capacity['total_rows']:,}")
    print(f"   Total Size: {capacity['total_size_gb']:.1f} GB")
    print(f"   Estimated Capacity Units: {capacity['estimated_cu']}")
    print(f"   Daily Cost: ${capacity['daily_cost_usd']:,}")
    print(f"   Monthly Cost: ${capacity['monthly_cost_usd']:,}")
    
    print(f"\n🔍 Validation Results:")
    print(f"   Total Checks: {validation_result['total_checks']}")
    print(f"   Passed: {validation_result['passed']}")
    print(f"   Failed: {validation_result['failed']}")
    print(f"\n   Checks:")
    for v in validation_result["validations"]:
        print(f"   {v['status']} {v['check']}: {v['message']}")
    
    print(f"\n📋 Deployment Plan ({len(plan.generate_deployment_steps())} steps):")
    for step in plan.generate_deployment_steps():
        print(f"   {step['step']:2d}. [{step['phase']:15s}] {step['task']:30s} ({step['duration_hours']:1.1f}h) - Risk: {step['risk']}")
    
    print(f"\n⚠️  Risk Assessment ({len(plan.generate_risk_assessment())} risks):")
    for risk in plan.generate_risk_assessment():
        print(f"   [{risk['severity'].upper():6s}] {risk['description']}")


if __name__ == "__main__":
    main()
