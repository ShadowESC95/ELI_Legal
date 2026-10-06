from __future__ import annotations
import argparse
from pathlib import Path

REQUIRED = [
    "config/policy.default.json", "docs/02_REQUIREMENTS.md",
    "src/eli_legal/domain/models.py", "src/eli_legal/legal/human_review_gate.py",
    "src/eli_legal/adapters/local/hmac_audit.py", "tests/evaluation/test_stale_authority_scenario.py",
]

parser = argparse.ArgumentParser()
parser.add_argument("--print", action="store_true", dest="print_tree")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
missing = [p for p in REQUIRED if not (root / p).exists()]
if missing:
    raise SystemExit("Missing required files: " + ", ".join(missing))
if args.print_tree:
    for p in sorted(root.rglob("*")):
        if ".venv" not in p.parts and "__pycache__" not in p.parts:
            print(p.relative_to(root))
else:
    print("tree OK")
