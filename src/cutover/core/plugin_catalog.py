from __future__ import annotations

from .agent import MigrationAgent


class PluginCatalog:
    def __init__(self) -> None:
        self._items: dict[str, MigrationAgent] = {}

    def add(self, agent: MigrationAgent) -> None:
        if agent.name in self._items:
            raise ValueError("duplicate agent")
        self._items[agent.name] = agent

    def find(self, name: str) -> MigrationAgent:
        return self._items[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))
