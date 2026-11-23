import json
from pathlib import Path

import pytest

from eli_legal.domain.enums import ClaimKind, ClaimStatus, ReviewDecision
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.errors import (
    AuditIntegrityError,
    InvalidInput,
    InvalidState,
    VerificationGateFailed,
)
from eli_legal.domain.models import VerificationResult
from eli_legal.security.db_key import open_existing
from eli_legal.workflows.case_preparation import warning_id
from tests.conftest import case_text

A, S = "arb.keane", "sec.byrne"


def test_the_whole_lifecycle_from_ingestion_to_approved_release(lifecycle):
    assert lifecycle.first_status == "held"
    assert lifecycle.final_status == "approved_for_reliance"
    assert "ALLOWED" not in lifecycle.refusals.values(), lifecycle.refusals
    assert set(lifecycle.refusals) == {
        "approve a held run",
        "secretary resolves a hold",
        "administrator opens the matter",
        "secretary restarts the run",
        "approve without acknowledging the stated limits",
        "secretary approves",
        "send the tribunal's memorandum to a party",
    }
    steps = {s["step"]: s["status"] for s in lifecycle.summary["steps"]}
    assert all(
        status == "ok"
        for step, status in steps.items()
        if step
        not in {"human_review", "prepare_release", "recipient_approval", "controlled_delivery"}
    )
    assert Path(lifecycle.report_path).name.endswith("_approved.md")


def test_approved_report_is_the_reviewed_draft_with_only_its_banner_changed(lifecycle):
    from eli_legal.security.sealed import FileKeys, SealedFiles

    # ELI Legal's own copies are sealed; the demo handed its runner a readable one.
    files = SealedFiles(
        FileKeys(lifecycle.root / "secrets" / "file_keys"), lifecycle.root / "artifacts"
    )
    kept = Path(lifecycle.summary["report"]["path"])
    draft = kept.with_name(kept.name.replace("_approved", ""))
    a = Path(lifecycle.report_path).read_text(encoding="utf-8")
    assert a.encode("utf-8") == files.read(lifecycle.matter_id, kept), "handed over exactly"
    d = files.read(lifecycle.matter_id, draft).decode("utf-8")
    # The demonstration is a practice matter: one status, never "approved for reliance".
    assert "PRACTICE REVIEW COMPLETE — NOT FOR RELIANCE.** Reviewed by Aoife Keane (arb.keane)" in a
    assert "APPROVED FOR RELIANCE" not in a
    assert "PRACTICE MATTER — DRAFT, NOT FOR RELIANCE" in d and "PRACTICE MATTER — DRAFT" not in a
    assert a.split("## 1. Matter")[1] == d.split("## 1. Matter")[1]


def test_the_report_keeps_failed_authorities_visible_and_out_of_the_reliable_sections(lifecycle):
    text = Path(lifecycle.report_path).read_text(encoding="utf-8")
    relied, not_relied = text.split("## 6. Findings not to be relied on")
    not_relied = not_relied.split("## 7.")[0]
    assert "[2011] XXSC 14" in not_relied and "[2019] XXSC 99" in not_relied
    assert "[2011] XXSC 14" not in relied.split("## 5. Authorities relied on by the parties")[1]
    assert "has not checked that an authority supports the proposition" in text
    assert (
        "“14 days” appears in the party's sentence but not in this passage" in text
    )  # 14 days cited; the Act in force says 30


def test_evidence_pack_accounts_for_the_run(lifecycle):
    pack = Path(lifecycle.evidence_pack)
    manifest = json.loads((pack / "MANIFEST.json").read_text(encoding="utf-8"))
    for name in (
        "run.json",
        "document_manifest.json",
        "claims.json",
        "verifications.json",
        "holds.json",
        "reviews.json",
        "audit_events.jsonl",
        "audit_verification.json",
        "configuration.json",
    ):
        assert name in manifest["files"]
    verification = json.loads((pack / "audit_verification.json").read_text(encoding="utf-8"))
    assert (
        verification["chain_ok"]
        and verification["run_record_complete"]
        and verification["gaps"] == []
    )
    documents = json.loads((pack / "document_manifest.json").read_text(encoding="utf-8"))
    assert all(set(d) >= {"sha256", "ingested_by", "status"} and "text" not in d for d in documents)
    events = [
        json.loads(line)
        for line in (pack / "audit_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    kinds = {e["event_type"] for e in events}
    assert {
        "run_started",
        "step_completed",
        "hold_raised",
        "hold_resolved",
        "human_verification",
        "run_restarted",
        "review_decision",
        "release_prepared",
        "delivery_receipt",
    } <= kinds
    assert not any("Harbour Freight" in json.dumps(e) for e in events), (
        "the ledger holds ids and hashes, not content"
    )


def test_held_claims_close_only_by_passing_checks_or_by_a_named_exclusion(held_run):
    sv, mid, rid = held_run
    hold = next(
        h for h in sv.holds.list(mid, rid, actor_id=A) if h.reason_code == "verification_failed"
    )
    with pytest.raises(InvalidState):
        sv.holds.resolve(
            mid, hold.hold_id, actor_id=A, action="waive", reason="waiving a failed authority"
        )
    with pytest.raises(InvalidInput):
        sv.holds.resolve(mid, hold.hold_id, actor_id=A, action="exclude", reason="no")
    sv.holds.resolve(
        mid, hold.hold_id, actor_id=A, action="exclude", reason="Overruled; not to be relied on."
    )
    claim = next(
        c for c in sv.verification.claims(mid, rid, actor_id=A) if c.claim_id == hold.subject_id
    )
    assert claim.status is ClaimStatus.EXCLUDED and "arb.keane" in claim.status_reason


def test_overriding_a_failed_check_needs_the_override_permission_and_is_recorded(held_run):
    sv, mid, rid = held_run
    sv.users.add_user(
        actor_id="admin", user_id="rev.shaw", display_name="L Shaw", roles=["reviewer"]
    )
    sv.matters.grant(mid, actor_id=A, user_id="rev.shaw")
    overruled = next(
        c for c in sv.verification.claims(mid, rid, actor_id=A) if c.citation == "[2011] XXSC 14"
    )
    kwargs = dict(
        verification_type="current_law",
        status=V.VERIFIED,
        reason="The treatment table entry is wrong; checked the judgment itself.",
    )
    from eli_legal.domain.errors import PolicyDenied

    with pytest.raises(PolicyDenied):
        sv.verification.record_human_result(mid, overruled.claim_id, actor_id="rev.shaw", **kwargs)
    result = sv.verification.record_human_result(mid, overruled.claim_id, actor_id=A, **kwargs)
    assert result.override and result.by_human and result.verifier == "human:arb.keane"
    siblings = [
        c for c in sv.verification.claims(mid, rid, actor_id=A) if c.citation == "[2011] XXSC 14"
    ]
    assert len(siblings) > 1 and all(c.status is ClaimStatus.VERIFIED for c in siblings), (
        "one decision per authority"
    )
    snapshot = sv.monitoring.snapshot(actor_id="gov.hale")
    assert snapshot.overrides >= 1 and any("overrode the system" in a for a in snapshot.alerts)


def _to_review(sv, mid, rid):
    for hold in sv.holds.list(mid, rid, actor_id=A):
        if hold.hold_id not in {h.hold_id for h in sv.holds.list(mid, rid, actor_id=A)}:
            continue
        action = "waive" if hold.reason_code == "coverage_gap" else "exclude"
        sv.holds.resolve(
            mid,
            hold.hold_id,
            actor_id=A,
            action=action,
            reason="Resolved for the purposes of this test.",
        )
    sv.runs.resume(mid, rid, actor_id=A, reason="Holds resolved; rebuild the report.")
    summary = sv.runs.summary(mid, rid, actor_id=A)
    assert summary["status"] == "awaiting_human_review"
    return summary["report"]


def _approve(sv, mid, rid, report):
    return sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Checked against the papers.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )


def test_restart_reproduces_findings_and_keeps_human_decisions(held_run):
    sv, mid, rid = held_run
    before = {c.claim_id: c for c in sv.verification.claims(mid, rid, actor_id=A)}
    report = _to_review(sv, mid, rid)
    after = {c.claim_id: c for c in sv.verification.claims(mid, rid, actor_id=A)}
    kept = [cid for cid in after if cid in before]
    assert len(kept) >= len(after) - 5, "re-running reproduces the same findings under the same ids"
    assert [c.status for c in after.values() if c.citation == "[2011] XXSC 14"] == [
        ClaimStatus.EXCLUDED,
        ClaimStatus.EXCLUDED,
    ]
    assert report["version"] == 2
    assert not any(c.evidence and "exhibit_c7" in c.text.lower() for c in after.values())


def test_a_report_edited_on_disk_cannot_be_approved(held_run):
    sv, mid, rid = held_run
    report = _to_review(sv, mid, rid)
    path = Path(report["path"])
    path.chmod(0o600)
    path.write_text(  # replaced on disk with an altered copy
        case_text(sv, path).replace("not of the essence", "of the essence"), encoding="utf-8"
    )
    with pytest.raises(AuditIntegrityError, match="no longer matches"):
        _approve(sv, mid, rid, report)


def test_findings_changed_after_the_draft_block_approval(held_run):
    sv, mid, rid = held_run
    report = _to_review(sv, mid, rid)
    claim = next(
        c
        for c in sv.verification.claims(mid, rid, actor_id=A)
        if c.kind is ClaimKind.FACT and c.status is ClaimStatus.VERIFIED
    )
    claim.text = claim.text + " (altered)"
    sv.ctx.store.put(claim)
    with pytest.raises(VerificationGateFailed, match="changed after the draft"):
        _approve(sv, mid, rid, report)


def test_verification_results_altered_in_the_store_are_caught_by_the_completeness_check(held_run):
    sv, mid, rid = held_run
    report = _to_review(sv, mid, rid)
    forged = sv.ctx.store.list(VerificationResult, mid, run_id=rid)[0]
    with open_existing(sv.ctx.settings.db_path, sv.ctx.settings.audit_key_file) as con:
        con.execute(
            "UPDATE verifications SET data = replace(data, '\"verified\"', '\"failed\"') WHERE id = ?",
            (forged.verification_id,),
        )
    with pytest.raises(VerificationGateFailed, match="incomplete"):
        _approve(sv, mid, rid, report)


def test_stop_and_reject_and_return(held_run):
    sv, mid, rid = held_run
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    review = sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.RETURN_FOR_CORRECTION,
        reasons="Deal with the cited authorities first.",
        report_hash=report["sha256"],
    )
    assert review.decision is ReviewDecision.RETURN_FOR_CORRECTION
    assert sv.runs.get(mid, rid, actor_id=A).status.value == "returned_for_correction"
    assert sv.runs.stop(mid, rid, actor_id=A, reason="Hearing vacated.").status.value == "stopped"
    with pytest.raises(VerificationGateFailed):
        _approve(sv, mid, rid, report)
