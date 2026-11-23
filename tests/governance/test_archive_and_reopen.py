"""A closed matter goes off the case list without being lost: its content archived (encrypted, out
of the working database, no readable trace left in either database), restored exactly when it is
reopened, its team given access again; and destroyed for good, by its key, when its retention
ends, unless a preservation hold keeps it."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eli_legal.adapters.local import archive as archive_mod
from eli_legal.adapters.local.archive import MatterArchive
from eli_legal.application.preservation_service import PreservationHeld
from eli_legal.domain.enums import MatterStatus
from eli_legal.domain.errors import (
    AuditIntegrityError,
    InvalidState,
    MatterAccessDenied,
    PolicyDenied,
)
from eli_legal.domain.models import Document

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
WHY = "Award issued and the time for any challenge has passed."
BASIS = "Respondent's solicitors gave notice of a negligence claim on 12 November 2026."


def _events(sv, mid, kind):
    return [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == kind]


def _snapshot(sv, mid):
    documents = sorted(
        (d.document_id, d.sha256, d.filename) for d in sv.ctx.store.list(Document, mid)
    )
    chunks = sorted((c.chunk_id, c.text_hash, c.text) for c in sv.ctx.store.chunks_for(mid))
    return documents, chunks


def _phrase(sv, mid) -> bytes:
    """A distinctive run of words from the case's own papers."""
    text = max((c.text for c in sv.ctx.store.chunks_for(mid)), key=len)
    words = text.split()
    return " ".join(words[len(words) // 2 : len(words) // 2 + 6]).encode("utf-8")


def _files_contain(folder: Path, needle: bytes) -> list[str]:
    return [p.name for p in folder.rglob("*") if p.is_file() and needle in p.read_bytes()]


def test_archived_at_closing_restored_exactly_when_reopened_and_the_team_given_access_again(
    held_run,
):
    sv, mid, run_id = held_run
    before = _snapshot(sv, mid)
    phrase = _phrase(sv, mid)
    report = Path(sv.ctx.settings.artifacts_dir) / "runs" / mid / run_id / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b"# The report\n\n" + phrase)
    roles = dict(sv.ctx.store.get_matter(mid).member_roles)

    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    matter = sv.ctx.store.get_matter(mid)
    assert matter.status is MatterStatus.CLOSED and matter.archived_at is not None
    assert not sv.ctx.store.list(Document, mid) and not sv.ctx.store.chunks_for(mid)
    assert not sv.ctx.vault.has_files(mid) and not report.exists()
    assert sv.ctx.archive.has(mid)
    # Nothing of the case is left readable: not in the working database, not in the archive.
    data = Path(sv.ctx.settings.db_path).parent
    assert not _files_contain(data, phrase), "no readable trace in either database"
    key = sv.ctx.archive._key_path(mid)
    assert key.is_file() and key.parent != Path(sv.ctx.settings.db_path).parent
    [event] = _events(sv, mid, "matter_archived")
    assert event["output_hash"] == sv.ctx.archive.info(mid).plain_sha256
    assert event["payload"]["originals"] >= 1
    # Off everyone's case list but its lead's; the lead sees it as closed.
    with pytest.raises((MatterAccessDenied, PolicyDenied)):
        sv.matters.get(mid, S)
    [listed] = sv.matters.closed_overview(A)
    assert listed["content"] == "archived" and listed["team"] >= 2
    with pytest.raises((MatterAccessDenied, PolicyDenied)):
        sv.matters.reopen(mid, actor_id=S, reason="I would like to look at it again.")

    done = sv.matters.reopen(mid, actor_id=A, reason="The award was set aside; rehearing ordered.")
    assert done["content"] == "restored from its archive" and S in done["team"]
    matter = sv.ctx.store.get_matter(mid)
    assert matter.status is not MatterStatus.CLOSED and matter.closed_at is None
    assert matter.archived_at is None and matter.closed_team is None
    assert _snapshot(sv, mid) == before, "every document and every passage, exactly"
    assert report.read_bytes().endswith(phrase), "the reports too"
    word = max(("".join(ch for ch in w if ch.isalnum()) for w in phrase.decode().split()), key=len)
    assert sv.ctx.store.search_chunks(mid, word), "searchable again"
    assert all(sv.ctx.vault.verify(mid, sha) for _id, sha, _name in before[0])
    assert sv.matters.get(mid, S).matter_id == mid and matter.member_roles == roles
    assert not sv.ctx.archive.has(mid) and not key.exists(), "one copy of the case, not two"
    [reopened] = _events(sv, mid, "matter_reopened")
    assert reopened["payload"]["access_given_back"] and sv.ctx.audit.report().ok


def test_someone_suspended_since_is_left_out_and_named_and_a_deleted_case_reopens_as_record(
    demo,
):
    sv, mid = demo
    sv.matters.close(mid, actor_id=A, purge_content=True, reason=WHY)
    secretary = sv.ctx.store.get_user(S)
    secretary.active = False
    sv.ctx.store.put_user(secretary)
    done = sv.matters.reopen(mid, actor_id=A, reason="Reopened to record the costs decision.")
    assert done["content"].startswith("deleted while it was closed")
    assert S in done["left_out"] and S not in sv.ctx.store.get_matter(mid).authorised_user_ids
    with pytest.raises(InvalidState, match="not closed"):
        sv.matters.reopen(mid, actor_id=A, reason="Reopened to record the costs decision.")


def test_an_altered_or_another_matters_archive_is_refused_and_nothing_is_restored(demo):
    sv, mid = demo
    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    db = sv.ctx.archive.db_path
    with sqlite3.connect(db) as con:
        data = bytearray(con.execute("SELECT data FROM archive_parts WHERE n=0").fetchone()[0])
        data[100] ^= 0x01
        con.execute("UPDATE archive_parts SET data=? WHERE n=0", (bytes(data),))
    with pytest.raises(AuditIntegrityError, match="does not authenticate"):
        sv.matters.reopen(mid, actor_id=A, reason="The award was set aside; rehearing ordered.")
    assert sv.ctx.store.get_matter(mid).status is MatterStatus.CLOSED
    assert not sv.ctx.store.list(Document, mid), "nothing restored from an altered archive"
    assert sv.ctx.archive.has(mid), "and the archive is not destroyed by the attempt"
    assert not list((Path(sv.ctx.settings.db_path).parent / "archive_work").glob("*")), "no scratch"


def test_parts_cannot_be_cut_off_reordered_or_moved_to_another_matter(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_mod, "PART", 1024)
    store = MatterArchive(tmp_path / "archive.sqlite3", tmp_path / "keys")
    source = tmp_path / "plain.bin"
    source.write_bytes(bytes(range(256)) * 20)  # five parts
    info = store.seal("mat_a", source)
    assert info.parts == 5
    store.open_to("mat_a", tmp_path / "out.bin")
    assert (tmp_path / "out.bin").read_bytes() == source.read_bytes()

    def tamper(sql: str, *args) -> None:
        with sqlite3.connect(store.db_path) as con:
            con.execute(sql, args)

    tamper("DELETE FROM archive_parts WHERE matter_id='mat_a' AND n=4")
    tamper("UPDATE archives SET parts=4 WHERE matter_id='mat_a'")  # and the count made to fit
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_a", tmp_path / "out.bin")  # the last part says it is the last
    store.destroy("mat_a")

    store.seal("mat_a", source)
    with sqlite3.connect(store.db_path) as con:
        rows = con.execute("SELECT n, data FROM archive_parts WHERE matter_id='mat_a'").fetchall()
        swapped = {0: rows[1][1], 1: rows[0][1]}
        for n, data in swapped.items():
            con.execute(
                "UPDATE archive_parts SET data=? WHERE matter_id='mat_a' AND n=?", (data, n)
            )
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_a", tmp_path / "out.bin")
    store.destroy("mat_a")

    store.seal("mat_a", source)
    with sqlite3.connect(store.db_path) as con:
        con.execute("UPDATE archives SET matter_id='mat_b' WHERE matter_id='mat_a'")
        con.execute("UPDATE archive_parts SET matter_id='mat_b' WHERE matter_id='mat_a'")
    (tmp_path / "keys" / "mat_a.key").rename(tmp_path / "keys" / "mat_b.key")
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_b", tmp_path / "out.bin")


def test_when_retention_ends_the_key_is_destroyed_unless_a_preservation_hold_keeps_it(demo):
    sv, mid = demo
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=0)
    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    key = sv.ctx.archive._key_path(mid)
    hold = sv.preservation.place(mid, actor_id=A, legal_basis=BASIS, authority="Tribunal chair")
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert not retention.acted and "archive is kept" in retention.items[0].text
    assert sv.ctx.archive.has(mid) and key.exists()
    assert _events(sv, mid, "disposal_refused")
    with pytest.raises(PreservationHeld):
        sv.matters.delete_content(mid, actor_id=A, reason="The parties asked for erasure now.")

    sv.preservation.release(
        mid, hold.hold_id, actor_id=G,
        reason="Claim settled by deed of 1 December 2026; preservation no longer required.",
    )  # fmt: skip
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert retention.acted and "key is gone" in retention.acted[0]
    assert not sv.ctx.archive.has(mid) and not key.exists()
    [event] = _events(sv, mid, "retention_purge")
    receipt = Path(sv.ctx.settings.artifacts_dir) / "disposals" / mid / event["payload"]["receipt"]
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["archive"]["sha256"] == event["output_hash"] and "key" in body["erasure"]
    [listed] = sv.matters.closed_overview(A)
    assert listed["content"] == "deleted" and sv.ctx.audit.report().ok


def test_kept_then_archived_later_then_deleted_by_decision(demo):
    sv, mid = demo
    sv.matters.close(mid, actor_id=A, purge_content=False, reason=WHY)
    assert sv.matters.closed_overview(A)[0]["content"] == "kept"
    with pytest.raises(InvalidState, match="already closed"):
        sv.matters.close(mid, actor_id=A, purge_content=False, reason=WHY)
    with pytest.raises((MatterAccessDenied, PolicyDenied)):
        sv.matters.archive(mid, actor_id=S, reason="Tidying the case list today.")
    sv.matters.archive(mid, actor_id=A, reason="Off the working database until retention ends.")
    assert sv.matters.closed_overview(A)[0]["content"] == "archived"
    with pytest.raises(InvalidState, match="already archived"):
        sv.matters.archive(mid, actor_id=A, reason="Off the working database until retention ends.")
    done = sv.matters.delete_content(mid, actor_id=A, reason="Data-protection erasure request.")
    assert done["archive_destroyed"]
    assert sv.matters.closed_overview(A)[0]["content"] == "deleted"
    with pytest.raises(InvalidState, match="already deleted"):
        sv.matters.delete_content(mid, actor_id=A, reason="Data-protection erasure request.")
