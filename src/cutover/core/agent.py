from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AgentContext:
    run_id: str
    user_id: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentResult:
    status: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MigrationAgent(ABC):
    name: str
    version: str
    capabilities: frozenset[str] = frozenset()

    async def initialize(self, runtime: Any) -> None:
        """Optional lifecycle hook called once when registered."""

    @abstractmethod
    async def execute(
        self,
        context: AgentContext,
        payload: Mapping[str, Any],
    ) -> AgentResult:
        raise NotImplementedError

    async def health_check(self) -> Mapping[str, Any]:
        return {"status": "healthy", "agent": self.name, "version": self.version}
