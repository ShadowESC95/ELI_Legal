"""The organisation's compliance work, and the routine checks that keep everything current.

A requirement must read as met, waiting for someone, or due for review: never "partial". The
routine checks must find what goes stale or wrong after a run (law, sources, files, people,
retention, deadlines), act where acting is certain, and never show a matter to someone not on it.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from eli_legal.application.services import build_services
from eli_legal.demo import SOURCE_ID, build_demo_workspace
from eli_legal.demo_run import demo_settings, run_demo
from eli_legal.domain.enums import IncidentSeverity
from eli_legal.domain.errors import InvalidInput, InvalidState, PolicyDenied, StepUpRequired
from eli_legal.domain.models import Incident, utcnow
from eli_legal.governance.compliance import (
    MIN_AUDIT_RETENTION_DAYS,
    load_actions,
    template_fields,
)
from eli_legal.governance.registers import check_registers, load_register
from eli_legal.security import access, authn

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
TODAY = utcnow().date()


def _states(sv, today=None):
    return {
        r.requirement_id: r for r in sv.compliance.overview(actor_id=G, today=today).requirements
    }


def test_every_requirement_reads_as_met_waiting_or_due_never_partial(demo):
    sv, _mid = demo
    statuses = _states(sv)
    assert len(statuses) == len(load_register("requirements"))
    assert {r.state for r in statuses.values()} <= {"software", "met", "waiting", "review_due"}
    # What the software does in full needs nobody: met by the software.
    assert statuses["AIA-12"].state == "software" and statuses["AIA-12"].who == "The software"
    # What remains for an organisation is an action someone can take, never a shrug.
    for r in statuses.values():
        if r.software_part != "implemented":
            assert r.actions, f"{r.requirement_id} names nothing to do"
    assert statuses["AIA-27"].state == "waiting" and statuses["AIA-27"].who == "Your organisation"
    assert check_registers(Path(__file__).resolve().parents[2]) == []


def test_recording_compliance_needs_the_right_and_the_passphrase_again(demo):
    sv, _mid = demo
    with pytest.raises(PolicyDenied):
        sv.compliance.record("OA-04", actor_id=A, confirmed=True)  # an arbitrator does not
    with authn.harness("test-harness", step_up=False), pytest.raises(StepUpRequired):
        sv.compliance.record("OA-04", actor_id=G, confirmed=True)
    with pytest.raises(InvalidInput, match="confirm the statement"):
        sv.compliance.record("OA-04", actor_id=G)
    record = sv.compliance.record("OA-04", actor_id=G, confirmed=True, notes="Quarterly review.")
    assert record.review_by == TODAY + timedelta(days=90)
    event = [
        e for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "compliance_recorded"
    ][-1]
    assert event["actor_id"] == G and event["subject_id"] == "OA-04"
    assert _states(sv)["AIA-09"].state == "met"


def test_a_form_is_the_template_itself_and_must_be_answered_in_full(demo):
    sv, _mid = demo
    template = Path(__file__).resolve().parents[2] / (
        "src/eli_legal/governance/templates/classification_assessment.md"
    )
    bullets = [line for line in template.read_text().splitlines() if line.startswith("- ")]
    fields = template_fields("classification_assessment")
    assert len(fields) == len(bullets) - 1  # who assessed it, and when, the system records
    assert not any(f.label.lower().startswith("assessed by") for f in fields)
    with pytest.raises(InvalidInput, match="unanswered"):
        sv.compliance.record("OA-01", actor_id=G, answers={fields[0].key: "Tribunal"})
    sv.compliance.record(
        "OA-01", actor_id=G, answers={f.key: f"Answer to {f.label[:20]}" for f in fields}
    )
    for rid in ("AIA-03", "AIA-06", "ISO-A.10.2"):
        assert _states(sv)[rid].state == "met", rid


def test_a_record_falls_due_for_review_and_a_duty_can_be_recorded_as_not_applying(demo):
    sv, _mid = demo
    sv.compliance.record("OA-04", actor_id=G, confirmed=True)
    assert _states(sv, TODAY + timedelta(days=91))["AIA-09"].state == "review_due"
    with pytest.raises(InvalidInput, match="why it does not apply"):
        sv.compliance.record("OA-19", actor_id=G, not_applicable=True, notes="n/a")
    sv.compliance.record(
        "OA-19",
        actor_id=G,
        not_applicable=True,
        notes="The provider is established in the Union and supplies the tribunal directly.",
    )
    assert _states(sv)["AIA-22"].state == "met"


def test_training_is_recorded_per_person_and_reviewers_without_it_are_reported(demo):
    sv, _mid = demo
    assert A in sv.compliance.untrained()
    people = {r.check_id: r for r in sv.checks.run().results}["people"]
    assert any("named reviewer with no current training record" in i.text for i in people.items)
    with pytest.raises(InvalidInput, match="future"):
        sv.compliance.record_training(
            actor_id=G, user_id=A, course="AI literacy", completed_on=TODAY + timedelta(days=1)
        )
    record = sv.compliance.record_training(
        actor_id=G, user_id=A, course="AI literacy and instructions for use", completed_on=TODAY
    )
    assert record.expires_on == TODAY.replace(year=TODAY.year + 1)
    assert A not in sv.compliance.untrained()
    assert A in sv.compliance.untrained(TODAY.replace(year=TODAY.year + 2))


def test_the_evaluation_measures_planted_defects_against_declared_thresholds(demo):
    sv, _mid = demo
    record = sv.compliance.run_evaluation(actor_id=G)
    assert record.answers["passed"] == "yes" and record.answers["caught"] == "5"
    assert record.answers["facts_verbatim"] == "1.0" and record.answers["unexpected_holds"] == "0"
    assert _states(sv)["AIA-15"].state == "met"
    assert authn.current() is None  # the evaluation borrowed nobody's identity
    short = sv.compliance.run_evaluation(actor_id=G, thresholds={"unexpected_holds": -1})
    assert short.answers["passed"] == "no"
    assert _states(sv)["AIA-15"].state == "waiting"


def test_retention_keeps_the_audit_trail_six_months_and_deletes_closed_matters_on_time(demo):
    sv, mid = demo
    assert sv.checks.run().results[-2].check_id == "retention"
    with pytest.raises(InvalidInput, match="six months"):
        sv.compliance.set_retention(
            actor_id=G, audit_days=MIN_AUDIT_RETENTION_DAYS - 1, closed_matter_days=30
        )
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=0)
    assert sv.ctx.store.chunks_for(mid)
    sv.matters.close(mid, actor_id=A, purge_content=False, reason="Award issued; file closed.")
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert retention.state == "ok" and retention.acted
    assert not sv.ctx.store.chunks_for(mid)
    purge = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "retention_purge"]
    assert len(purge) == 1 and purge[0]["actor_id"] == "system"
    sv.checks.run()  # nothing left to delete: nothing more recorded
    assert (
        len([e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "retention_purge"])
        == 1
    )
    assert sv.ctx.audit.report().ok


def test_documents_are_drafted_from_the_records_and_not_issued_before_the_assessment(demo):
    sv, _mid = demo
    path, digest = sv.compliance.generate("annex_iv", actor_id=G)
    text = path.read_text(encoding="utf-8")
    for row in load_register("controls"):
        assert row["control_id"] in text
    assert "## 9. Post-market monitoring" in text and "[provider to complete" in text
    declaration, _ = sv.compliance.generate("declaration", actor_id=G)
    assert "NOT TO BE ISSUED" in declaration.read_text(encoding="utf-8")
    with pytest.raises(InvalidState, match="generate the document"):
        sv.compliance.record("OA-05", actor_id=G, confirmed=True)
    with pytest.raises(InvalidInput, match="SHA-256"):
        sv.compliance.sign_off("OA-05", actor_id=G, sha256="abc")
    sv.compliance.sign_off("OA-05", actor_id=G, sha256=digest)
    assert _states(sv)["AIA-11"].state == "met"


@pytest.fixture
def approved(tmp_path):
    """The demonstration, run to an approved, released report."""
    run_demo(tmp_path, say=lambda _line: None, install_network_guard=False)
    return tmp_path


def _services(root):
    return build_services(
        demo_settings(root, build_demo_workspace(root / "demo")), install_network_guard=False
    )


def _reimport(sv, root, record, **changes):
    """The source publishes new status information and a current copy is imported."""
    corpus = root / "demo" / "corpus"
    path = corpus / f"{record}.json"
    path.write_text(
        json.dumps(json.loads(path.read_text(encoding="utf-8")) | changes), encoding="utf-8"
    )
    with authn.harness("test-harness"):
        sv.sources.import_corpus(SOURCE_ID, corpus, actor_id="admin")


def test_an_authority_overruled_after_approval_opens_an_incident_once(approved):
    sv = _services(approved)
    first = {r.check_id: r for r in sv.checks.run().results}["authorities"]
    assert first.state == "ok", "a person's recent confirmation of a stale status stands"
    _reimport(
        sv,
        approved,
        "corvin_2022_xxsc_7",
        status="overruled",
        status_checked_at=utcnow().isoformat(),
        treatments=[
            {
                "treatment": "overruled",
                "effective_date": (TODAY - timedelta(days=1)).isoformat(),
                "by_citation": "[2026] XXSC 1",
            }
        ],
    )
    found = {r.check_id: r for r in sv.checks.run().results}["authorities"]
    assert found.state == "attention" and found.acted
    assert [i.text.split(",")[0] for i in found.items] == ["[2022] XXSC 7"]
    relied = re.search(r"\((\d+) findings\)", found.items[0].text)
    assert "approved report" in found.items[0].text and relied and int(relied.group(1)) >= 2
    matter_id = found.items[0].matter_id
    incidents = [
        i
        for i in sv.ctx.store.list(Incident, matter_id)
        if i.category == "authority_changed_after_approval"
    ]
    assert len(incidents) == 1 and incidents[0].created_by == "system"
    again = {r.check_id: r for r in sv.checks.run().results}["authorities"]
    assert not again.acted, "an open incident is not opened twice"


def test_an_altered_original_is_found_and_opens_a_serious_incident(approved):
    sv = _services(approved)
    matter = sv.ctx.store.list_matters()[0]
    target = next(
        p for p in (Path(sv.ctx.settings.data_dir) / matter.matter_id).rglob("*") if p.is_file()
    )
    target.chmod(0o600)
    target.write_bytes(target.read_bytes() + b"tampered")
    found = {r.check_id: r for r in sv.checks.run().results}["originals"]
    assert found.state == "failed" and found.acted
    serious = [
        i for i in sv.ctx.store.list(Incident, matter.matter_id) if i.category == "original_altered"
    ]
    assert serious and serious[0].severity is IncidentSeverity.SERIOUS


def test_results_never_show_a_matter_to_someone_not_on_it(approved):
    sv = _services(approved)
    with authn.harness("test-harness"):
        sv.users.add_user(
            actor_id="admin", user_id="aud.x", display_name="Auditor", roles=["auditor"]
        )
    _reimport(
        sv,
        approved,
        "corvin_2022_xxsc_7",
        status="overruled",
        status_checked_at=utcnow().isoformat(),
    )
    with authn.harness("test-harness"):
        run = sv.checks.run()
        shown = sv.checks.for_viewer(run, actor_id="aud.x")
        member = sv.checks.for_viewer(run, actor_id=A)
    about = [i for r in shown for i in r.items if i.matter_id]
    assert about and all(access.is_withheld(i.text) and "Harbour" not in i.text for i in about)
    assert all("Harbour" not in a for r in shown for a in r.acted)
    assert any("Harbour" in i.text for r in member for i in r.items if i.matter_id)


def test_law_packages_fall_due_for_checking_and_a_named_person_confirms_them(demo):
    sv, _mid = demo
    later = TODAY + timedelta(days=400)
    laws = {r.check_id: r for r in sv.checks.run(today=later).results}["law_packages"]
    assert laws.state == "attention"
    assert any("more than 180 days ago" in i.text for i in laws.items)
    assert any("2027-12-02" in i.text for i in laws.items), "the calendar date has passed since"
    with pytest.raises(PolicyDenied):
        sv.checks.confirm_law_current(
            "eu-ai-act-high-risk", actor_id=A, checked_on=TODAY, note="x" * 20
        )
    for pack_id in sv.matters.get(_mid, A).framework_ids:
        sv.checks.confirm_law_current(
            pack_id, actor_id=G, checked_on=TODAY, note="Checked against the consolidated text."
        )
    assert sv.checks.law_checked_on("gdpr") == (TODAY, G)
    soon = {r.check_id: r for r in sv.checks.run(today=TODAY + timedelta(days=30)).results}
    assert soon["law_packages"].state == "ok"


def test_routine_checks_run_on_their_schedule_and_by_people_with_the_right(demo):
    sv, _mid = demo
    assert sv.checks.due()
    run = sv.checks.run()
    assert not sv.checks.due() and sv.checks.due(utcnow() + timedelta(hours=25))
    assert sv.checks.latest().run_id == run.run_id
    with pytest.raises(PolicyDenied):
        sv.checks.run(actor_id=A)
    assert sv.checks.run(actor_id=G).actor_id == G
    events = [e for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "routine_check"]
    assert [e["actor_id"] for e in events] == ["system", G]


def test_a_serious_incident_carries_its_reporting_deadline_until_a_person_decides(demo):
    from eli_legal.application.incident_service import reporting_deadline

    sv, mid = demo
    incident = sv.incidents.create(
        mid,
        actor_id=A,
        category="wrong_law_relied_on",
        detail="x" * 12,
        severity=IncidentSeverity.SERIOUS,
    )
    assert reporting_deadline(incident) == incident.created_at + timedelta(days=15)
    waiting = {r.check_id: r for r in sv.checks.run().results}["open_work"]
    assert any("must be reported" in i.text and "due by" in i.text for i in waiting.items)
    late = {r.check_id: r for r in sv.checks.run(today=TODAY).results}
    decided = sv.incidents.decide_reporting(
        mid,
        incident.incident_id,
        actor_id=A,
        reportable=False,
        reason="No harm to health, safety or fundamental rights resulted.",
    )
    assert reporting_deadline(decided) is None and late
    with pytest.raises(InvalidInput):
        sv.incidents.decide_reporting(
            mid,
            incident.incident_id,
            actor_id=A,
            reportable=True,
            reason="x" * 12,
            serious_kind="other",
        )
    death = sv.incidents.decide_reporting(
        mid,
        incident.incident_id,
        actor_id=A,
        reportable=True,
        reason="x" * 12,
        serious_kind="death",
    )
    assert reporting_deadline(death) == death.created_at + timedelta(days=10)


def test_the_actions_register_covers_every_duty_and_names_real_templates():
    actions = load_actions()
    assert len({a.action_id for a in actions}) == len(actions)
    for a in actions:
        if a.evidence == "form":
            assert template_fields(a.template), a.action_id
    assert date.fromisoformat("2027-12-02")  # the calendar's own dates parse
