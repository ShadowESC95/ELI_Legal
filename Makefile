.PHONY: install test lint typecheck doctor tree
install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

doctor:
	python -m eli_legal.cli doctor

tree:
	python scripts/verify_tree.py --print
