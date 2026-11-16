"""EL-004: a preservation hold stops a matter's content being deleted, at closure or when its
retention period ends; a hold on named documents keeps only those; every disposal leaves a
receipt; only the legal or data-protection owner releases a hold, on a recorded reason."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eli_legal.application.preservation_service import PreservationHeld
from eli_legal.domain.errors import InvalidInput, PolicyDenied
from eli_legal.domain.models import Document, PreservationHold

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
BASIS = "Respondent's solicitors gave notice of a negligence claim on 12 November 2026."


def _events(sv, mid, kind):
    return [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == kind]


def _receipts(sv, mid):
    folder = Path(sv.ctx.settings.artifacts_dir) / "disposals" / mid
    return sorted(folder.glob("*.json")) if folder.exists() else []


def test_a_hold_on_the_matter_refuses_deletion_at_closure_and_when_retention_ends(demo):
    sv, mid = demo
    hold = sv.preservation.place(mid, actor_id=A, legal_basis=BASIS, authority="Tribunal chair")
    assert hold.scope == "matter" and hold.status == "active"
    with pytest.raises(PreservationHeld, match="preservation hold covers this matter"):
        sv.matters.close(mid, actor_id=A, purge_content=True, reason="Award issued; file closed.")
    assert sv.ctx.store.chunks_for(mid) and sv.ctx.vault.has_files(mid), "nothing deleted"
    assert sv.matters.get(mid, A).status.value != "closed", "refused before anything changed"
    assert _events(sv, mid, "disposal_refused")

    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=0)
    sv.matters.close(mid, actor_id=A, purge_content=False, reason="Award issued; file closed.")
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert not retention.acted and "kept" in retention.items[0].text
    assert sv.ctx.store.chunks_for(mid) and sv.ctx.vault.has_files(mid)
    assert not _receipts(sv, mid)

    with pytest.raises(PolicyDenied):
        sv.preservation.release(mid, hold.hold_id, actor_id=A, reason="The claim was settled; "
                                "no further preservation is needed.")  # fmt: skip
    with pytest.raises(InvalidInput):
        sv.preservation.release(mid, hold.hold_id, actor_id=G, reason="done")
    released = sv.preservation.release(
        mid, hold.hold_id, actor_id=G,
        reason="Claim settled by deed of 1 December 2026; preservation no longer required.",
    )  # fmt: skip
    assert released.status == "released" and released.released_by == G
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert retention.acted and not sv.ctx.store.chunks_for(mid) and not sv.ctx.vault.has_files(mid)
    [receipt] = _receipts(sv, mid)
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["deleted_originals_sha256"] and body["preservation_holds"] == [], "none in force"
    [event] = _events(sv, mid, "retention_purge")
    assert event["output_hash"] == body["manifest_sha256"], "the receipt matches the ledger"
    [kept] = sv.ctx.store.list(PreservationHold, mid)
    assert kept.status == "released", "the hold's record outlives the content it preserved"


def test_a_hold_on_named_documents_keeps_only_those(demo):
    sv, mid = demo
    documents = sv.ctx.store.list(Document, mid)
    kept, *rest = documents
    sv.preservation.place(mid, actor_id=G, legal_basis=BASIS, authority="Data-protection owner",
                          document_ids=[kept.document_id])  # fmt: skip
    counts = sv.matters.close(mid, actor_id=A, purge_content=True, reason="Award issued; closed.")
    assert counts["preserved_documents"] == 1 and counts["vault_files"] >= len(rest) - 1
    left = sv.ctx.store.list(Document, mid)
    assert [d.document_id for d in left] == [kept.document_id]
    assert sv.ctx.vault.read(mid, kept.sha256), "its original is kept"
    assert all(c.document_id == kept.document_id for c in sv.ctx.store.chunks_for(mid))
    [receipt] = _receipts(sv, mid)
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["preserved_document_ids"] == [kept.document_id]
    assert kept.sha256 not in body["deleted_originals_sha256"]


def test_placing_a_hold_needs_a_basis_and_the_right_person(demo):
    sv, mid = demo
    with pytest.raises(InvalidInput, match="what requires the hold"):
        sv.preservation.place(mid, actor_id=A, legal_basis="keep it", authority="me")
    with pytest.raises(InvalidInput, match="not documents of this matter"):
        sv.preservation.place(mid, actor_id=A, legal_basis=BASIS, authority="Chair",
                              document_ids=["doc_nowhere"])  # fmt: skip
    with pytest.raises(PolicyDenied):
        sv.preservation.place(mid, actor_id=S, legal_basis=BASIS, authority="Secretary")
    [placed] = _events(sv, mid, "preservation_hold_placed") or [None]
    assert placed is None, "nothing was placed"
