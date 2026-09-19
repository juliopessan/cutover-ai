# Evaluation: DeepSeek Harness (`dsh`) as an executor

Status: **not integrated yet**. Evaluated against `deepseek-harness` 0.1.0-rc.8 (developer preview, breaking changes expected).

## What `dsh` offers

The `deepseek-harness-sdk` Python package bundles the runtime and exposes `DeepSeekHarness(...).run(prompt, session_id=...)`, returning `RunResult(final_response, finish_reason, events, ...)`. It is an **agent loop** (persistent `bash` and `str_replace_editor` tools), not a single completion.

## Fit with Cutover

| Need | Verdict |
|---|---|
| Mapping suggestions, exception explanation (single completion) | Not a fit. `DeepSeekProvider` already covers these, with measured usage. |
| Generating and self-testing transformation code inside a sandbox | Good fit: multi-turn, runs tests, iterates. |
| Tollgate Guardian contract (measured cost, hard caps) | **Blocked.** `RunResult` exposes no token usage or cost, and its ACP server keeps usage off the wire. Tollgate rule 7 forbids mixing estimated and measured evidence, so a `dsh` run could only be logged as `estimated`. |
| Safety | The documented composition uses `danger-full-access`. It must run only in a disposable container or checkout, never against a source system or credentials. |
| Platforms | Linux x64/arm64 and macOS 14+ on arm64; no Windows agents. |

## Recommendation

1. Keep `DeepSeekProvider` as the default executor for all governed calls.
2. Add a `DshCodegenExecutor` only for sandboxed code generation, after either:
   - upstream exposes token usage in `RunResult` (or the runtime events are confirmed to carry it), so runs can be recorded as measured; or
   - the run is bounded by a hard wall-clock and turn cap and recorded as `estimated`, with cost reconciled from the DeepSeek account usage report.
3. Route it through the Aurora/Starlight approval path: generated code needs validation, lineage and human approval before use (see `AGENTS.md`).
4. Pin the `deepseek-harness-sdk` version; the project warns of breaking changes.
