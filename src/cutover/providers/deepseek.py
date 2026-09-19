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
        """One chat completion. Pass ``on_delta(kind, text)`` to receive the stream as it arrives.

        ``kind`` is ``"reasoning"`` or ``"content"``. Usage is always taken from the provider's own
        report; a stream that ends without usage raises, because cost would be unmeasured.
        """
        from tollgate.governance.runtime.provider_gateway import ProviderResponse

        on_delta = kwargs.pop("on_delta", None)
        system = kwargs.pop("instructions", None)
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": payload})
        if on_delta is None:
            response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
            usage, content, raw = response.usage, response.choices[0].message.content or "", response
        else:
            stream = self.client.chat.completions.create(
                model=model, messages=messages, stream=True,
                stream_options={"include_usage": True}, **kwargs)
            parts: list[str] = []
            usage = None
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "reasoning_content", None):
                    on_delta("reasoning", delta.reasoning_content)
                if getattr(delta, "content", None):
                    parts.append(delta.content)
                    on_delta("content", delta.content)
            content, raw = "".join(parts), None
            if usage is None:
                raise DeepSeekProviderError("provider ended the stream without usage; cost cannot be measured")
        return ProviderResponse(
            content=content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=self.pricing.calculate(usage.prompt_tokens, usage.completion_tokens),
            raw=raw,
        )
