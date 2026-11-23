"""Reports released to me: each recipient is told, finds the report in the application or the
browser, reads it, and takes a copy as PDF, Word or Markdown, stamped with their name. Nobody
else can; a recipient who leaves the matter, a suspended report or an altered file stops it; and
every reading and copy is in the audit trail."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eli_legal.adapters.local.renditions import ensure_typesetter
from eli_legal.api.app import create_app
from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import RelianceBlock
from eli_legal.domain.release import ReleasePackage
from eli_legal.workflows.case_preparation import warning_id

A, S = "arb.keane", "sec.byrne"


@pytest.fixture
def released(held_run):
    """The demo matter, approved and released to the arbitrator and the registrar."""
    sv, mid, rid = held_run
    resolve_demo_holds(sv, mid, rid)
    sv.runs.resume(mid, rid, actor_id=A, reason="All holds resolved; rebuild the report.")
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Checked each finding against its source; the stated limits are accepted.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )
    package = sv.releases.prepare(
        mid,
        rid,
        actor_id=A,
        recipients=[(A, "Aoife Keane", "collect"), (S, "Tom Byrne", "collect")],
    )
    sv.delivery.distribute(mid, package.release_id, actor_id=A, confirmed_recipient_ids=[A, S])
    return sv, mid, rid, package.release_id


def _events(sv, kind):
    return [e for e in sv.ctx.audit.events() if e["event_type"] == kind]


def test_each_recipient_is_told_and_finds_it_ready_to_collect(released):
    sv, mid, _rid, rel = released
    for uid in (A, S):
        notes = {n["kind"]: n for n in sv.notifications.inbox(uid)}
        assert notes["report_released"]["page"] == "released"
        mine = sv.released.mine(uid)
        assert [(r["release_id"], r["can_open"], r["collected"]) for r in mine] == [
            (rel, True, False)
        ]
    sv.users.add_user(
        actor_id="admin", user_id="judge.x", display_name="Other judge", roles=["judge"]
    )
    assert sv.released.mine("judge.x") == []
    assert sv.ctx.store.get(ReleasePackage, mid, rel).status == "delivery_attempted"


def test_a_copy_is_the_approved_report_stamped_with_who_collected_it(released):
    sv, mid, _rid, rel = released
    package = sv.ctx.store.get(ReleasePackage, mid, rel)
    name, data, media = sv.released.collect(mid, rel, A, "md")
    assert hashlib.sha256(data).hexdigest() == package.report_hash, "the approved text, unaltered"
    assert name.endswith(".md") and media.startswith("text/markdown")
    _name, docx, media = sv.released.collect(mid, rel, A, "docx")
    assert media.endswith("wordprocessingml.document")
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        body = z.read("word/document.xml").decode()
        assert {"[Content_Types].xml", "word/styles.xml"} <= set(z.namelist())
    assert "Collected by Aoife Keane (arb.keane)" in body and package.report_hash in body
    ensure_typesetter()
    _name, pdf, media = sv.released.collect(mid, rel, A, "pdf")
    assert media == "application/pdf" and pdf.startswith(b"%PDF")
    from pypdf import PdfReader

    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Collected by Aoife Keane" in text
    got = [(e["actor_id"], e["payload"]["format"]) for e in _events(sv, "report_collected")]
    assert got == [(A, "md"), (A, "docx"), (A, "pdf")]
    assert all(e["output_hash"] == package.report_hash for e in _events(sv, "report_collected"))
    assert "report_released" not in {n["kind"] for n in sv.notifications.inbox(A)}, "collected"
    assert "report_released" in {n["kind"] for n in sv.notifications.inbox(S)}, "not yet"
    assert sv.ctx.audit.report().ok


def test_nobody_else_collects_it_and_each_refusal_is_recorded(released):
    sv, mid, _rid, rel = released
    sv.users.add_user(
        actor_id="admin", user_id="sol.x", display_name="A solicitor", roles=["solicitor"]
    )
    sv.matters.grant(mid, actor_id=A, user_id="sol.x", party="Northwind Logistics Ltd")
    for uid in ("sol.x", "gov.hale", "admin"):
        with pytest.raises(NotFound):
            sv.released.collect(mid, rel, uid, "docx")
    refused = [e for e in _events(sv, "access_denied") if e["action"] == "report.collect"]
    assert {e["actor_id"] for e in refused} == {"sol.x", "gov.hale", "admin"}


def test_leaving_the_matter_a_suspension_or_an_altered_file_stops_collection(released):
    sv, mid, rid, rel = released
    sv.matters.revoke(mid, actor_id=A, user_id=S)
    assert sv.released.mine(S) == []
    with pytest.raises(PolicyDenied, match="no longer on this matter"):
        sv.released.collect(mid, rel, S, "md")

    block = RelianceBlock(
        matter_id=mid,
        run_id=rid,
        report_id="r",
        report_hash="h",
        cause="authority_changed_after_approval",
        recipient_ids=[A],
    )
    sv.ctx.store.put(block)
    [row] = sv.released.mine(A)
    assert not row["can_open"] and "suspended" in row["why_not"]
    with pytest.raises(PolicyDenied, match="suspended"):
        sv.released.collect(mid, rel, A, "md")
    block.status = "resolved"
    sv.ctx.store.put(block)

    package = sv.ctx.store.get(ReleasePackage, mid, rel)
    Path(package.artifact_ref).write_text("An altered report.", encoding="utf-8")
    with pytest.raises(InvalidState, match="no longer matches"):
        sv.released.collect(mid, rel, A, "docx")
    assert _events(sv, "report_integrity_failure")[-1]["actor_id"] == A


def test_the_browser_lists_and_downloads_only_what_was_released_to_you(released):
    sv, mid, _rid, rel = released
    tokens = {u: sv.users.issue_token(actor_id=u, user_id=u) for u in (A, "gov.hale")}
    client = TestClient(create_app(sv), base_url="http://localhost")
    mine = client.get("/v1/released", headers={"Authorization": f"Bearer {tokens[A]}"}).json()
    assert [r["release_id"] for r in mine] == [rel]
    got = client.get(
        f"/v1/matters/{mid}/released/{rel}?format=docx",
        headers={"Authorization": f"Bearer {tokens[A]}"},
    )
    assert got.status_code == 200 and got.content.startswith(b"PK")
    assert "attachment" in got.headers["content-disposition"]
    other = client.get(
        f"/v1/matters/{mid}/released/{rel}?format=md",
        headers={"Authorization": f"Bearer {tokens['gov.hale']}"},
    )
    assert other.status_code == 404
    assert (
        client.get("/v1/released", headers={"Authorization": f"Bearer {tokens['gov.hale']}"}).json()
        == []
    )


def test_the_journey_goes_on_to_collection_and_then_to_closing(released):
    sv, mid, _rid, rel = released
    guide = sv.guidance.for_matter(mid, actor_id=A)
    states = {s.key: s.state for s in guide.stages}
    assert (states["release"], states["collect"], states["close"]) == ("done", "current", "later")
    assert guide.steps[0].title == "Collect the report released to you" and guide.steps[0].can_do
    assert "Tom Byrne" in [s for s in guide.stages if s.key == "collect"][0].detail
    sv.matters.grant(mid, actor_id=A, user_id="gov.hale")  # on the matter, not a recipient
    other = sv.guidance.for_matter(mid, actor_id="gov.hale")
    collect = next(s for s in other.steps if s.title.startswith("Collect"))
    assert not collect.can_do and collect.who.startswith("Waiting for:")
    sv.released.collect(mid, rel, A, "md")
    sv.released.collect(mid, rel, S, "md")
    guide = sv.guidance.for_matter(mid, actor_id=A)
    states = {s.key: s.state for s in guide.stages}
    assert (states["collect"], states["close"]) == ("done", "current")
    assert any(s.title.startswith("Close the matter") and s.can_do for s in guide.steps)
    assert not [w for w in sv.guidance.my_work(actor_id=S) if w.page == "released"]
