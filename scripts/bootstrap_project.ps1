$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force secrets,data\matters,data\source_cache,artifacts\runs,artifacts\evidence,artifacts\incidents | Out-Null
if (-not (Test-Path secrets\audit_hmac.key)) { python scripts\generate_audit_key.py }
pytest
python -m eli_legal.cli doctor
Write-Host "`nELI Legal scaffold is ready."
