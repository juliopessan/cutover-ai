from __future__ import annotations

import json
import re
import unicodedata
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


INT32_MAX = 2_147_483_647
NUMERIC_TARGETS = {"int", "bigint", "double", "decimal"}


def type_conflict(profile: Mapping[str, Any], suggested: str | None) -> str | None:
    """Why ``suggested`` cannot safely hold the data the profile measured, or None when it can."""
    kind = profile.get("type")
    if suggested in NUMERIC_TARGETS and kind not in ("integer", "decimal"):
        return f"a coluna é {kind}, não numérica"
    if suggested in ("int", "bigint") and kind == "decimal":
        return "há casas decimais que seriam perdidas"
    if suggested == "int":
        try:
            if max(abs(float(profile.get("min") or 0)), abs(float(profile.get("max") or 0))) > INT32_MAX:
                return f"valores até {profile.get('max')} não cabem em int (use bigint)"
        except ValueError:
            return None
    if suggested == "boolean" and kind != "boolean":
        return f"a coluna é {kind}, não booleana"
    if suggested in ("date", "timestamp") and kind in ("integer", "decimal", "boolean", "mixed"):
        return f"a coluna é {kind}, não uma data"
    return None


def check_mapping(
    source_columns: Sequence[str],
    mappings: Mapping[str, Any],
    profile_columns: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic checks over a suggested mapping. None of them asks a model anything.

    With ``profile_columns`` (name to measured column profile) it also checks that each suggested type can
    hold the data that was measured.
    """
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

    checks = [
        check("covers_all_columns", missing, "Toda coluna de origem tem destino.", "Colunas de origem sem destino."),
        check("no_unknown_columns", extra, "Nenhuma coluna inventada.", "O modelo mapeou colunas que não existem."),
        check("delta_safe_names", bad_names, "Todos os nomes de destino são seguros para Delta.", "Nomes de destino fora de [a-z_][a-z0-9_]*."),
        check("unique_targets", collisions, "Nenhum destino repetido.", "Várias colunas apontam para o mesmo destino."),
        check("valid_types", bad_types, "Todos os tipos são suportados.", f"Tipos fora de {', '.join(DELTA_TYPES)}."),
    ]
    if profile_columns is not None:
        conflicts = []
        for name in sources:
            entry = mappings.get(name)
            suggested = entry.get("type") if isinstance(entry, dict) else None
            reason = type_conflict(profile_columns.get(name, {}), suggested) if suggested else None
            if reason:
                conflicts.append(f"{name}: {suggested}, {reason}")
        checks.append(check("type_fits_data", conflicts, "Todo tipo sugerido comporta os dados medidos.",
                            "Tipo sugerido não comporta os dados medidos."))
    return checks


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


# ---- deterministic corrections -----------------------------------------------------------------

def snake_case(name: str) -> str:
    """A Delta-safe lowercase name from any column name: accents dropped, symbols to underscores."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", ascii_name).strip("_").lower() or "coluna"
    return (("c_" + cleaned) if cleaned[0].isdigit() else cleaned)[:128]


def infer_type(profile: Mapping[str, Any]) -> str:
    """The safest Delta type for what the profile measured."""
    kind = profile.get("type")
    if kind == "integer":
        try:
            wide = max(abs(float(profile.get("min") or 0)), abs(float(profile.get("max") or 0))) > INT32_MAX
        except ValueError:
            wide = True
        return "bigint" if wide else "int"
    return {"decimal": "decimal", "date": "date", "boolean": "boolean"}.get(str(kind), "string")


def safe_type(profile: Mapping[str, Any], suggested: str) -> str:
    """A type that holds the measured data, keeping the model's intent where it can."""
    kind = profile.get("type")
    if suggested in ("int", "bigint") and kind == "integer":
        return "bigint"
    if suggested in ("int", "bigint", "double") and kind == "decimal":
        return "decimal"
    return "string" if suggested in NUMERIC_TARGETS | {"boolean", "date", "timestamp"} else infer_type(profile)


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name}_{n}", n + 1
    return candidate


def correct_mapping(
    profile_columns: Sequence[Mapping[str, Any]], mappings: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fix everything a rule can fix, and say why. Returns ``(corrected mappings, changes)``.

    It never guesses beyond the measured profile: a type is only changed to one the data provably fits, and
    a name only to its snake_case form. Anything else is left for a person.
    """
    changes: list[dict[str, Any]] = []
    known = [c["name"] for c in profile_columns]
    for extra in (k for k in mappings if k not in known):
        changes.append({"column": extra, "field": "coluna", "from": "mapeada", "to": None, "reason": "A coluna não existe no arquivo."})
    corrected: dict[str, Any] = {}
    taken: set[str] = set()
    for column in profile_columns:
        name = column["name"]
        entry = mappings.get(name)
        target = entry if isinstance(entry, str) else (entry or {}).get("target") if isinstance(entry, dict) else None
        kind = (entry or {}).get("type") if isinstance(entry, dict) else None
        if target is None:
            fresh = _unique(snake_case(name), taken)
            changes.append({"column": name, "field": "destino", "from": None, "to": fresh, "reason": "A coluna não tinha destino no mapeamento."})
            target = fresh
        elif not TARGET_NAME.match(str(target)):
            fixed = _unique(snake_case(str(target)), taken)
            changes.append({"column": name, "field": "destino", "from": target, "to": fixed, "reason": "Nome fora de [a-z_][a-z0-9_]*."})
            target = fixed
        elif target in taken:
            fixed = _unique(str(target), taken)
            changes.append({"column": name, "field": "destino", "from": target, "to": fixed, "reason": "Destino repetido."})
            target = fixed
        taken.add(str(target))
        if kind not in DELTA_TYPES:
            fixed_type = infer_type(column)
            changes.append({"column": name, "field": "tipo", "from": kind, "to": fixed_type, "reason": "Tipo ausente ou não suportado; inferido do perfil."})
            kind = fixed_type
        conflict = type_conflict(column, str(kind))
        if conflict:
            fixed_type = safe_type(column, str(kind))
            changes.append({"column": name, "field": "tipo", "from": kind, "to": fixed_type, "reason": conflict[0].upper() + conflict[1:] + "."})
            kind = fixed_type
        corrected[name] = {"target": target, "type": kind}
    return corrected, changes
