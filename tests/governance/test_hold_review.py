"""A hold is decided on the evidence: the person sees the exact words that caused it, or the
original itself, and can describe an unreadable original by hand or file a readable copy. A
case's details can be corrected after it is opened."""

from __future__ import annotations

import pytest

from eli_legal.domain.enums import DocumentStatus, HoldResolution, HoldStatus
from eli_legal.domain.errors import InvalidState, PolicyDenied
from eli_legal.domain.models import Document, Hold, Party

A, S = "arb.keane", "sec.byrne"
WHY = "Checked against the print the claimant handed up at the directions hearing."


def _hold(sv, mid, rid, code):
    return next(h for h in sv.holds.list(mid, rid, actor_id=A) if h.reason_code == code)


def _unread(sv, mid, rid):
    held = [h for h in sv.holds.list(mid, rid, actor_id=A) if h.scope.value == "document"]
    return next(h for h in held if h.reason_code != "prompt_injection_detected")


def test_a_flagged_document_shows_the_exact_words_that_caused_its_hold(held_run):
    sv, mid, rid = held_run
    hold = _hold(sv, mid, rid, "prompt_injection_detected")
    seen = sv.holds.evidence(mid, hold.hold_id, actor_id=A)
    assert seen["document"]["filename"] == "06_exhibit_c7_forwarded_note.txt"
    assert "Northwind" in seen["document"]["filed_by"] and len(seen["document"]["sha256"]) == 64
    marked = [p["text"][start:end] for p in seen["passages"] for _name, start, end in p["marks"]]
    assert marked and any("ignore" in m.lower() or "instruction" in m.lower() for m in marked)
    assert seen["actions"] == ["accept_evidence", "exclude_document", "save_original"]


def test_an_unreadable_photo_says_why_and_is_described_by_hand_by_someone_entitled(held_run):
    sv, mid, rid = held_run
    hold = _unread(sv, mid, rid)
    seen = sv.holds.evidence(mid, hold.hold_id, actor_id=A)
    assert seen["document"]["filename"] == "07_site_photo.jpg" and seen["document"]["original"]
    if sv.ctx.ocr.can_read_images:  # the demo's photo is a damaged file, not a picture
        assert "could not be opened" in seen["document"]["error"]
    assert seen["actions"][:2] == ["describe", "readable_copy"]
    words = "Photograph of berth 4: two containers with water damage to their lower panels."
    with pytest.raises(PolicyDenied):
        sv.holds.describe(mid, hold.hold_id, actor_id=S, text=words, reason=WHY)
    done = sv.holds.describe(mid, hold.hold_id, actor_id=A, text=words, reason=WHY)
    assert done.status is HoldStatus.RESOLVED and done.resolution is HoldResolution.CORRECTED
    document = sv.ctx.store.require(Document, mid, hold.subject_id)
    assert document.described_by == A and document.status is DocumentStatus.PROCESSED
    [passage] = [c for c in sv.ctx.store.chunks_for(mid, document.document_id) if c.text == words]
    assert "described by hand by Aoife Keane" in passage.locator
    [event] = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "document_described"
    ]
    assert words not in str(event), "the words are in the case, not in the ledger"
    with pytest.raises(InvalidState):
        sv.holds.describe(mid, hold.hold_id, actor_id=A, text=words, reason=WHY)


def test_a_readable_copy_closes_the_hold_on_the_original_and_names_it(held_run):
    sv, mid, rid = held_run
    hold = _unread(sv, mid, rid)
    done, copy = sv.holds.replace_with_copy(
        mid, hold.hold_id, actor_id=A, filename="07_site_photo_description.txt",
        raw=b"Site photograph, 3 April 2023: containers stacked at berth 4, two water-damaged.",
        reason="The claimant filed a written description of the photograph instead.",
    )  # fmt: skip
    assert done is not None and done.resolution is HoldResolution.CORRECTED
    assert copy.status is DocumentStatus.PROCESSED
    original = sv.ctx.store.require(Document, mid, hold.subject_id)
    assert original.status is DocumentStatus.WAIVED and "readable copy (D" in original.waiver_reason
    assert copy.party_id == original.party_id and copy.doc_type == original.doc_type

    still = sv.ctx.store.require(Hold, mid, hold.hold_id)
    assert still.status is HoldStatus.RESOLVED


def test_looking_at_an_original_is_recorded_and_it_is_exactly_what_was_filed(held_run):
    import hashlib

    sv, mid, rid = held_run
    hold = _unread(sv, mid, rid)
    document, raw = sv.matters.original(mid, hold.subject_id, A)
    assert hashlib.sha256(raw).hexdigest() == document.sha256
    sv.matters.original(mid, hold.subject_id, A, purpose="saved")
    opened = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "document_opened"]
    assert [e["outcome"] for e in opened] == ["viewed", "saved"]


def test_case_details_are_corrected_and_a_party_in_use_is_not_removed(demo):
    sv, mid = demo
    matter = sv.matters.get(mid, A)
    claimant, respondent = matter.parties
    sv.matters.update(
        mid, actor_id=A, name="Harbour Freight Ltd v Northwind Logistics Ltd ",
        purpose="Case analysis ahead of the hearing",
        stated_issues=["Was time of the essence?", "  ", "Was the notice valid?"],
        parties=[Party(name="Harbour Freight Limited", role="claimant", party_id=claimant.party_id),
                 respondent],
    )  # fmt: skip
    matter = sv.matters.get(mid, A)
    assert matter.name == "Harbour Freight Ltd v Northwind Logistics Ltd"
    assert matter.stated_issues == ["Was time of the essence?", "Was the notice valid?"]
    assert matter.parties[0].name == "Harbour Freight Limited"
    assert matter.parties[0].party_id == claimant.party_id, "renamed, still the same party"
    with pytest.raises(InvalidState, match="cannot be removed"):
        sv.matters.update(mid, actor_id=A, parties=[matter.parties[0]])


def test_who_can_decide_is_said_so_nobody_is_left_at_a_greyed_out_button(held_run):
    from eli_legal.security import authn

    sv, mid, rid = held_run  # run by the secretary
    mine = sv.reviews.deciders(mid, rid, actor_id=A)
    assert mine["you_can"] and [w["user_id"] for w in mine["who"]] == [A]
    theirs = sv.reviews.deciders(mid, rid, actor_id=S)
    assert not theirs["you_can"] and theirs["why_not"] == "not a named reviewer of this matter"
    with authn.harness("test-harness"):
        own = sv.runs.start(mid, actor_id=A)
    mine = sv.reviews.deciders(mid, own.run_id, actor_id=A)
    assert not mine["you_can"] and mine["why_not"].startswith("started this run")
    assert mine["who"] == [], "the only named reviewer ran it: someone else must be named"
