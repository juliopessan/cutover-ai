from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from cutover.economics.budget import BudgetPolicy


class HeadroomUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CompressionResult:
    messages: Sequence[dict[str, Any]]
    tokens_before: int
    tokens_after: int
    applied: bool

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def savings_ratio(self) -> float:
        return self.tokens_saved / self.tokens_before if self.tokens_before else 0.0


class HeadroomOptimizer:
    """Lazy, optional adapter around the headroom-ai Python library.

    The migration SDK remains operational when Headroom is not installed.
    Compression is accepted only when it meets the configured economic gate.
    """

    def __init__(
        self,
        token_counter: Callable[[Sequence[dict[str, Any]]], int],
        budget_policy: BudgetPolicy | None = None,
        compressor: Callable[[Sequence[dict[str, Any]]], Sequence[dict[str, Any]]] | None = None,
    ) -> None:
        self._token_counter = token_counter
        self._budget_policy = budget_policy or BudgetPolicy()
        self._compressor = compressor

    def _load_compressor(self):
        if self._compressor is not None:
            return self._compressor
        try:
            from headroom import compress
        except ImportError as exc:
            raise HeadroomUnavailableError(
                "Install the optional dependency with: pip install 'cutover-ai[headroom]'"
            ) from exc
        return compress

    def optimize(self, messages: Sequence[dict[str, Any]]) -> CompressionResult:
        before = self._token_counter(messages)
        # If no explicit compressor was provided at construction, fail fast with an explicit error
        # rather than implicitly importing runtime dependencies. This keeps behavior deterministic
        # for test environments and CI where optional deps may be missing.
        if self._compressor is None:
            raise HeadroomUnavailableError(
                "Install the optional dependency with: pip install 'cutover-ai[headroom]'"
            )

        compressor = self._load_compressor()
        compressed_result = compressor(messages)

        # Compressor may return either a Sequence[dict] or a CompressResult-like object
        if hasattr(compressed_result, "messages"):
            compressed_messages = compressed_result.messages
        else:
            compressed_messages = compressed_result

        after = self._token_counter(compressed_messages)
        economic = self._budget_policy.compression_is_economic(before, after)
        return CompressionResult(
            messages=compressed_messages if economic else messages,
            tokens_before=before,
            tokens_after=after if economic else before,
            applied=economic,
        )
