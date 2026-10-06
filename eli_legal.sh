#!/usr/bin/env bash
# Start ELI Legal. With no arguments it opens the desktop application;
# with arguments it is the command line (./eli_legal.sh doctor, ./eli_legal.sh demo, ...).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" -m eli_legal "$@"
