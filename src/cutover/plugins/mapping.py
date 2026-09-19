from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cutover.core.governed_agent import GovernedAgent

DELTA_TYPES = ("string", "int", "bigint", "double", "decimal", "boolean", "date", "timestamp")
TARGET_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def extract_json(content: str) -> Any:
    """Parse the model's JSON, tolerating code fences and surrounding prose."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _target_of(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("target"), str):
        return str(entry["target"])
    return None


def check_mapping(source_columns: Sequence[str], mappings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Deterministic checks over a suggested mapping. None of them asks a model anything."""
    sources = list(source_columns)
    targets = {name: _target_of(mappings.get(name)) for name in sources}
    missing = [n for n in sources if targets[n] is None]
    extra = [k for k in mappings if k not in sources]
    bad_names = [f"{n} → {t}" for n, t in targets.items() if t is not None and not TARGET_NAME.match(t)]
    seen: dict[str, list[str]] = {}
    for name, target in targets.items():
        if target is not None:
            seen.setdefault(target, []).append(name)
    collisions = [f"{', '.join(v)} → {k}" for k, v in seen.items() if len(v) > 1]
    bad_types = [
        f"{n}: {mappings[n].get('type')!r}" for n in sources
        if isinstance(mappings.get(n), dict) and mappings[n].get("type") not in DELTA_TYPES
    ]

    def check(name: str, offenders: list[str], ok: str, fail: str) -> dict[str, Any]:
        return {"name": name, "status": "failed" if offenders else "passed",
                "details": fail if offenders else ok, "offenders": offenders}

    return [
        check("covers_all_columns", missing, "Toda coluna de origem tem destino.", "Colunas de origem sem destino."),
        check("no_unknown_columns", extra, "Nenhuma coluna inventada.", "O modelo mapeou colunas que não existem."),
        check("delta_safe_names", bad_names, "Todos os nomes de destino são seguros para Delta.", "Nomes de destino fora de [a-z_][a-z0-9_]*."),
        check("unique_targets", collisions, "Nenhum destino repetido.", "Várias colunas apontam para o mesmo destino."),
        check("valid_types", bad_types, "Todos os tipos são suportados.", f"Tipos fora de {', '.join(DELTA_TYPES)}."),
    ]


class MappingSuggestionAgent(GovernedAgent):
    """Suggests source-to-target column mappings. Suggestions are never applied automatically."""

    name = "mapping_suggestion"
    version = "1.1.0"
    capabilities = frozenset({"suggest_mappings"})

    def build_prompt(self, payload: Mapping[str, Any]) -> str:
        target = payload.get("target", "unknown")
        target_columns = payload.get("target_columns")
        if target_columns:
            return (
                "Suggest column mappings as a JSON object {source_column: target_column}.\n"
                f"Target platform: {target}\n"
                f"Source columns: {json.dumps(payload.get('source_columns', []))}\n"
                f"Target columns: {json.dumps(target_columns)}"
            )
        return (
            f"You map source columns to Delta Lake columns for {target}. Reply with ONLY a JSON object of the form "
            '{"<source column>": {"target": "<snake_case name>", "type": "<type>"}}. '
            f"Allowed types: {', '.join(DELTA_TYPES)}. Every source column must appear exactly once. "
            "Target names use only lowercase letters, digits and underscores, and must be unique.\n"
            "Source columns as [name, inferred type]: "
            + json.dumps([[c["name"], c["type"]] if isinstance(c, dict) else [c, "unknown"]
                          for c in payload.get("source_columns", [])], ensure_ascii=False)
        )

    def interpret(self, content: str) -> Mapping[str, Any]:
        try:
            mappings = extract_json(content)
        except ValueError:  # includes json.JSONDecodeError
            return {"mappings": {}, "requires_approval": True, "error": "unparseable model output"}
        if not isinstance(mappings, dict):
            return {"mappings": {}, "requires_approval": True, "error": "unexpected model output"}
        return {"mappings": mappings, "requires_approval": True}
