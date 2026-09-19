from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeepSeekPricing:
    """Per-million-token prices used to reconcile measured usage.

    Prices are supplied by the caller so they never go stale inside the SDK.
    """

    input_per_million_usd: float
    output_per_million_usd: float

    @classmethod
    def from_env(cls) -> "DeepSeekPricing":
        """Read DEEPSEEK_PRICE_INPUT_PER_M and DEEPSEEK_PRICE_OUTPUT_PER_M (USD per million tokens)."""
        try:
            return cls(
                input_per_million_usd=float(os.environ["DEEPSEEK_PRICE_INPUT_PER_M"]),
                output_per_million_usd=float(os.environ["DEEPSEEK_PRICE_OUTPUT_PER_M"]),
            )
        except (KeyError, ValueError) as exc:
            raise DeepSeekProviderError(
                "Set DEEPSEEK_PRICE_INPUT_PER_M and DEEPSEEK_PRICE_OUTPUT_PER_M (see .env.example)"
            ) from exc

    def calculate(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1_000_000 * self.input_per_million_usd
            + output_tokens / 1_000_000 * self.output_per_million_usd,
            8,
        )


class DeepSeekProvider:
    """Provider client for the DeepSeek chat API (OpenAI-compatible).

    Satisfies Tollgate's ``ProviderClient`` protocol, so it plugs into
    ``cutover.governance.build_gateway``. A cost-efficient fit for the
    Daylight and Horizon tiers. Accepts an injected client for deterministic tests.
    """

    def __init__(
        self,
        *,
        pricing: DeepSeekPricing,
        client: Any | None = None,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.pricing = pricing
        if client is not None:
            self.client = client
            return
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise DeepSeekProviderError(
                "Install the deepseek extra with: pip install 'cutover-ai[deepseek]'"
            ) from exc
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise DeepSeekProviderError("DEEPSEEK_API_KEY is required")
        self.client = OpenAI(api_key=resolved_key, base_url=base_url)

    def complete(self, *, model: str, payload: str, **kwargs: Any) -> Any:
        from tollgate.governance.runtime.provider_gateway import ProviderResponse

        system = kwargs.pop("instructions", None)
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": payload})
        response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
        usage = response.usage
        return ProviderResponse(
            content=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=self.pricing.calculate(usage.prompt_tokens, usage.completion_tokens),
            raw=response,
        )
