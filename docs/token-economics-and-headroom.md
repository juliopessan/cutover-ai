# Native Telemetry and Token Economics

The migration SDK owns telemetry, budgets and quality gates. Headroom is integrated as an optional optimization adapter rather than a hard runtime dependency.

## Design principles

1. Every LLM call records input, output and cached tokens, latency, estimated cost, agent, workflow stage and target platform.
2. Prompt and payload content are not captured by default. Sensitive values must be redacted before export.
3. Per-call and per-run budgets can fail closed before cost exceeds the configured ceiling.
4. Compression is accepted only when measured savings exceed the configured threshold.
5. Original context remains the fallback whenever compression is unavailable, uneconomic or causes a quality regression.
6. A holdout sample should bypass optimization so savings and answer quality can be compared against an uncompressed control group.

## Headroom integration

Install explicitly:

```bash
pip install "cutover-ai[headroom]"
```

The adapter imports `headroom.compress` lazily. This keeps the core SDK deployable in restricted environments and permits a proxy-based deployment later without changing agent contracts.

## Financial viability metrics

Track at minimum:

- cost per migration run;
- cost per discovered object;
- cost per generated mapping;
- cost per validated table;
- tokens before and after optimization;
- compression savings ratio;
- cache-hit tokens;
- retries and wasted-token rate;
- quality delta between optimized and holdout runs;
- projected monthly cost at expected workload.

An optimizer is financially viable only when net token savings exceed its compute and operational cost while reconciliation and quality gates remain within tolerance.
