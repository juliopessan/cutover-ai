"""Persistence and export for governed mapping runs."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from cutover.web.db import Database


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold the event stream of one run into the row that gets stored."""
    by: dict[str, dict[str, Any]] = {}
    for event in events:
        by[event["type"]] = event  # the last event of each type wins
    response, scored, checks = by.get("provider.response"), by.get("gate.scored"), by.get("checks")
    result, summary, policy = by.get("result"), by.get("summary"), by.get("policy")
    failure = (by.get("error") or by.get("provider.error") or by.get("gate.blocked") or by.get("result.blocked") or {})
    completed = bool(result and checks and response)
    return {
        "status": "completed" if completed else "failed",
        "tier": scored and scored["tier"], "score": scored and scored["score"],
        "input_tokens": summary and summary["input_tokens"], "output_tokens": summary and summary["output_tokens"],
        "cost_usd": summary and summary["cost_usd"], "latency_ms": response and response["latency_ms"],
        "elapsed_ms": max((e.get("t_ms", 0) for e in events), default=0),
        "pass_rate": checks and checks["pass_rate"], "policy_action": policy and policy["action"],
        "mappings_json": json.dumps(result["mappings"], ensure_ascii=False) if result else None,
        "checks_json": json.dumps(checks["checks"], ensure_ascii=False) if checks else None,
        "error": failure.get("message") or failure.get("reason") or (result or {}).get("error"),
    }


def save_run(db: Database, *, user_id: int, dataset_id: int, model: str, events: list[dict[str, Any]]) -> int:
    row = summarize(events)
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO mapping_runs(dataset_id, user_id, status, model, tier, score, input_tokens, output_tokens, "
            "cost_usd, latency_ms, elapsed_ms, pass_rate, policy_action, mappings_json, checks_json, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dataset_id, user_id, row["status"], model, row["tier"], row["score"], row["input_tokens"],
             row["output_tokens"], row["cost_usd"], row["latency_ms"], row["elapsed_ms"], row["pass_rate"],
             row["policy_action"], row["mappings_json"], row["checks_json"], row["error"]))
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


def mapping_csv(run: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["source_column", "target_column", "type", "decision"])
    for source, entry in run["mappings"].items():
        target = entry if isinstance(entry, str) else (entry or {}).get("target", "")
        kind = "" if isinstance(entry, str) else (entry or {}).get("type", "")
        writer.writerow([source, target, kind, run["decision"]])
    return out.getvalue()
