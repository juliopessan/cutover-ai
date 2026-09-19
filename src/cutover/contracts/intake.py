from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Readiness(StrEnum):
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class TargetContract:
    platform: str
    workspace: str | None = None
    storage_mode: str | None = None
    governance_mode: str | None = None
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MigrationIntake:
    project_name: str
    source_systems: tuple[str, ...]
    targets: tuple[TargetContract, ...]
    contains_sensitive_data: bool
    data_residency: str | None
    synthetic_data_required: bool
    assumptions: tuple[str, ...] = ()
    readiness: Readiness = Readiness.BLOCKED
