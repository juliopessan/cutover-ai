from cutover.contracts.intake import MigrationIntake, TargetContract
from cutover.targets.base import TargetAdapter


class DatabricksTargetAdapter(TargetAdapter):
    platform = "databricks"

    def build_contract(self, intake: MigrationIntake) -> TargetContract:
        for target in intake.targets:
            if target.platform == self.platform:
                return target
        raise ValueError("Databricks target not found in intake")

    def deployment_plan(self, contract: TargetContract) -> tuple[str, ...]:
        return (
            "validate_workspace_and_network",
            "configure_unity_catalog",
            "provision_external_locations",
            "create_delta_lake_catalogs_and_schemas",
            "deploy_lakeflow_jobs_and_pipelines",
            "deploy_notebooks_and_sql_assets",
            "configure_lineage_and_access_policies",
            "run_reconciliation_suite",
        )
