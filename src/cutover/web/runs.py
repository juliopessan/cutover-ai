"""Persistence and export for governed mapping runs."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from cutover.web.db import Database


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold the event stream of one run into the row that gets stored."""
    by: dict[str, dict[str, Any]] = {}
    for event in events:
        by[event["type"]] = event  # the last event of each type wins
    response, scored, checks = by.get("provider.response"), by.get("gate.scored"), by.get("checks")
    result, summary, policy = by.get("result"), by.get("summary"), by.get("policy")
    rule = by.get("rule.corrected")
    failure = (by.get("error") or by.get("provider.error") or by.get("gate.blocked") or by.get("result.blocked") or {})
    completed = bool(result and checks and response)
    return {
        "status": "completed" if completed else "failed",
        "tier": scored and scored["tier"], "score": scored and scored["score"],
        "input_tokens": summary and summary["input_tokens"], "output_tokens": summary and summary["output_tokens"],
        "cost_usd": summary and summary["cost_usd"], "latency_ms": response and response["latency_ms"],
        "elapsed_ms": max((e.get("t_ms", 0) for e in events), default=0),
        "pass_rate": (rule or checks or {}).get("pass_rate"), "policy_action": policy and policy["action"],
        "mappings_json": json.dumps((rule or result)["mappings"], ensure_ascii=False) if result else None,
        "checks_json": json.dumps((rule or checks)["checks"], ensure_ascii=False) if checks else None,
        # A rule correction is an edit like any other: keep the model's suggestion and say what changed and why.
        "edited": 1 if rule else 0,
        "original_mappings_json": json.dumps(result["mappings"], ensure_ascii=False) if rule and result else None,
        "edit_log_json": json.dumps([{
            "at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"), "by": "Cutover (regra)", "source": "auto-regra",
            "changes": rule["changes"], "pass_rate_after": rule["pass_rate"], "reset_decision": False}],
            ensure_ascii=False) if rule else "[]",
        "prompt": (by.get("payload.built") or {}).get("prompt"),
        "price_in": (scored or {}).get("price_in"), "price_out": (scored or {}).get("price_out"),
        "input_cap": (scored or {}).get("input_cap"), "output_cap": (scored or {}).get("output_cap"),
        "estimated_cost_usd": (scored or {}).get("estimated_cost_usd"),
        "error": failure.get("message") or failure.get("reason") or (result or {}).get("error"),
    }


def save_run(db: Database, *, user_id: int, dataset_id: int, model: str, events: list[dict[str, Any]]) -> int:
    row = summarize(events)
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO mapping_runs(dataset_id, user_id, status, model, tier, score, input_tokens, output_tokens, "
            "cost_usd, latency_ms, elapsed_ms, pass_rate, policy_action, mappings_json, checks_json, error, "
            "prompt, price_in, price_out, input_cap, output_cap, estimated_cost_usd, edited, original_mappings_json, "
            "edit_log_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dataset_id, user_id, row["status"], model, row["tier"], row["score"], row["input_tokens"],
             row["output_tokens"], row["cost_usd"], row["latency_ms"], row["elapsed_ms"], row["pass_rate"],
             row["policy_action"], row["mappings_json"], row["checks_json"], row["error"], row["prompt"],
             row["price_in"], row["price_out"], row["input_cap"], row["output_cap"], row["estimated_cost_usd"],
             row["edited"], row["original_mappings_json"], row["edit_log_json"]))
        return int(cursor.lastrowid or 0)


def load_run(db: Database, *, dataset_id: int, user_id: int, run_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM mapping_runs WHERE id = ? AND dataset_id = ? AND user_id = ?",
                           (run_id, dataset_id, user_id)).fetchone()
    return _decode(row)


def best_run(db: Database, *, dataset_id: int, user_id: int) -> dict[str, Any] | None:
    """The approved run if there is one, otherwise the latest completed run."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM mapping_runs WHERE dataset_id = ? AND user_id = ? AND status = 'completed' "
            "ORDER BY (decision = 'approved') DESC, id DESC LIMIT 1", (dataset_id, user_id)).fetchone()
    return _decode(row)


def list_runs(db: Database, *, dataset_id: int, user_id: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM mapping_runs WHERE dataset_id = ? AND user_id = ? ORDER BY id DESC",
                            (dataset_id, user_id)).fetchall()
    return [d for d in (_decode(r) for r in rows) if d]


def _decode(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["mappings"] = json.loads(data.pop("mappings_json") or "{}")
    data["original_mappings"] = json.loads(data.pop("original_mappings_json", None) or "null")
    data["edit_log"] = json.loads(data.pop("edit_log_json", None) or "[]")
    data["checks"] = json.loads(data.pop("checks_json") or "[]")
    return data


def decide(db: Database, *, run_id: int, user_id: int, dataset_id: int, decision: str, note: str, who: str) -> tuple[bool, str]:
    """Approve or reject a completed run. Approval is refused unless every deterministic check passed."""
    run = load_run(db, dataset_id=dataset_id, user_id=user_id, run_id=run_id)
    if run is None:
        return False, "Execução não encontrada."
    if run["status"] != "completed":
        return False, "Só execuções concluídas podem ser decididas."
    if decision == "approved" and (run["pass_rate"] or 0) < 1.0:
        return False, "Verificações reprovadas: rejeite esta sugestão ou rode de novo."
    with db.connect() as conn:
        conn.execute("UPDATE mapping_runs SET decision = ?, decision_note = ?, decided_at = datetime('now'), decided_by = ? "
                     "WHERE id = ?", (decision, note[:500], who, run_id))
    return True, decision


def revise(db: Database, *, run_id: int, dataset_id: int, user_id: int, who: str, profile_columns: list[dict[str, Any]],
           new_mappings: dict[str, Any], changes: list[dict[str, Any]], source: str) -> tuple[bool, str, dict[str, Any] | None]:
    """Replace a run's mapping with an edited one and re-run the deterministic checks. No model is called.

    The model's original suggestion is kept, every change is logged with who and why, and the decision goes
    back to pending: an approval covers one exact mapping, so editing it always requires approving again.
    """
    from cutover.plugins.mapping import check_mapping
    from cutover.refinement import pass_rate_from_checks

    run = load_run(db, dataset_id=dataset_id, user_id=user_id, run_id=run_id)
    if run is None:
        return False, "Execução não encontrada.", None
    if run["status"] != "completed":
        return False, "Só execuções concluídas podem ser corrigidas.", None
    names = [c["name"] for c in profile_columns]
    checks = check_mapping(names, new_mappings, {c["name"]: c for c in profile_columns})
    pass_rate = pass_rate_from_checks(checks)
    log = [*run["edit_log"], {"at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"), "by": who, "source": source,
                              "changes": changes, "pass_rate_after": pass_rate, "reset_decision": run["decision"] != "pending"}]
    original = run["original_mappings"] if run["original_mappings"] is not None else run["mappings"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE mapping_runs SET mappings_json = ?, checks_json = ?, pass_rate = ?, edited = 1, original_mappings_json = ?, "
            "edit_log_json = ?, decision = 'pending', decision_note = NULL, decided_at = NULL, decided_by = NULL WHERE id = ?",
            (json.dumps(new_mappings, ensure_ascii=False), json.dumps(checks, ensure_ascii=False), pass_rate,
             json.dumps(original, ensure_ascii=False), json.dumps(log, ensure_ascii=False), run_id))
    return True, "ok", {"mappings": new_mappings, "checks": checks, "pass_rate": pass_rate, "changes": changes}


def csv_safe(value: Any) -> Any:
    """Neutralize spreadsheet formulas: a cell starting with = + - @ is executed by Excel and Sheets."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def mapping_csv(run: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["source_column", "target_column", "type", "decision"])
    for source, entry in run["mappings"].items():
        target = entry if isinstance(entry, str) else (entry or {}).get("target", "")
        kind = "" if isinstance(entry, str) else (entry or {}).get("type", "")
        writer.writerow([csv_safe(source), csv_safe(target), csv_safe(kind), run["decision"]])
    return out.getvalue()
