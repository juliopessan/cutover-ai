from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from cutover.core.governed_agent import GovernedAgent


class MappingSuggestionAgent(GovernedAgent):
    """Suggests source-to-target column mappings. Suggestions are never applied automatically."""

    name = "mapping_suggestion"
    version = "1.0.0"
    capabilities = frozenset({"suggest_mappings"})

    def build_prompt(self, payload: Mapping[str, Any]) -> str:
        return (
            "Suggest column mappings as a JSON object {source_column: target_column}.\n"
            f"Target platform: {payload.get('target', 'unknown')}\n"
            f"Source columns: {json.dumps(payload.get('source_columns', []))}\n"
            f"Target columns: {json.dumps(payload.get('target_columns', []))}"
        )

    def interpret(self, content: str) -> Mapping[str, Any]:
        try:
            mappings = json.loads(content)
        except json.JSONDecodeError:
            return {"mappings": {}, "requires_approval": True, "error": "unparseable model output"}
        if not isinstance(mappings, dict):
            return {"mappings": {}, "requires_approval": True, "error": "unexpected model output"}
        return {"mappings": mappings, "requires_approval": True}
