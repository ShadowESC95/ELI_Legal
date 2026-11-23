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
    "families": "control_families.csv",
    "lifecycle": "lifecycle_stages.csv",
    "requirements": "requirements_register.csv",
    "controls": "control_register.csv",
    "risks": "risk_register.csv",
    "responsibilities": "provider_deployer_matrix.csv",
    "actions": "organisation_actions.csv",
}


def load_register(name: str) -> list[dict[str, str]]:
    """One of the shipped registers as rows: families, requirements, controls, risks,
    responsibilities, actions."""
    return _rows(REGISTER_DIR / REGISTER_FILES[name])


# Controls are identified by the five controls of the RAIMS Week 5 Control Map: RM-01 Risk
# Management, HO-01 Human Oversight, TR-01 Transparency, MO-01 Monitoring, DG-01 Data Governance.
# Each of ELI Legal's controls is a numbered part of one (HO-01.2); its former number (C-14) is
# kept beside it, so earlier records, packages and papers still resolve.
FAMILY_ORDER = ("RM", "HO", "TR", "MO", "DG")
CONTROL_ID = re.compile(r"^(RM|HO|TR|MO|DG)-01\.(\d+)$")
FORMER_ID = re.compile(r"^C-\d{2}$")


def family_of(control_id: str) -> str:
    """``HO-01.2`` → ``HO-01``."""
    return control_id.split(".", 1)[0]


def control_sort_key(control_id: str) -> tuple[int, int]:
    m = CONTROL_ID.match(control_id)
    return (FAMILY_ORDER.index(m.group(1)), int(m.group(2))) if m else (len(FAMILY_ORDER), 0)


def former_ids() -> dict[str, str]:
    """Each control's former number and its id now: ``C-14`` → ``HO-01.2``."""
    return {
        row["formerly"]: row["control_id"]
        for row in load_register("controls")
        if row.get("formerly")
    }


def current_control_id(control_id: str) -> str:
    """The id a control has now, whether it was given by its current or its former number."""
    cid = control_id.strip()
    return former_ids().get(cid, cid) if FORMER_ID.match(cid) else cid


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

    families = (
        {f["family_id"]: f for f in _rows(governance / REGISTER_FILES["families"])}
        if (governance / REGISTER_FILES["families"]).is_file()
        else {}
    )
    if set(families) != {f"{f}-01" for f in FAMILY_ORDER}:
        problems.append("the control families must be exactly RM-01, HO-01, TR-01, MO-01 and DG-01")
    for fid, family in families.items():
        for column in ("name", "what_it_needs", "control", "owner", "evidence"):
            if not family.get(column, "").strip():
                problems.append(f"{fid} needs its {column.replace('_', ' ')}")
    stages = (
        {s["stage"] for s in _rows(governance / REGISTER_FILES["lifecycle"])}
        if (governance / REGISTER_FILES["lifecycle"]).is_file()
        else set()
    )
    controls = _rows(governance / "control_register.csv")
    control_ids = [c["control_id"] for c in controls]
    formerly = [c.get("formerly", "") for c in controls if c.get("formerly")]
    for duplicate in {f for f in formerly if formerly.count(f) > 1}:
        problems.append(f"two controls were both {duplicate}")
    for duplicate in {c for c in control_ids if control_ids.count(c) > 1}:
        problems.append(f"duplicate control id {duplicate}")
    for control in controls:
        cid = control["control_id"]
        if not CONTROL_ID.match(cid):
            problems.append(f"{cid} is not a part of a RAIMS control (such as HO-01.2)")
        elif family_of(cid) not in families:
            problems.append(f"{cid} belongs to no control family")
        if stages and control.get("stage") not in stages:
            problems.append(f"{cid} names no lifecycle stage of the RAIMS table")
        if control.get("formerly") and not FORMER_ID.match(control["formerly"]):
            problems.append(f"{cid} gives {control['formerly']!r} as its former number")
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
    # What remains of each requirement for an organisation must be an action someone can take.
    from eli_legal.governance.compliance import check_actions, load_actions

    if not (governance / REGISTER_FILES["actions"]).is_file():
        return [*problems, f"missing register: {REGISTER_FILES['actions']}"]
    problems += check_actions(
        load_actions(governance), _rows(governance / "requirements_register.csv")
    )
    return problems
