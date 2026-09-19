from cutover.validation.evidence import evaluate_deterministic_migration_checks


def test_deterministic_validation_emits_objective_checks():
    source_catalog = {
        "databases": [
            {
                "name": "sales",
                "tables": [
                    {
                        "table_name": "orders",
                        "row_count": 120,
                        "storage_size_gb": 3.5,
                        "columns": [
                            {"name": "id", "type": "int", "nullable": False},
                            {"name": "customer_id", "type": "int", "nullable": True},
                        ],
                        "foreign_keys": ["customer_id -> customers.id"],
                    }
                ],
            }
        ]
    }

    target_plan = {
        "fabric_schema": {
            "workspaces": [
                {
                    "lakehouses": [
                        {
                            "name": "sales_lakehouse",
                            "tables": [
                                {
                                    "name": "orders",
                                    "properties": {"original_row_count": 120, "original_size_gb": 3.5},
                                    "schema": {
                                        "columns": [
                                            {"name": "id", "type": "int", "nullable": False},
                                            {"name": "customer_id", "type": "int", "nullable": True},
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    }

    checks = evaluate_deterministic_migration_checks(source_catalog, target_plan)
    names = {check["name"] for check in checks}

    assert "schema_drift_detection" in names
    assert "row_count_reconciliation" in names
    assert "checksum_reconciliation" in names
    assert "null_profile_comparison" in names
    assert "referential_integrity_check" in names
    assert any(check["status"] == "passed" for check in checks)
    # SQL AST validation should be present and pass for well-formed target types
    assert "sql_ast_validation" in names
    assert any(check["name"] == "sql_ast_validation" and check["status"] == "passed" for check in checks)


def test_deterministic_validation_flags_disagreement():
    source_catalog = {
        "databases": [
            {
                "name": "sales",
                "tables": [
                    {
                        "table_name": "orders",
                        "row_count": 120,
                        "storage_size_gb": 3.5,
                        "columns": [{"name": "id", "type": "int", "nullable": False}],
                    }
                ],
            }
        ]
    }

    target_plan = {
        "fabric_schema": {
            "workspaces": [
                {
                    "lakehouses": [
                        {
                            "name": "sales_lakehouse",
                            "tables": [
                                {
                                    "name": "orders",
                                    "properties": {"original_row_count": 999},
                                    "schema": {"columns": [{"name": "id", "type": "int", "nullable": True}]},
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    }

    checks = evaluate_deterministic_migration_checks(source_catalog, target_plan)
    by_name = {check["name"]: check for check in checks}

    assert by_name["row_count_reconciliation"]["status"] == "failed"
    assert by_name["null_profile_comparison"]["status"] == "failed"
