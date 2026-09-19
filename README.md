# Cutover

[![CI](https://github.com/juliopessan/cutover-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/juliopessan/cutover-ai/actions/workflows/ci.yml)

**A model can draft your migration plan. It cannot be trusted to grade it.**

Cutover is governed data migration to Microsoft Fabric and Databricks: what can be measured is computed, every AI call is budgeted before it costs a token, and what cannot be verified is flagged.

<p align="center"><img src="docs/assets/landing.png" alt="Cutover landing page: headline 'Cada número da sua migração é medido, não afirmado' beside the cost-gate ledger read from dispatch.yaml" width="860"></p>

## Why this exists

AI-assisted migrations tend to fail quietly, in three places:

- **Spend has no ceiling.** Model calls are made without a budget per artifact, so cost is discovered on the invoice.
- **The model grades its own work.** A review by the same model that wrote the mapping tends to approve it. Counts, types and duplicates should be computed from the data instead.
- **Suggestions get applied without an owner.** A mapping that came from a model needs a person to decide before anything runs.

Cutover closes each one: a Tollgate gate in front of every provider call, deterministic checks for anything measurable, and human approval on model suggestions. Migration-critical work stays deterministic; models only analyse, suggest and explain.

## What works today

Cutover is alpha. Here is what you can use now and what is still being built.

| Step | What happens | Status |
|---|---|---|
| Onboarding | `cutover onboard` asks for business, security and target requirements and reports `blocked`, `needs_review` or `ready` | Available (CLI) |
| Upload and profile | The web app profiles a CSV: rows, types, empty cells, duplicates, SHA-256, Delta-compatible column names. Nothing is sent to an LLM | Available |
| Governed AI calls | `GovernedAgent` and `MappingSuggestionAgent` route every call through the Tollgate gateway; suggestions carry `requires_approval` | Available (SDK) |
| Refinement policy | `ArtifactBranch` decides accept, refine, escalate, parallelize or stop by pass rate and cost | Available (SDK), not yet wired to agents |
| Migration plan and validation | Plans per target and reconciliation of source against target | In development |

Extraction, deployment and cutover are never automatic; see the [safety boundary](#safety-boundary).

## Try it in two minutes

```bash
make install
make serve            # http://127.0.0.1:8000
```

Create an account at `/signup`, upload a CSV in UTF-8 (up to 25 MB) and read the profile. Or use Docker: `docker compose up --build`.

Data lives in `CUTOVER_DATA_DIR` (SQLite plus uploads), which makes this a single-node setup: back that directory up, and set `CUTOVER_COOKIE_SECURE=1` behind HTTPS.

## Governed AI calls (powered by Tollgate)

Cutover routes every LLM call through [Tollgate](https://github.com/juliopessan/toolgate): a complexity score picks a tier (Solar to Aurora), the Guardian admits, compresses or blocks the payload, and the outcome is recorded.

```bash
pip install "cutover-ai[governance]"      # Tollgate gate + waste ledger
pip install "cutover-ai[deepseek]"        # optional low-cost DeepSeek provider
```

```python
from pathlib import Path
from cutover.governance import GovernanceSettings, build_gateway, tier_for_score
from cutover.providers import DeepSeekPricing, DeepSeekProvider
from tollgate.governance.runtime.guardian import CallEnvelope

provider = DeepSeekProvider(pricing=DeepSeekPricing(input_per_million_usd=..., output_per_million_usd=...))
gateway = build_gateway(GovernanceSettings(db_path=Path("~/.cutover/ledger.db").expanduser()), provider)

score = 24.0  # your artifact complexity score, 0-100
response = gateway.complete(CallEnvelope(
    session_id="run-1", project_id="acme", artifact_id="mapping-42",
    payload=prompt, candidate_tokens=len(prompt) // 4,
    complexity_score=score, tier=tier_for_score(score),
    provider="deepseek", model="deepseek-chat",
    estimated_cost_usd=0.002, session_budget_usd=25.0,
))
```

A call with no score, an unknown tier or an exhausted budget raises `GuardianBlocked` and never reaches the provider. Tier caps live in [`dispatch.yaml`](src/cutover/governance/dispatch.yaml).

[DeepSeek Harness](https://github.com/juliopessan/deepseek-harness) is a TypeScript agent runtime and is intentionally **not** vendored: Cutover talks to DeepSeek models through the API provider above. A `dsh` executor for sandboxed code generation was evaluated and deferred; see [docs/dsh-executor-evaluation.md](docs/dsh-executor-evaluation.md).

## Repository layout

```text
src/cutover/          SDK, governance bridge, refinement policy and the web app (cutover.web)
tests/                pytest suite; fixtures/ holds Apache-2.0 seeds from Cloudera's dbt example
config/               economics and onboarding configuration
scripts/scenarios/    per-scenario simulators (Cloudera/Fabric, Snowflake/Databricks, Oracle, SAP legacy)
scripts/rtk/          RTK installers
templates/            dashboard and report templates
docs/                 design notes and guides (see docs/README.md)
```

`make install`, `make test`, `make lint`, `make serve` and `make pipelines` cover the common tasks. For the `rtk` CLI helpers, see [RTK Integration](docs/rtk/overview.md).

## Design principles

- **Onboarding first:** discovery cannot start until business, technical, security, target, testing, and acceptance requirements are complete.
- **Python owns execution:** contracts, state, validation, retries, budgets, telemetry, approvals, and integrations are implemented as testable Python components.
- **Markdown and YAML own behavior:** prompts, questions, policies, examples, and platform configuration remain declarative and versionable.
- **Fabric and Databricks are first-class targets:** each platform receives an independent target contract and deployment plan.
- **Cost is a runtime constraint:** token and cost limits are enforced before model calls, not discovered on an invoice later.
- **Quality outranks compression:** Headroom is optional and compression is accepted only when savings clear configured economic and quality gates.

## Architecture

```text
User
  -> Proactive Onboarding Agent
  -> Versioned MigrationIntake
  -> Readiness Gate
  -> Discovery and Source Plugins
  -> Mapping and Transformation Agents
  -> Fabric / Databricks Target Adapters
  -> Synthetic Data and Migration Simulation
  -> Validation and Reconciliation
  -> Human Approval
  -> Controlled Execution

Every agent call
  -> Redaction
  -> Token and Cost Budget Gate
  -> Optional Headroom Optimization
  -> LLM Gateway
  -> Native Telemetry
  -> Quality Gate
```

## SDK layout

```text
src/
├── cutover/
│   ├── core/             # agent contracts, runtime and plugin registry
│   ├── contracts/        # immutable migration and target contracts
│   ├── economics/        # token and cost budget policies
│   ├── optimization/     # optional Headroom adapter
│   ├── plugins/          # onboarding and future installable agents
│   ├── targets/          # Microsoft Fabric and Databricks adapters
│   └── telemetry/        # token, cost, latency and run events
└── cutover/     # API, CLI and migration control-plane scaffold
```

## Current source coverage

The initial catalog was generated from `migration_agent_checklist.xlsx` and covers Cloudera, Airflow, SSIS, SAP BusinessObjects, Informatica PowerCenter, Snowflake, Teradata, Oracle Exadata/ADW, IBM Db2 Warehouse, and SAP BW/HANA.

Connectors are being implemented incrementally behind stable source-plugin contracts.

## Target platforms

### Microsoft Fabric

Target planning covers OneLake landing zones, Lakehouse or Warehouse selection, Fabric Data Factory pipelines, notebooks, SQL assets, semantic models, Purview, lineage, reconciliation, and workspace/capacity constraints.

### Databricks

Target planning covers Unity Catalog, Delta Lake, catalogs and schemas, external locations, Lakeflow jobs and pipelines, notebooks, compute policy, lineage, access controls, and reconciliation.

Dual-target initiatives maintain separate contracts so that Fabric and Databricks decisions do not leak into each other.

## Proactive onboarding

The onboarding agent asks only the next relevant questions and produces one of three readiness states:

- `blocked`: mandatory, security, or residency information is unresolved.
- `needs_review`: explicit assumptions require human approval.
- `ready`: discovery may begin.

The workflow cannot continue without a selected target and an approved synthetic-data policy.

## Financial governance and Headroom

Native telemetry records token usage, estimated cost, latency, model, agent, workflow stage, source system, and target platform. Prompt content is not captured by default.

Budget policies can fail closed when per-call or per-run token and cost limits are exceeded. Headroom is loaded lazily and remains optional:

```bash
pip install -e ".[headroom]"
```

Compression is used only when measured savings exceed the configured threshold. A holdout group and reconciliation gates protect quality, while the original context remains the fallback.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev,governance]"

ruff check .
mypy src
pytest -q
python -m build
```

Run the existing control plane:

```bash
cutover onboard --answers answers.json
```

## CI quality gates

GitHub Actions validates Python 3.11 and 3.12 with:

- Ruff linting and import checks;
- strict mypy type checking;
- pytest unit tests;
- source and wheel builds;
- clean wheel installation and import smoke tests.

## Safety boundary

The repository currently provides a safe control plane for onboarding, discovery planning, mappings, synthetic test data, target planning, telemetry, and validation evidence. Production extraction, deployment, and cutover require explicit credentials, network configuration, policy approval, and human authorization.

## Roadmap

Near-term work includes the workflow state machine, OpenTelemetry exporters, source connector contracts, Snowflake and Oracle discovery, deeper Fabric and Databricks planners, secrets redaction middleware, synthetic data integration, and migration-cost dashboards.
