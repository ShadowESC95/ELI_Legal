#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
python -m eli_legal.cli init
python -m pytest
ruff format --check src tests
ruff check src tests
mypy src
python -m eli_legal.cli governance
python -m eli_legal.cli doctor
printf '\nELI Legal is ready. Try: eli-legal demo\n'
