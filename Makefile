PYTHON ?= python3

.PHONY: format lint typecheck test check

format:
	black src/ tests/

lint:
	ruff check src/ tests/

typecheck:
	mypy src/

test:
	pytest --cov=src/gitsync --cov-report=term-missing --cov-fail-under=80

check: format lint typecheck test