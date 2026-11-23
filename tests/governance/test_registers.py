from pathlib import Path

from eli_legal.governance import registers
from eli_legal.governance.registers import check_registers, load_register

ROOT = Path(__file__).resolve().parents[2]


def test_governance_registers_match_the_code():
    assert check_registers(ROOT) == []


def test_registers_ship_with_the_package_and_load():
    assert len(load_register("controls")) >= 28
    assert {r["status"] for r in load_register("requirements")} == {
        "implemented",
        "partial",
        "organisational",
    }
    assert load_register("risks") and load_register("responsibilities")
    assert check_registers(None) == [], (
        "an installed copy can still check everything but test names"
    )


def test_the_check_catches_a_register_that_drifts_from_the_code(tmp_path, monkeypatch):
    import csv

    fake = tmp_path / "registers"
    fake.mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_real():\n    pass\n", encoding="utf-8")
    rows = {
        "control_register.csv": [
            ["control_id", "control", "type", "implementation", "tests", "evidence", "owner_role"],
            ["DG-01.1", "a control", "prevent", "missing.py", "test_imaginary", "e", "provider"],
            ["DG-01.2", "unreferenced", "prevent", "cli.py", "test_real", "e", "provider"],
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
            ["R-01", "r", "c", "e", "i", "DG-01.1;C-99", "some", "provider", "treated"],
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
        with open(fake / name, "w", newline="") as handle:
            csv.writer(handle).writerows(content)
    monkeypatch.setattr(registers, "REGISTER_DIR", fake)
    problems = check_registers(tmp_path)
    assert "DG-01.1 points at src/eli_legal/missing.py, which does not exist" in problems
    assert "DG-01.1 names test test_imaginary, which does not exist" in problems
    assert "R-01 refers to unknown control C-99" in problems
    assert "Q-01 is marked implemented but names no control" in problems
    assert "DG-01.2 is not linked to any risk or requirement" in problems
    assert "missing register: organisation_actions.csv" in problems
    with open(fake / "organisation_actions.csv", "w", newline="") as handle:
        csv.writer(handle).writerows(
            [
                [
                    "action_id",
                    "title",
                    "what_to_do",
                    "requirement_ids",
                    "owner",
                    "evidence",
                    "template",
                    "statement",
                    "review_days",
                    "before_real_use",
                ],
                ["OA-01", "t", "w", "Q-99", "provider", "attestation", "", "", "30", "no"],
                ["OA-02", "t", "w", "Q-01", "provider", "form", "no_such_template", "", "30", "no"],
            ]
        )
    problems = check_registers(tmp_path)
    assert "OA-01 refers to unknown requirement Q-99" in problems
    assert "OA-01 needs the statement a person confirms" in problems
    assert "OA-02 names template 'no_such_template', which has no questions" in problems


def test_the_product_liability_directive_is_dated_as_corrected_in_the_official_journal():
    """Article 2(1) of Directive (EU) 2024/2853 was corrected on 7 May 2026 (OJ L 2026/90364):
    it applies to products placed on the market or put into service after 8 December 2026, not
    after 9 December, which had left products placed on 9 December under neither directive."""
    [pld] = [r for r in load_register("requirements") if r["requirement_id"] == "PLD-01"]
    assert "after 8 December 2026" in pld["reference"] and "2026/90364" in pld["reference"]
    for path in (ROOT / "docs").rglob("*.md"):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "after 9 December 2026" not in text, path.name


def test_controls_are_identified_by_the_five_raims_controls_with_their_former_numbers():
    """RAIMS Week 5: RM-01, HO-01, TR-01, MO-01, DG-01, each with its minimum evidence, owner and
    when; every control of the system is a numbered part of one, placed at a stage of the RAIMS
    lifecycle, and keeps its former number so earlier records and packages still resolve."""
    families = {f["family_id"]: f for f in load_register("families")}
    assert list(families) == ["RM-01", "HO-01", "TR-01", "MO-01", "DG-01"]
    assert families["HO-01"]["minimum_evidence_fields"].startswith("Reviewer ID; report hash")
    assert families["DG-01"]["what_it_needs"] == "The approved source, and three separate checks."
    stages = [s["stage"] for s in load_register("lifecycle")]
    assert stages == [
        "Intake",
        "Design",
        "Development",
        "Testing",
        "Deployment",
        "Monitoring",
        "Retirement",
    ]
    controls = load_register("controls")
    assert all(registers.CONTROL_ID.match(c["control_id"]) for c in controls)
    assert all(c["stage"] in stages for c in controls)
    assert all(c["formerly"].startswith("C-") for c in controls if c["formerly"]), "or new"
    assert {registers.family_of(c["control_id"]) for c in controls} == set(families)
    assert registers.current_control_id("C-14") == "HO-01.2"
    assert registers.current_control_id("HO-01.2") == "HO-01.2"
    assert registers.current_control_id("C-99") == "C-99", "an unknown number is left to fail"


def test_a_package_written_with_former_control_numbers_still_loads():
    from eli_legal.legal.frameworks import requirement_from

    requirement = requirement_from(
        {
            "id": "P-1",
            "title": "Named review",
            "text": "A named person approves the exact report.",
            "effect": "enforced",
            "controls": ["C-14", "C-15"],
        }
    )
    assert requirement.controls == ("HO-01.2", "HO-01.3")
