$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m eli_legal.cli init
python -m pytest
ruff format --check src tests
ruff check src tests
mypy src
python -m eli_legal.cli governance
python -m eli_legal.cli doctor
Write-Host "`nELI Legal is ready. Try: eli-legal demo"
