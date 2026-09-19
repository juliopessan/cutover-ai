# Load local secrets (DEEPSEEK_API_KEY, DEEPSEEK_MODEL) from .env when present.
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: install test lint serve pipelines benchmark llm-benchmark

PY := PYTHONPATH=src .venv/bin/python

# macOS marks the editable-install .pth file hidden and Python 3.14 skips hidden .pth files,
# which silently breaks `import cutover`. Running from src makes the targets independent of it.

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev,governance,scenarios,deepseek]"
	@# Undo the hidden flag macOS puts on the editable-install .pth, which Python 3.14 skips.
	@-chflags nohidden .venv/lib/python*/site-packages/*.pth 2>/dev/null || true
	@.venv/bin/python -c "import cutover" 2>/dev/null && echo "import cutover: ok" || echo "aviso: import cutover falhou; os alvos do make usam PYTHONPATH=src"

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src/cutover tests
	$(PY) -m mypy

serve:
	CUTOVER_DATA_DIR=./cutover-data PYTHONPATH=src $(PY) -m cutover.cli serve --port 8000

pipelines:
	$(PY) scripts/scenarios/cloudera_fabric/run_cloudera_fabric_pipeline.py
	$(PY) scripts/scenarios/snowflake_databricks/run_snowflake_databricks_pipeline.py

benchmark:
	$(PY) scripts/benchmarks/profile_benchmark.py

llm-benchmark:
	$(PY) scripts/benchmarks/llm_benchmark.py
