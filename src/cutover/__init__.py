"""Extensible SDK for migration agents and target plugins."""

from .core.agent import AgentContext, AgentResult, MigrationAgent
from .core.registry import PluginRegistry
from .core.runtime import AgentRuntime

__all__ = [
    "AgentContext",
    "AgentResult",
    "AgentRuntime",
    "MigrationAgent",
    "PluginRegistry",
]
