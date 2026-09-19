.PHONY: install test lint serve pipelines benchmark

PY := .venv/bin/python

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev,governance,scenarios]"

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src/cutover tests

serve:
	CUTOVER_DATA_DIR=./cutover-data $(PY) -m cutover.cli serve --port 8000

pipelines:
	$(PY) scripts/scenarios/cloudera_fabric/run_cloudera_fabric_pipeline.py
	$(PY) scripts/scenarios/snowflake_databricks/run_snowflake_databricks_pipeline.py

benchmark:
	$(PY) scripts/benchmarks/profile_benchmark.py
