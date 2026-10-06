# Setup commands

## Linux / macOS

```bash
unzip ELI_Legal_scaffold.zip
cd ELI_Legal
chmod +x scripts/bootstrap_project.sh CREATE_TREE_COMMANDS.sh
./scripts/bootstrap_project.sh

git init
git branch -M main
git add .
git commit -m "Initial ELI Legal governance-first scaffold"
```

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
cp .env.example .env
python scripts/generate_audit_key.py
pytest
python -m eli_legal.cli doctor
uvicorn eli_legal.api.app:app --reload
```

## Windows PowerShell

```powershell
Expand-Archive .\ELI_Legal_scaffold.zip .
Set-Location .\ELI_Legal
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_project.ps1

git init
git branch -M main
git add .
git commit -m "Initial ELI Legal governance-first scaffold"
```

## Empty tree only

`CREATE_TREE_COMMANDS.sh` creates the directory/file names only. Use the ZIP/TAR scaffold for the populated starter implementation.
