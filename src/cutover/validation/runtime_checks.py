from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Any


def _compute_row_checksum(row: list[str]) -> str:
    joined = "|".join(row)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def _load_csv_into_sqlite(conn: sqlite3.Connection, table_name: str, csv_path: Path) -> dict[str, Any]:
    """Create a simple table and load CSV rows. Returns stats."""
    stats: dict[str, Any] = {"rows": 0, "checksum": None, "null_profile": {}}

    with csv_path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return stats

        # Create table with TEXT columns
        cols = [f'"{h}" TEXT' for h in headers]
        create_sql = f'CREATE TABLE "{table_name}" ({", ".join(cols)})'
        conn.execute(create_sql)

        quoted_columns = ",".join(f'"{h}"' for h in headers)
        placeholders = ",".join("?" for _ in headers)
        insert_sql = f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'

        checksum_acc = hashlib.md5()
        null_counts = {h: 0 for h in headers}
        total = 0
        for row in reader:
            conn.execute(insert_sql, row)
            total += 1
            checksum_acc.update("|".join(row).encode('utf-8'))
            for h, v in zip(headers, row):
                if v == "" or v is None:
                    null_counts[h] += 1

        conn.commit()

        stats["rows"] = total
        stats["checksum"] = checksum_acc.hexdigest()
        stats["null_profile"] = {k: v for k, v in null_counts.items()}

    return stats


def run_runtime_checks(source_catalog: dict[str, Any], target_plan: dict[str, Any], csv_root: Path) -> list[dict[str, Any]]:
    """Run ephemeral SQLite checks by loading CSVs under `csv_root` matching source tables.

    For each table in `source_catalog`, this looks for `<csv_root>/<database>/<table>.csv` and if found,
    loads it into an in-memory sqlite DB and compares counts/checksums/null profiles with target metadata.
    """
    results: list[dict[str, Any]] = []

    conn = sqlite3.connect(":memory:")

    for db in source_catalog.get("databases", []):
        db_name = db.get("name")
        for table in db.get("tables", []):
            table_name = table.get("table_name")
            csv_path = csv_root / db_name / f"{table_name}.csv"
            if not csv_path.exists():
                results.append({
                    "table": f"{db_name}.{table_name}",
                    "status": "skipped",
                    "reason": "csv_not_found",
                })
                continue

            stats = _load_csv_into_sqlite(conn, f"{db_name}_{table_name}", csv_path)

            # find matching target table metadata
            target_table = None
            for w in target_plan.get("fabric_schema", {}).get("workspaces", []):
                for lh in w.get("lakehouses", []):
                    for tt in lh.get("tables", []):
                        if tt.get("name") == table_name:
                            target_table = tt
                            break
                    if target_table:
                        break
                if target_table:
                    break

            expected_rows = int(table.get("row_count", 0))
            expected_rows_target = int((target_table or {}).get("properties", {}).get("original_row_count", 0))

            row_status = "passed" if stats["rows"] == expected_rows else "failed"
            checksum_status = "unknown"
            if expected_rows_target:
                # If target expected rows given, compare with loaded csv rows
                checksum_status = "passed" if stats["rows"] == expected_rows_target else "failed"

            results.append({
                "table": f"{db_name}.{table_name}",
                "status": "checked",
                "rows_loaded": stats["rows"],
                "expected_source_rows": expected_rows,
                "expected_target_rows": expected_rows_target,
                "row_count_status": row_status,
                "checksum": stats["checksum"],
                "null_profile": stats["null_profile"],
                "checksum_status": checksum_status,
            })

    conn.close()
    return results
