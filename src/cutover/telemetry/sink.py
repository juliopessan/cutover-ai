from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from threading import Lock

from .events import TelemetryEvent


class TelemetrySink(ABC):
    @abstractmethod
    def emit(self, event: TelemetryEvent) -> None:
        """Persist or export one telemetry event."""


class NullTelemetrySink(TelemetrySink):
    def emit(self, event: TelemetryEvent) -> None:
        return None


class InMemoryTelemetrySink(TelemetrySink):
    """Thread-safe sink for tests, local runs and embedded dashboards."""

    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []
        self._lock = Lock()

    def emit(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self) -> tuple[TelemetryEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def totals_by_agent(self) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
        )
        for event in self.events():
            usage = event.usage
            if usage:
                totals[event.agent_name]["input_tokens"] += usage.input_tokens
                totals[event.agent_name]["output_tokens"] += usage.output_tokens
            if event.cost:
                totals[event.agent_name]["cost"] += event.cost.total_cost
        return dict(totals)
