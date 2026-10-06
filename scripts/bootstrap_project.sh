#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
mkdir -p secrets data/matters data/source_cache artifacts/runs artifacts/evidence artifacts/incidents
if [ ! -f secrets/audit_hmac.key ]; then python scripts/generate_audit_key.py; fi
python -m pytest
ruff format --check src tests
ruff check src tests
python -m eli_legal.cli doctor
printf '\nELI Legal scaffold is ready.\n'
