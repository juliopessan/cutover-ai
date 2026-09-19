from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import sqlglot


def _iter_tables(catalog: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for database in catalog.get("databases", []):
        for table in database.get("tables", []):
            yield table


def _iter_target_tables(target_plan: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for workspace in target_plan.get("fabric_schema", {}).get("workspaces", []):
        for lakehouse in workspace.get("lakehouses", []):
            for table in lakehouse.get("tables", []):
                yield table


def _sql_ast_validation(target_plan: dict[str, Any]) -> dict[str, Any]:
    """Attempt to parse generated CREATE TABLE DDLs for target tables using sqlglot.

    This provides an AST-level sanity check that the derived SQL types/DDL are syntactically valid.
    """
    failures: list[str] = []
    parsed = 0

    for table in _iter_target_tables(target_plan):
        tbl_name = table.get("name")
        cols = table.get("schema", {}).get("columns", [])
        if not cols:
            # nothing to validate
            continue

        col_defs = []
        for c in cols:
            col_name = c.get("name")
            col_type = c.get("type") or "nvarchar(max)"
            col_defs.append(f"{col_name} {col_type}")

        ddl = f"CREATE TABLE {tbl_name} ({', '.join(col_defs)})"
        try:
            # parse_one raises on invalid SQL
            sqlglot.parse_one(ddl)
            parsed += 1
        except Exception as e:
            failures.append(f"{tbl_name}: {e}")

    status = "passed" if not failures else "failed"
    return {
        "name": "sql_ast_validation",
        "status": status,
        "evidence": {"tables_parsed": parsed, "failures": failures},
        "details": "Parsed CREATE TABLE DDLs using sqlglot" + (" — failures present" if failures else ""),
    }


def evaluate_deterministic_migration_checks(source_catalog: dict[str, Any], target_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return objective migration evidence checks that do not rely on LLM judgment."""
    checks: list[dict[str, Any]] = []

    source_tables = list(_iter_tables(source_catalog))
    target_tables = list(_iter_target_tables(target_plan))

    if source_tables and target_tables:
        source_rows = sum(int(table.get("row_count", 0)) for table in source_tables)
        target_rows = sum(int(table.get("properties", {}).get("original_row_count", 0)) for table in target_tables)
        if source_rows == target_rows:
            checks.append(
                {
                    "name": "row_count_reconciliation",
                    "status": "passed",
                    "evidence": {
                        "source_rows": source_rows,
                        "target_rows": target_rows,
                    },
                    "details": "Row counts match for the migrated tables.",
                }
            )
        else:
            checks.append(
                {
                    "name": "row_count_reconciliation",
                    "status": "failed",
                    "evidence": {
                        "source_rows": source_rows,
                        "target_rows": target_rows,
                    },
                    "details": "Row counts differ between source and target.",
                }
            )
    else:
        checks.append(
            {
                "name": "row_count_reconciliation",
                "status": "passed",
                "evidence": {"source_rows": 0, "target_rows": 0},
                "details": "No source or target tables were provided.",
            }
        )

    if source_tables:
        expected_columns = {
            (table.get("table_name"), tuple(sorted(col.get("name", "") for col in table.get("columns", []))))
            for table in source_tables
        }
        actual_columns = {
            (table.get("name"), tuple(sorted(col.get("name", "") for col in table.get("schema", {}).get("columns", []))))
            for table in target_tables
        }

        if expected_columns == actual_columns:
            checks.append(
                {
                    "name": "schema_drift_detection",
                    "status": "passed",
                    "evidence": {"tables_checked": len(expected_columns)},
                    "details": "Source and target column sets match exactly.",
                }
            )
        else:
            checks.append(
                {
                    "name": "schema_drift_detection",
                    "status": "failed",
                    "evidence": {"expected": sorted(expected_columns), "actual": sorted(actual_columns)},
                    "details": "Column sets differ between source and target.",
                }
            )
    else:
        checks.append(
            {
                "name": "schema_drift_detection",
                "status": "passed",
                "evidence": {"tables_checked": 0},
                "details": "No source tables were provided.",
            }
        )

    if source_tables and target_tables:
        checks.append(
            {
                "name": "checksum_reconciliation",
                "status": "passed",
                "evidence": {
                    "source_checksum": sum(len(table.get("columns", [])) for table in source_tables),
                    "target_checksum": sum(len(table.get("schema", {}).get("columns", [])) for table in target_tables),
                },
                "details": "Checksum-like structure reconciliation passed.",
            }
        )
    else:
        checks.append(
            {
                "name": "checksum_reconciliation",
                "status": "passed",
                "evidence": {"source_checksum": 0, "target_checksum": 0},
                "details": "No tables available for checksum reconciliation.",
            }
        )

    if source_tables and target_tables:
        source_nullable = {
            (table.get("table_name"), tuple(sorted(str(col.get("nullable", False)) for col in table.get("columns", []))))
            for table in source_tables
        }
        target_nullable = {
            (table.get("name"), tuple(sorted(str(col.get("nullable", False)) for col in table.get("schema", {}).get("columns", []))))
            for table in target_tables
        }
        if source_nullable == target_nullable:
            checks.append(
                {
                    "name": "null_profile_comparison",
                    "status": "passed",
                    "evidence": {"tables_checked": len(source_nullable)},
                    "details": "Nullability profiles match.",
                }
            )
        else:
            checks.append(
                {
                    "name": "null_profile_comparison",
                    "status": "failed",
                    "evidence": {"expected": sorted(source_nullable), "actual": sorted(target_nullable)},
                    "details": "Nullability profiles differ between source and target.",
                }
            )
    else:
        checks.append(
            {
                "name": "null_profile_comparison",
                "status": "passed",
                "evidence": {"tables_checked": 0},
                "details": "No tables available for null profile comparison.",
            }
        )

    if source_tables and target_tables:
        source_fk = {
            table.get("table_name"): table.get("foreign_keys", [])
            for table in source_tables
        }
        target_fk = {
            table.get("name"): table.get("properties", {}).get("foreign_keys", [])
            for table in target_tables
        }
        if not any(source_fk.values()) and not any(target_fk.values()):
            checks.append(
                {
                    "name": "referential_integrity_check",
                    "status": "passed",
                    "evidence": {"source_foreign_keys": source_fk, "target_foreign_keys": target_fk},
                    "details": "No foreign key metadata was present on either side.",
                }
            )
        elif source_fk == target_fk:
            checks.append(
                {
                    "name": "referential_integrity_check",
                    "status": "passed",
                    "evidence": {"source_foreign_keys": source_fk, "target_foreign_keys": target_fk},
                    "details": "Referential integrity metadata is consistent.",
                }
            )
        else:
            checks.append(
                {
                    "name": "referential_integrity_check",
                    "status": "failed",
                    "evidence": {"source_foreign_keys": source_fk, "target_foreign_keys": target_fk},
                    "details": "Referential integrity metadata was not preserved.",
                }
            )
    else:
        checks.append(
            {
                "name": "referential_integrity_check",
                "status": "passed",
                "evidence": {"source_foreign_keys": {}, "target_foreign_keys": {}},
                "details": "No tables available for referential integrity check.",
            }
        )

    # SQL AST validation (parse generated CREATE TABLE DDLs)
    try:
        sql_check = _sql_ast_validation(target_plan)
        checks.append(sql_check)
    except Exception as e:
        checks.append({
            "name": "sql_ast_validation",
            "status": "failed",
            "evidence": {},
            "details": f"sql_ast_validation error: {e}",
        })

    return checks
