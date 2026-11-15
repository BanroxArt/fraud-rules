PY ?= python3

.PHONY: bench install lint test check compiled

install:
	$(PY) -m pip install -e '.[dev]'

lint:
	ruff check .
	ruff format --check .
	$(PY) scripts/check.py
	$(PY) -m mypy

test:
	$(PY) -m pytest -q

check: lint test compiled

compiled:
	$(PY) scripts/build_compiled.py --check

bench:
	PYTHONPATH=src $(PY) bench/run.py
