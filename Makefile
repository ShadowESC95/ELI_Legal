.PHONY: install test lint format typecheck governance check demo doctor
install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

governance:
	python -m eli_legal.cli governance

check: test lint typecheck governance
	ruff format --check src tests

demo:
	python -m eli_legal.cli demo

doctor:
	python -m eli_legal.cli doctor
