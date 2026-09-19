from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_DISPATCH_POLICY = Path(__file__).with_name("dispatch.yaml")


class GovernanceUnavailableError(RuntimeError):
    """Raised when Tollgate is required but not installed."""


@dataclass(frozen=True, slots=True)
class GovernanceSettings:
    db_path: Path
    policy_path: Path = DEFAULT_DISPATCH_POLICY


def _require_tollgate() -> None:
    try:
        import tollgate  # noqa: F401
    except ImportError as exc:
        raise GovernanceUnavailableError(
            "Install the governance extra with: pip install 'cutover-ai[governance]'"
        ) from exc


def load_dispatch_tiers(policy_path: Path = DEFAULT_DISPATCH_POLICY) -> list[dict[str, Any]]:
    """Return the tier definitions (id, score range, caps) from a dispatch policy file."""
    import yaml

    raw = yaml.safe_load(Path(policy_path).read_text(encoding="utf-8"))
    tiers = raw.get("tiers") if isinstance(raw, dict) else None
    if not isinstance(tiers, list) or not tiers:
        raise ValueError(f"{policy_path} must define at least one tier")
    return tiers


def tier_for_score(score: float, policy_path: Path = DEFAULT_DISPATCH_POLICY) -> str:
    """Map a 0-100 complexity score to a tier id. Fails closed on out-of-range scores."""
    for tier in load_dispatch_tiers(policy_path):
        if tier["score_min"] <= score <= tier["score_max"]:
            return str(tier["id"])
    raise ValueError(f"complexity score {score} is outside every tier range")


def tier_output_cap(tier_id: str, policy_path: Path = DEFAULT_DISPATCH_POLICY) -> int:
    """Output-token cap of a tier, used as the provider's hard max_tokens."""
    for tier in load_dispatch_tiers(policy_path):
        if tier["id"] == tier_id:
            return int(tier["output_token_cap"])
    raise ValueError(f"unknown tier {tier_id!r}")


class _EventingGuardian:
    """Delegates to a Tollgate Guardian and reports each gate decision to ``emit``."""

    def __init__(self, guardian: Any, emit: Callable[[dict[str, Any]], None]) -> None:
        self._guardian = guardian
        self._emit = emit

    def enforce(self, envelope: Any) -> Any:
        from tollgate.governance.runtime.guardian import GuardianBlocked

        try:
            result = self._guardian.enforce(envelope)
        except GuardianBlocked as exc:
            self._emit({"type": "gate.blocked", "reason": str(exc)})
            raise
        self._emit({
            "type": "gate.admitted", "decision": result.decision,
            "admitted_tokens": result.admitted_tokens, "rejected_tokens": result.rejected_tokens,
        })
        return result

    def record_completion(self, result: Any, actual_cost_usd: float, output_tokens: int, quality_status: str) -> None:
        self._guardian.record_completion(result, actual_cost_usd, output_tokens, quality_status)
        self._emit({"type": "gate.audited", "output_tokens": output_tokens, "actual_cost_usd": actual_cost_usd})


class _EventingClient:
    """Delegates to a provider client and reports the call and its measured usage."""

    def __init__(self, client: Any, emit: Callable[[dict[str, Any]], None]) -> None:
        self._client = client
        self._emit = emit

    def complete(self, *, model: str, payload: str, **kwargs: Any) -> Any:
        import time

        totals = {"reasoning": 0, "content": 0}
        buffer = {"reasoning": "", "content": ""}
        last_flush = [time.perf_counter()]

        def flush() -> None:
            for kind, text in buffer.items():
                if text:
                    self._emit({"type": "provider.delta", "kind": kind, "text": text, "chars": totals[kind]})
                    buffer[kind] = ""
            last_flush[0] = time.perf_counter()

        def on_delta(kind: str, text: str) -> None:
            buffer[kind] += text
            totals[kind] += len(text)
            if time.perf_counter() - last_flush[0] >= 0.12:
                flush()

        self._emit({"type": "provider.call", "model": model, "max_tokens": kwargs.get("max_tokens")})
        started = time.perf_counter()
        try:
            response = self._client.complete(model=model, payload=payload, on_delta=on_delta, **kwargs)
        except Exception as exc:
            flush()
            self._emit({"type": "provider.error", "message": f"{type(exc).__name__}: {exc}"})
            raise
        flush()
        self._emit({
            "type": "provider.response", "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens, "cost_usd": response.cost_usd,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        return response


def build_gateway(
    settings: GovernanceSettings,
    client: Any,
    token_counter: Callable[[str], int] | None = None,
    compressor: Any | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """Build a Tollgate GuardedProviderGateway around any provider client.

    Every call passes admission, compression and audit before reaching the provider,
    and is recorded in the waste ledger at ``settings.db_path``.
    """
    _require_tollgate()
    from tollgate.context.tokens import estimate_tokens
    from tollgate.governance.runtime.compressors import ContextCompressor
    from tollgate.governance.runtime.guardian import Guardian
    from tollgate.governance.runtime.policy_loader import load_tier_policies
    from tollgate.governance.runtime.provider_gateway import GuardedProviderGateway
    from tollgate.governance.store.budget_reservations import BudgetReservations
    from tollgate.governance.store.waste_ledger import WasteLedger

    ledger = WasteLedger(settings.db_path)
    ledger.migrate()
    guardian = Guardian(
        ledger,
        load_tier_policies(settings.policy_path),
        token_counter or estimate_tokens,
        compressor or ContextCompressor(),
    )
    if on_event is not None:
        guardian = _EventingGuardian(guardian, on_event)
        client = _EventingClient(client, on_event)
    return GuardedProviderGateway(guardian, BudgetReservations(settings.db_path), client)
