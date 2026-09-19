"""Data behind the executive report. Measured figures come from committed benchmark files."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

BENCH = Path(__file__).parent / "benchmarks"

# Every value below is an ASSUMPTION for illustration, not a measurement. The report says so and lets
# the reader replace them. Only ``ai_cost_per_dataset_usd`` starts from a measured value.
ASSUMPTIONS: dict[str, dict[str, Any]] = {
    "datasets": {"label": "Datasets por assessment", "value": 50, "step": 1, "unit": ""},
    "assessments_per_year": {"label": "Assessments por ano", "value": 4, "step": 1, "unit": ""},
    "manual_hours": {"label": "Horas do time por dataset, à mão", "value": 2.0, "step": 0.25, "unit": "h"},
    "review_hours": {"label": "Horas de revisão humana por dataset, com IA", "value": 0.25, "step": 0.05, "unit": "h"},
    "rate_usd": {"label": "Custo horário do time (carga total)", "value": 60.0, "step": 5, "unit": "US$/h"},
    "platform_usd": {"label": "Custo de plataforma por assessment", "value": 50.0, "step": 10, "unit": "US$"},
    "setup_hours": {"label": "Esforço único de adoção", "value": 40.0, "step": 5, "unit": "h"},
}


# Illustrative work breakdown for the pilot: (code, task, optimistic h, most likely h, pessimistic h, source).
# These are estimates to be validated with the client, not measurements.
PILOT_WBS: list[tuple[str, str, float, float, float, str]] = [
    ("1.1", "Curadoria da amostra de datasets e acordo de uso dos dados (NDA)", 6, 10, 20, "Pré-condição de dados reais"),
    ("1.2", "Cronometrar o assessment manual em 5 datasets (baseline)", 8, 12, 20, "Fecha a lacuna do ROI"),
    ("1.3", "Rodar o AI-IS nos mesmos datasets e registrar a revisão humana", 6, 10, 18, "Mesmos 5 datasets do baseline"),
    ("1.4", "Análise de qualidade com revisores (aceite sem edição, divergências)", 8, 14, 24, "Cria o gabarito humano"),
    ("1.5", "Relatório final de decisão com ROI medido", 6, 10, 16, "Substitui as premissas por medições"),
]


def pilot_wbs() -> tuple[list[dict[str, Any]], float]:
    rows = [{"code": c, "task": t, "o": o, "m": m, "p": p, "e": (o + 4 * m + p) / 6, "source": src}
            for c, t, o, m, p, src in PILOT_WBS]
    return rows, sum(r["e"] for r in rows)


def load(name: str) -> dict[str, Any] | None:
    try:
        return json.loads((BENCH / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def roi(a: dict[str, float], ai_cost_per_dataset_usd: float) -> dict[str, float]:
    """AS-IS assessment economics: a team doing it by hand versus AI plus human review.

    No migration cost or risk appears here on purpose: an AI-IS delivers the result without migrating platforms.
    """
    manual = a["datasets"] * a["manual_hours"] * a["rate_usd"]
    assisted = (a["datasets"] * (a["review_hours"] * a["rate_usd"] + ai_cost_per_dataset_usd) + a["platform_usd"])
    saving = manual - assisted
    setup = a["setup_hours"] * a["rate_usd"]
    annual = saving * a["assessments_per_year"]
    return {
        "manual_cost": manual, "assisted_cost": assisted, "saving": saving,
        "hours_saved": a["datasets"] * (a["manual_hours"] - a["review_hours"]),
        "reduction": saving / manual if manual else 0.0, "annual_saving": annual, "setup_cost": setup,
        "payback_assessments": setup / saving if saving > 0 else float("inf"),
        "roi_year_one": (annual - setup) / setup if setup else 0.0,
    }


def per_dataset(llm: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, info in llm["datasets"].items():
        runs = [r for r in llm["runs"] if r["dataset"] == name and r["ok"]]
        if not runs:
            continue
        rows.append({
            "name": name, "rows": info["rows"], "columns": info["columns"], "alerts": len(info["alerts"]),
            "runs": len(runs), "latency_median": round(statistics.median(r["latency_ms"] for r in runs)),
            "latency_max": max(r["latency_ms"] for r in runs), "cost_mean": statistics.mean(r["cost_usd"] for r in runs),
            "pass_mean": statistics.mean(r["pass_rate"] for r in runs), "stable": info["columns_stable_across_reps"],
        })
    return rows


def disagreements(llm: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], int] = {}
    for run in llm["runs"]:
        for d in run.get("disagreements", []):
            key = (run["dataset"], d["column"], f"{d['profile_type']} → {d['suggested_type']}")
            seen[key] = seen.get(key, 0) + 1
    return [{"dataset": k[0], "column": k[1], "change": k[2], "times": n} for k, n in sorted(seen.items())]


def check_failures(llm: dict[str, Any]) -> list[dict[str, Any]]:
    """Which deterministic checks rejected model output, how often, and one concrete example each."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for run in llm["runs"]:
        for name, offenders in (run.get("failed_detail") or {}).items():
            entry = found.setdefault((run["dataset"], name), {"dataset": run["dataset"], "check": name, "times": 0,
                                                              "example": (offenders or [""])[0]})
            entry["times"] += 1
    return sorted(found.values(), key=lambda e: (-e["times"], e["dataset"]))


def build_context() -> dict[str, Any]:
    profile, llm, project = load("profile"), load("llm"), load("project")
    defaults = {k: v["value"] for k, v in ASSUMPTIONS.items()}
    ai_cost = llm["totals"]["cost_usd_mean"] if llm else 0.0
    wbs, wbs_total = pilot_wbs()
    return {
        "wbs": wbs, "wbs_total": wbs_total, "wbs_weeks": wbs_total / 25,
        "profile": profile, "llm": llm, "project": project, "assumptions": ASSUMPTIONS,
        "defaults": defaults, "ai_cost": ai_cost, "roi": roi(defaults, ai_cost),
        "per_dataset": per_dataset(llm) if llm else [], "disagreements": disagreements(llm) if llm else [],
        "check_failures": check_failures(llm) if llm else [],
        "checks_per_run": max((run.get("checks_total", 0) for run in llm["runs"]), default=0) if llm else 0,
        "cost_tail": (llm["totals"]["cost_usd_max"] / llm["totals"]["cost_usd_mean"]) if llm else 0.0,
    }


def _seconds_between(start: str | None, end: str | None) -> float | None:
    from datetime import datetime

    try:
        return (datetime.strptime(end or "", "%Y-%m-%d %H:%M:%S") - datetime.strptime(start or "", "%Y-%m-%d %H:%M:%S")).total_seconds()
    except ValueError:
        return None


def column_note(c: dict[str, Any]) -> str:
    """One measured observation per column, used next to the suggested mapping."""
    notes = []
    if c.get("is_key_candidate"):
        notes.append("candidata a chave (valores únicos)")
    kind = c.get("type")
    if kind == "decimal" and c.get("max_scale") is not None:
        notes.append(f"decimal({(c.get('max_int_digits') or 0) + c['max_scale']},{c['max_scale']}) é o mínimo observado")
    elif kind == "integer" and c.get("min") is not None:
        notes.append(f"faixa {c['min']} a {c['max']}")
    elif kind == "date" and c.get("min"):
        notes.append(f"de {c['min']} a {c['max']}")
    elif kind == "text" and c.get("max_len"):
        notes.append(f"até {c['max_len']} caracteres")
    return "; ".join(notes)


def dataset_economy(run: dict[str, Any] | None, baselines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Time and money for one dataset. The manual side is the analyst-reported baseline when there is one."""
    if not run or run.get("elapsed_ms") is None:
        return None
    assumptions = {k: v["value"] for k, v in ASSUMPTIONS.items()}
    reported = statistics.median(b["seconds"] for b in baselines) / 3600 if baselines else None
    manual_hours = reported if reported is not None else assumptions["manual_hours"]
    review = _seconds_between(run.get("created_at"), run.get("decided_at")) if run["decision"] != "pending" else None
    ai_seconds = run["elapsed_ms"] / 1000
    hours_spent = (ai_seconds + (review or 0)) / 3600
    saving_hours = manual_hours - hours_spent if review is not None else None
    return {
        "ai_seconds": ai_seconds, "review_seconds": review, "manual_hours": manual_hours,
        "manual_is_reported": reported is not None, "baseline_count": len(baselines), "rate_usd": assumptions["rate_usd"],
        "saving_hours": saving_hours,
        "saving_usd": saving_hours * assumptions["rate_usd"] - (run.get("cost_usd") or 0) if saving_hours is not None else None,
    }


def dataset_analysis(profile: dict[str, Any], run: dict[str, Any] | None, history: list[dict[str, Any]],
                     baselines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything the dataset report shows beyond the raw profile. Measured values and assumptions stay separate."""
    from cutover.web.profiling import INVALID_NAME_CHARS

    columns = profile["columns"]
    total_cells, rows = profile.get("total_cells", 0), profile["rows"]
    bad_names = [c for c in columns if INVALID_NAME_CHARS.search(c["name"]) or not c["name"].strip()]
    discarded = profile.get("rows_discarded", 0)
    quality = [
        ("Completude (células preenchidas)", 1 - (profile["empty_cells"] / total_cells) if total_cells else 1.0),
        ("Unicidade de linhas", 1 - (profile["duplicate_rows"] / rows) if rows else 1.0),
        ("Consistência de tipos (colunas sem mistura)", sum(1 for c in columns if c["type"] != "mixed") / len(columns)),
        ("Nomes compatíveis com Delta", 1 - len(bad_names) / len(columns)),
        ("Linhas lidas sem descarte", rows / (rows + discarded) if rows + discarded else 1.0),
    ]
    notes = {c["name"]: column_note(c) for c in columns}
    economy = dataset_economy(run, baselines or [])
    return {
        "quality": quality, "notes": notes, "economy": economy, "has_stats": "distinct" in (columns[0] if columns else {}),
        "key_columns": [c["name"] for c in columns if c.get("is_key_candidate")],
        "history": history,
    }


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def consolidated_analysis(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-dataset view for one client. ``items`` carry dataset, profile, best run, all runs and baselines."""
    from collections import Counter

    total_rows = sum(i["profile"]["rows"] for i in items)
    kinds: Counter[str] = Counter()
    for i in items:
        kinds.update(f["kind"] for f in i["profile"]["flags"])
    states = Counter((i["run"]["decision"] if i["run"] else "none") for i in items)

    by_name: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for i in items:
        for c in i["profile"]["columns"]:
            by_name.setdefault(_norm(c["name"]), []).append((i["dataset"]["filename"], c))
    shared, conflicts = [], []
    for group in by_name.values():
        files = {f for f, _ in group}
        if len(files) < 2:
            continue
        types = {c["type"] for _, c in group}
        row = {"column": group[0][1]["name"], "datasets": sorted(files), "types": sorted(types),
               "key_in": sorted(f for f, c in group if c.get("is_key_candidate"))}
        (conflicts if len(types) > 1 else shared).append(row)

    hints = [{"dataset": i["dataset"]["filename"], **h} for i in items for h in i["profile"].get("privacy_hints", [])]
    economies = [(i, dataset_economy(i["run"], i["baselines"])) for i in items if i["run"]]
    decided = [(i, e) for i, e in economies if e and e["saving_hours"] is not None]
    reported = [e for _, e in decided if e["manual_is_reported"]]
    return {
        "datasets": len(items), "rows": total_rows, "columns": sum(len(i["profile"]["columns"]) for i in items),
        "bytes": sum(i["dataset"]["size_bytes"] for i in items), "alerts_total": sum(kinds.values()),
        "alert_kinds": kinds.most_common(), "states": dict(states), "shared": shared, "conflicts": conflicts,
        "hints": hints, "runs_total": sum(len(i["runs"]) for i in items),
        "cost_total": sum((r.get("cost_usd") or 0) for i in items for r in i["runs"]),
        "decided": len(decided), "with_baseline": len(reported),
        "saving_hours": sum(e["saving_hours"] for _, e in decided),
        "saving_hours_reported": sum(e["saving_hours"] for e in reported),
        "saving_usd": sum(e["saving_usd"] for _, e in decided),
        "review_minutes": sum((e["review_seconds"] or 0) for _, e in decided) / 60,
        "ai_seconds": sum(e["ai_seconds"] for _, e in economies if e),
    }
