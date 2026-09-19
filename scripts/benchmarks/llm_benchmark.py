#!/usr/bin/env python3
"""Real governed LLM benchmark: the mapping suggestion on five datasets, three repetitions each.

Calls the DeepSeek API through the Tollgate gateway (needs DEEPSEEK_API_KEY, DEEPSEEK_MODEL and the
two DEEPSEEK_PRICE_* variables; `make llm-benchmark` loads .env). Only column names and types are sent.
Writes src/cutover/web/benchmarks/llm.json for the executive report. Costs a fraction of a cent.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "benchmarks"))

from profile_benchmark import build_defective_copy  # noqa: E402

from cutover.plugins.mapping import TARGET_NAME  # noqa: E402
from cutover.providers.deepseek import DeepSeekPricing, DeepSeekProvider  # noqa: E402
from cutover.web.live import run_mapping_stream  # noqa: E402
from cutover.web.profiling import profile_csv  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "cloudera_covid"
OUTPUT = ROOT / "src" / "cutover" / "web" / "benchmarks" / "llm.json"
REPS = 3
FAMILY = {"integer": {"int", "bigint"}, "decimal": {"double", "decimal"}, "boolean": {"boolean"},
          "date": {"date", "timestamp"}, "text": {"string"}, "mixed": {"string"}, "empty": {"string"}}


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct * (len(ordered) - 1)))]


def entry_of(mappings: dict, name: str) -> tuple[str | None, str | None]:
    entry = mappings.get(name)
    if isinstance(entry, dict):
        return entry.get("target"), entry.get("type")
    return (entry if isinstance(entry, str) else None), None


def main() -> None:
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
    pricing = DeepSeekPricing.from_env()
    provider = DeepSeekProvider(pricing=pricing)

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "raw_covid__cases_with_defects.csv"
        build_defective_copy(FIXTURES / "raw_covid__cases.csv", broken)
        sources = sorted(FIXTURES.glob("*.csv")) + [broken]
        profiles = {p.name: profile_csv(p) for p in sources}

        runs, per_dataset = [], {}
        for index, (name, profile) in enumerate(profiles.items(), start=1):
            outputs = []
            for rep in range(1, REPS + 1):
                events: list[dict] = []
                run_mapping_stream(
                    profile=profile.to_dict(), target="databricks", dataset_id=index,
                    db_path=Path(tmp) / "ledger.db", provider=provider, pricing=pricing, model=model,
                    emit=events.append)
                by = {}
                for event in events:
                    by.setdefault(event["type"], event)
                response, checks, scored = by.get("provider.response"), by.get("checks"), by.get("gate.scored")
                mappings = by.get("result", {}).get("mappings", {})
                outputs.append(mappings)
                names = [c["name"] for c in profile.columns]
                agree = sum(1 for c in profile.columns
                            if entry_of(mappings, c["name"])[1] in FAMILY.get(c["type"], set()))
                disagreements = [
                    {"column": c["name"], "profile_type": c["type"], "suggested_type": entry_of(mappings, c["name"])[1]}
                    for c in profile.columns if entry_of(mappings, c["name"])[1] not in FAMILY.get(c["type"], set())]
                needed = [n for n in names if not TARGET_NAME.match(n)]
                fixed = [n for n in needed if (entry_of(mappings, n)[0] or "") != n
                         and TARGET_NAME.match(entry_of(mappings, n)[0] or "")]
                run = {
                    "dataset": name, "rep": rep, "ok": bool(response and checks),
                    "error": by.get("error", {}).get("message") or by.get("provider.error", {}).get("message"),
                    "tier": scored and scored["tier"], "score": scored and scored["score"],
                    "input_tokens": response and response["input_tokens"],
                    "output_tokens": response and response["output_tokens"],
                    "cost_usd": response and response["cost_usd"], "latency_ms": response and response["latency_ms"],
                    "pass_rate": checks and checks["pass_rate"],
                    "checks_total": len((checks or {}).get("checks", [])),
                    "failed_checks": [c["name"] for c in (checks or {}).get("checks", []) if c["status"] == "failed"],
                    "type_family_agreement": agree / len(names), "disagreements": disagreements, "renames_needed": len(needed), "renames_done": len(fixed),
                }
                runs.append(run)
                print(f"{name:34} rep {rep}  " + (f"{run['latency_ms']:>5} ms  ${run['cost_usd']:.6f}  pass {run['pass_rate']:.2f}"
                                                  if run["ok"] else f"FAILED {run['error']}"), flush=True)
            names = [c["name"] for c in profile.columns]
            stable = sum(1 for n in names if len({entry_of(o, n) for o in outputs}) == 1)
            per_dataset[name] = {
                "rows": profile.rows, "columns": len(names), "alerts": [f.kind for f in profile.flags],
                "types": {t: sum(1 for c in profile.columns if c["type"] == t) for t in sorted({c["type"] for c in profile.columns})},
                "columns_stable_across_reps": stable,
            }

    ok = [r for r in runs if r["ok"]]
    latencies = [r["latency_ms"] for r in ok]
    needed = sum(r["renames_needed"] for r in ok)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "git_commit": commit,
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()),
        "model": model, "pricing_usd_per_million": {"input": pricing.input_per_million_usd, "output": pricing.output_per_million_usd},
        "environment": {"python": platform.python_version(), "platform": f"{platform.system()} {platform.machine()}"},
        "method": {"datasets": len(profiles), "repetitions": REPS, "sent_to_model": "column names and inferred types only"},
        "datasets": per_dataset, "runs": runs,
        "totals": {
            "runs": len(runs), "successful": len(ok), "failed": len(runs) - len(ok),
            "cost_usd_total": round(sum(r["cost_usd"] for r in ok), 8),
            "cost_usd_mean": round(statistics.mean(r["cost_usd"] for r in ok), 8),
            "cost_usd_max": max(r["cost_usd"] for r in ok),
            "input_tokens_total": sum(r["input_tokens"] for r in ok), "output_tokens_total": sum(r["output_tokens"] for r in ok),
            "latency_ms_median": round(statistics.median(latencies)), "latency_ms_p95": round(percentile(latencies, 0.95)),
            "latency_ms_max": max(latencies),
            "pass_rate_mean": round(statistics.mean(r["pass_rate"] for r in ok), 4),
            "runs_with_all_checks_passed": sum(1 for r in ok if r["pass_rate"] == 1.0),
            "type_family_agreement_mean": round(statistics.mean(r["type_family_agreement"] for r in ok), 4),
            "renames_needed": needed, "renames_done": sum(r["renames_done"] for r in ok),
            "columns_stable_across_reps": sum(d["columns_stable_across_reps"] for d in per_dataset.values()),
            "columns_total": sum(d["columns"] for d in per_dataset.values()),
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"], indent=2))


if __name__ == "__main__":
    main()
