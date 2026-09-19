# Scripts

Scenario simulators and helpers. **Run everything from the repository root**: the scripts read
`templates/` and write to `outputs/<scenario>/` using paths relative to it (`outputs/` is git-ignored).

Install the extra libraries first: `pip install -e ".[scenarios]"`.

| Folder | Scenario | Entry point |
|---|---|---|
| `scenarios/cloudera_fabric/` | Cloudera to Microsoft Fabric | `run_cloudera_fabric_pipeline.py` |
| `scenarios/snowflake_databricks/` | Snowflake to Databricks | `run_snowflake_databricks_pipeline.py` |
| `scenarios/oracle_databricks/` | Oracle Exadata to Databricks | run the three scripts in order: generate, simulate, report |
| `scenarios/sap_cloudera_legacy/` | SAP and Cloudera legacy estate | `generate_synthetic_*`, then `cloudera_to_fabric_migration.py`, then `generate_comprehensive_report.py` |
| `rtk/` | RTK (token-optimized CLI) installers | see [docs/rtk](../docs/rtk/overview.md) |
| `generate_dashboard.py` | Standalone dashboard from `templates/dashboard.template.html` | |

Each scenario follows the same three steps: synthetic data, migration plan, HTML report. The synthetic data is
generated from schema and statistics only; it never copies production data.
