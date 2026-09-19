from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cutover.contracts.intake import MigrationIntake, Readiness, TargetContract
from cutover.core.agent import AgentContext, AgentResult, MigrationAgent


class OnboardingAgent(MigrationAgent):
    name = "onboarding"
    version = "1.0.0"
    capabilities = frozenset({"ask_questions", "validate_readiness", "build_intake"})

    REQUIRED_FIELDS = ("project_name", "source_systems", "targets")

    def next_questions(self, answers: Mapping[str, Any]) -> tuple[str, ...]:
        questions: list[str] = []
        for field in self.REQUIRED_FIELDS:
            if not answers.get(field):
                questions.append(field)
        targets = set(answers.get("targets", ()))
        if "microsoft_fabric" in targets and not answers.get("fabric_storage_mode"):
            questions.append("fabric_storage_mode")
        if "databricks" in targets and answers.get("unity_catalog_enabled") is None:
            questions.append("unity_catalog_enabled")
        if answers.get("contains_sensitive_data") and not answers.get("data_residency"):
            questions.append("data_residency")
        if answers.get("production_data_allowed_for_testing") is False and answers.get("synthetic_data_required") is None:
            questions.append("synthetic_data_required")
        return tuple(questions)

    def build_intake(self, answers: Mapping[str, Any]) -> MigrationIntake:
        targets = tuple(
            TargetContract(
                platform=platform,
                storage_mode=answers.get("fabric_storage_mode") if platform == "microsoft_fabric" else "delta_lake",
                governance_mode="purview" if platform == "microsoft_fabric" else "unity_catalog",
            )
            for platform in answers.get("targets", ())
        )
        missing = self.next_questions(answers)
        readiness = Readiness.BLOCKED if missing else Readiness.NEEDS_REVIEW if answers.get("assumptions") else Readiness.READY
        return MigrationIntake(
            project_name=str(answers.get("project_name", "")),
            source_systems=tuple(answers.get("source_systems", ())),
            targets=targets,
            contains_sensitive_data=bool(answers.get("contains_sensitive_data", False)),
            data_residency=answers.get("data_residency"),
            synthetic_data_required=bool(answers.get("synthetic_data_required", False)),
            assumptions=tuple(answers.get("assumptions", ())),
            readiness=readiness,
        )

    async def execute(self, context: AgentContext, payload: Mapping[str, Any]) -> AgentResult:
        questions = self.next_questions(payload)
        if questions:
            return AgentResult(status="blocked", payload={"next_questions": questions})
        intake = self.build_intake(payload)
        return AgentResult(status=intake.readiness.value, payload={"intake": intake})
