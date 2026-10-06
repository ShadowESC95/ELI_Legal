from __future__ import annotations

import argparse
import json

from eli_legal.domain.policy import RuntimePolicy
from eli_legal.settings import settings


def doctor() -> int:
    problems = []
    if settings.network_default.lower() != "deny":
        problems.append("network default is not deny")
    if not settings.policy_file.exists():
        problems.append(f"policy missing: {settings.policy_file}")
    if not settings.audit_key_file.exists():
        problems.append(
            f"audit key missing: {settings.audit_key_file} (run scripts/generate_audit_key.py)"
        )
    print("ELI Legal doctor")
    print(f"  mode: {settings.mode}")
    print(f"  network default: {settings.network_default}")
    print(f"  policy: {settings.policy_file}")
    print(f"  audit key: {settings.audit_key_file}")
    if problems:
        for p in problems:
            print(f"  ERROR: {p}")
        return 1
    print("  OK: baseline checks passed")
    return 0


def show_policy() -> int:
    raw = json.loads(settings.policy_file.read_text())
    print(json.dumps(raw, indent=2))
    RuntimePolicy.from_file(settings.policy_file)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="eli-legal")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("show-policy")
    args = parser.parse_args()
    return doctor() if args.command == "doctor" else show_policy()


if __name__ == "__main__":
    raise SystemExit(main())
