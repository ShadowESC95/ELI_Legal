"""Keeps the governance registers honest.

A register that names a control nobody implemented, or a test that does not exist, is worse than
no register. This check ties each row to the code: implementation files must exist, named tests
must exist, and every cross-reference must resolve. It runs in CI and from ``eli-legal
governance``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

REQUIREMENT_STATUSES = {"implemented", "partial", "organisational"}
RISK_STATUSES = {"treated", "open", "accepted"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _ids(cell: str) -> list[str]:
    return [part.strip() for part in cell.split(";") if part.strip()]


REGISTER_DIR = Path(__file__).resolve().parent / "registers"
REGISTER_FILES = {
    "requirements": "requirements_register.csv",
    "controls": "control_register.csv",
    "risks": "risk_register.csv",
    "responsibilities": "provider_deployer_matrix.csv",
}


def load_register(name: str) -> list[dict[str, str]]:
    """One of the shipped registers as rows: requirements, controls, risks, responsibilities."""
    return _rows(REGISTER_DIR / REGISTER_FILES[name])


def check_registers(root: Path | None = None) -> list[str]:
    """Problems found, as plain sentences. Empty means the registers match the code.

    The registers and the code they point at ship in the package. ``root`` is a source checkout;
    when it has a ``tests`` directory, every test a control names must exist there. Without a
    checkout (an installed copy) the test names cannot be checked and that part is skipped.
    """
    governance = REGISTER_DIR
    source = Path(__file__).resolve().parents[1]
    tests = (root / "tests") if root is not None and (root / "tests").is_dir() else None
    problems: list[str] = []
    for name in ("control_register.csv", "risk_register.csv", "requirements_register.csv"):
        if not (governance / name).is_file():
            problems.append(f"missing register: {name}")
    if problems:
        return problems

    defined_tests: set[str] = set()
    if tests is not None:
        for path in tests.rglob("test_*.py"):
            defined_tests.update(
                re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), re.M)
            )

    controls = _rows(governance / "control_register.csv")
    control_ids = [c["control_id"] for c in controls]
    for duplicate in {c for c in control_ids if control_ids.count(c) > 1}:
        problems.append(f"duplicate control id {duplicate}")
    for control in controls:
        cid = control["control_id"]
        files = _ids(control["implementation"])
        if not files:
            problems.append(f"{cid} names no implementation")
        for file in files:
            if not (source / file).is_file():
                problems.append(f"{cid} points at src/eli_legal/{file}, which does not exist")
        named = _ids(control["tests"])
        if not named:
            problems.append(f"{cid} has no test")
        for test in named:
            if tests is not None and test not in defined_tests:
                problems.append(f"{cid} names test {test}, which does not exist")
        if control["type"] not in {"prevent", "detect", "respond"}:
            problems.append(f"{cid} has unknown type {control['type']!r}")
        if not control["owner_role"] or not control["evidence"]:
            problems.append(f"{cid} needs an owner role and the evidence it produces")

    known = set(control_ids)
    from eli_legal.legal.frameworks import load_shipped

    for pack in load_shipped().values():
        for req in pack.requirements:
            problems += [
                f"package {pack.pack_id} {req.req_id} names unknown control {c}"
                for c in req.controls
                if c not in control_ids
            ]
    referenced: set[str] = set()
    for risk in _rows(governance / "risk_register.csv"):
        rid = risk["risk_id"]
        linked = _ids(risk["control_ids"])
        referenced.update(linked)
        if not linked:
            problems.append(f"{rid} has no control")
        problems += [f"{rid} refers to unknown control {c}" for c in linked if c not in known]
        if risk["status"] not in RISK_STATUSES:
            problems.append(f"{rid} has unknown status {risk['status']!r}")
        if not risk["residual_risk_and_limits"].strip():
            problems.append(f"{rid} does not state its residual risk")
    for requirement in _rows(governance / "requirements_register.csv"):
        qid = requirement["requirement_id"]
        linked = _ids(requirement["control_ids"])
        referenced.update(linked)
        problems += [f"{qid} refers to unknown control {c}" for c in linked if c not in known]
        status = requirement["status"]
        if status not in REQUIREMENT_STATUSES:
            problems.append(f"{qid} has unknown status {status!r}")
        if status == "implemented" and not linked:
            problems.append(f"{qid} is marked implemented but names no control")
        if (
            status == "organisational"
            and "organisation" not in requirement["how_met_and_what_remains"].lower()
            and not requirement["how_met_and_what_remains"].strip()
        ):
            problems.append(f"{qid} must say what remains for the organisation")
    for orphan in sorted(known - referenced):
        problems.append(f"{orphan} is not linked to any risk or requirement")
    return problems
