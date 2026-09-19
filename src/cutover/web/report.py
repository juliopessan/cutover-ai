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
        "cost_tail": (llm["totals"]["cost_usd_max"] / llm["totals"]["cost_usd_mean"]) if llm else 0.0,
    }
