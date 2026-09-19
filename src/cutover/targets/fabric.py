from cutover.contracts.intake import MigrationIntake, TargetContract
from cutover.targets.base import TargetAdapter


class FabricTargetAdapter(TargetAdapter):
    platform = "microsoft_fabric"

    def build_contract(self, intake: MigrationIntake) -> TargetContract:
        for target in intake.targets:
            if target.platform == self.platform:
                return target
        raise ValueError("Fabric target not found in intake")

    def deployment_plan(self, contract: TargetContract) -> tuple[str, ...]:
        return (
            "validate_capacity_and_workspace",
            "provision_onelake_landing_zone",
            f"create_{contract.storage_mode or 'lakehouse'}",
            "deploy_data_factory_pipelines",
            "deploy_notebooks_and_sql_assets",
            "configure_purview_and_lineage",
            "run_reconciliation_suite",
        )
