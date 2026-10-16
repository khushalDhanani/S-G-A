.PHONY: install run test lint eval check-env
VENV := .venv/bin
PY   := $(VENV)/python

install:
	$(PY) -m pip install -e '.[dev]'
run:
	$(VENV)/sap-agent start
test:
	$(PY) -m pytest
lint:
	$(VENV)/ruff check src tests evals
	$(VENV)/mypy src
eval:
	$(PY) evals/run_evals.py
check-env:
	bash scripts/check_env.sh
