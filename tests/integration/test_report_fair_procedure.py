"""An authority the system found that no party cited is new to the dispute. The report must say
which those are, so a decision-maker does not rely on one without hearing the parties on it."""

import hashlib
from pathlib import Path

from eli_legal.application.services import build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import demo_settings, setup_demo
from tests.conftest import ARBITRATOR, SECRETARY


def _research_rows(text: str) -> list[list[str]]:
    rows, inside = [], False
    for line in text.splitlines():
        if line.startswith("**Authorities located in the approved sources**"):
            inside = True
        elif inside and line.startswith(("**", "#")):
            inside = False
        elif (
            inside
            and line.startswith("| ")
            and "---" not in line
            and "Cited by a party" not in line
        ):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def _report(sv, mid, rid) -> str:
    report = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)["report"]
    return Path(report["path"]).read_text(encoding="utf-8")


def test_an_authority_a_party_cites_is_marked_as_cited(held_run):
    sv, mid, rid = held_run
    text = _report(sv, mid, rid)
    assert "| Cited by a party |" in text
    marks = {row[1]: row[-1] for row in _research_rows(text)}
    assert marks["[2022] XXSC 7"] == "yes", "the Respondent cites this one in its defence"


def test_an_authority_no_party_cited_is_flagged_for_the_parties_to_address(tmp_path):
    """Without the defence, nobody has cited the authority the Respondent would rely on. The
    system still finds it. A decision-maker must be told it is new to the dispute."""
    workspace = build_demo_workspace(tmp_path / "demo")
    workspace.filing.pop("02_defence.txt")
    sv = build_services(demo_settings(tmp_path, workspace), install_network_guard=False)
    mid = setup_demo(sv, workspace)
    run = sv.runs.start(mid, actor_id=SECRETARY)
    claims = sv.verification.claims(mid, run.run_id, actor_id=ARBITRATOR)
    cited = {c.citation for c in claims if c.kind.value == "party_authority"}
    assert "[2022] XXSC 7" not in cited
    marks = {row[1]: row[-1] for row in _research_rows(_report(sv, mid, run.run_id))}
    assert "put it to the parties before relying on it" in marks["[2022] XXSC 7"]
    assert all(mark == "yes" for citation, mark in marks.items() if citation in cited)


def test_a_report_on_disk_is_byte_for_byte_what_was_hashed(held_run):
    """The recorded hash is of the file's bytes. A text-mode write would change the line endings
    on Windows, and every later comparison with the hash would then fail."""
    sv, mid, rid = held_run
    report = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)["report"]
    raw = Path(report["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["sha256"]
    assert b"\r\n" not in raw
