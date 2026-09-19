from cutover.contracts.intake import Readiness
from cutover.plugins.onboarding import OnboardingAgent
from cutover.targets.databricks import DatabricksTargetAdapter
from cutover.targets.fabric import FabricTargetAdapter


def test_onboarding_blocks_missing_target():
    agent = OnboardingAgent()
    questions = agent.next_questions({"project_name": "demo", "source_systems": ["snowflake"]})
    assert "targets" in questions


def test_sensitive_data_without_residency_is_blocked():
    answers = {
        "project_name": "regulated-migration",
        "source_systems": ["oracle"],
        "targets": ["microsoft_fabric"],
        "fabric_storage_mode": "lakehouse",
        "contains_sensitive_data": True,
        "production_data_allowed_for_testing": False,
        "synthetic_data_required": True,
    }
    intake = OnboardingAgent().build_intake(answers)
    assert intake.readiness is Readiness.BLOCKED
    assert "data_residency" in OnboardingAgent().next_questions(answers)


def test_dual_target_intake_is_ready():
    answers = {
        "project_name": "enterprise-migration",
        "source_systems": ["snowflake", "oracle"],
        "targets": ["microsoft_fabric", "databricks"],
        "fabric_storage_mode": "lakehouse",
        "unity_catalog_enabled": True,
        "contains_sensitive_data": True,
        "data_residency": "brazil-south",
        "production_data_allowed_for_testing": False,
        "synthetic_data_required": True,
    }
    intake = OnboardingAgent().build_intake(answers)
    assert intake.readiness is Readiness.READY
    assert len(intake.targets) == 2
    assert FabricTargetAdapter().deployment_plan(intake.targets[0])
    assert DatabricksTargetAdapter().deployment_plan(intake.targets[1])


def test_assumptions_require_review():
    answers = {
        "project_name": "review",
        "source_systems": ["teradata"],
        "targets": ["databricks"],
        "unity_catalog_enabled": True,
        "contains_sensitive_data": False,
        "production_data_allowed_for_testing": True,
        "synthetic_data_required": False,
        "assumptions": ["CDC mechanism pending confirmation"],
    }
    assert OnboardingAgent().build_intake(answers).readiness is Readiness.NEEDS_REVIEW
