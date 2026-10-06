import csv
from pathlib import Path

from eli_legal.governance.registers import check_registers

ROOT = Path(__file__).resolve().parents[2]


def test_governance_registers_match_the_code():
    assert check_registers(ROOT) == []


def test_the_check_catches_a_register_that_drifts_from_the_code(tmp_path):
    for sub in ("governance", "src/eli_legal", "tests"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "tests" / "test_x.py").write_text("def test_real():\n    pass\n")
    (tmp_path / "src/eli_legal/real.py").write_text("")
    rows = {
        "control_register.csv": [
            ["control_id", "control", "type", "implementation", "tests", "evidence", "owner_role"],
            ["C-01", "a control", "prevent", "missing.py", "test_imaginary", "e", "provider"],
            ["C-02", "unreferenced", "prevent", "real.py", "test_real", "e", "provider"],
        ],
        "risk_register.csv": [
            [
                "risk_id",
                "risk",
                "cause",
                "event",
                "impact",
                "control_ids",
                "residual_risk_and_limits",
                "owner_role",
                "status",
            ],
            ["R-01", "r", "c", "e", "i", "C-01;C-99", "some", "provider", "treated"],
        ],
        "requirements_register.csv": [
            [
                "requirement_id",
                "instrument",
                "reference",
                "addressed_to",
                "requirement_in_plain_words",
                "control_ids",
                "status",
                "how_met_and_what_remains",
            ],
            ["Q-01", "law", "Art. 1", "provider", "words", "", "implemented", "x"],
        ],
    }
    for name, content in rows.items():
        with open(tmp_path / "governance" / name, "w", newline="") as handle:
            csv.writer(handle).writerows(content)
    problems = check_registers(tmp_path)
    assert "C-01 points at src/eli_legal/missing.py, which does not exist" in problems
    assert "C-01 names test test_imaginary, which does not exist" in problems
    assert "R-01 refers to unknown control C-99" in problems
    assert "Q-01 is marked implemented but names no control" in problems
    assert "C-02 is not linked to any risk or requirement" in problems
