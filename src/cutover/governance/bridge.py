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


def build_gateway(
    settings: GovernanceSettings,
    client: Any,
    token_counter: Callable[[str], int] | None = None,
    compressor: Any | None = None,
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
    return GuardedProviderGateway(guardian, BudgetReservations(settings.db_path), client)
