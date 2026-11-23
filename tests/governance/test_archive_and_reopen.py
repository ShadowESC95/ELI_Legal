"""A closed matter goes off the case list without being lost: its content archived (encrypted, out
of the working database, no readable trace left in either database), restored exactly when it is
reopened, its team given access again; and destroyed for good, by its key, when its retention
ends, unless a preservation hold keeps it."""

from __future__ import annotations

import hashlib
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
    sv.ctx.files.write(mid, report, b"# The report\n\n" + phrase)
    assert phrase not in report.read_bytes(), "sealed on disk while the case is open"
    roles = dict(sv.ctx.store.get_matter(mid).member_roles)

    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    matter = sv.ctx.store.get_matter(mid)
    assert matter.status is MatterStatus.CLOSED and matter.archived_at is not None
    assert not sv.ctx.store.list(Document, mid) and not sv.ctx.store.chunks_for(mid)
    assert not sv.ctx.vault.has_files(mid) and not report.exists()
    assert {"papers", "analysis", "reports"} <= set(sv.ctx.archive.kinds(mid)), "each kind apart"
    # Nothing of the case is left readable: not in the working database, not in the archive.
    data = Path(sv.ctx.settings.db_path).parent
    assert not _files_contain(data, phrase), "no readable trace in either database"
    key = sv.ctx.archive._key_path(mid, "papers")
    assert key.is_file() and key.parent != Path(sv.ctx.settings.db_path).parent
    [event] = _events(sv, mid, "matter_archived")
    assert event["payload"]["kinds"]["papers"]["originals"] >= 1
    # Off everyone's case list but its lead's; the lead sees it as closed.
    with pytest.raises((MatterAccessDenied, PolicyDenied)):
        sv.matters.get(mid, S)
    [listed] = sv.matters.closed_overview(A)
    assert listed["content"] == "archived" and listed["team"] >= 2
    with pytest.raises((MatterAccessDenied, PolicyDenied)):
        sv.matters.reopen(mid, actor_id=S, reason="I would like to look at it again.")

    done = sv.matters.reopen(mid, actor_id=A, reason="The award was set aside; rehearing ordered.")
    assert done["content"].startswith("restored from its archive") and S in done["team"]
    matter = sv.ctx.store.get_matter(mid)
    assert matter.status is not MatterStatus.CLOSED and matter.closed_at is None
    assert matter.archived_at is None and matter.closed_team is None
    assert _snapshot(sv, mid) == before, "every document and every passage, exactly"
    assert sv.ctx.files.read(mid, report).endswith(phrase), "the reports too, sealed again"
    assert phrase not in report.read_bytes()
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
    info = store.seal("mat_a", "papers", source)
    assert info.parts == 5
    store.open_to("mat_a", "papers", tmp_path / "out.bin")
    assert (tmp_path / "out.bin").read_bytes() == source.read_bytes()

    def tamper(sql: str, *args) -> None:
        with sqlite3.connect(store.db_path) as con:
            con.execute(sql, args)

    tamper("DELETE FROM archive_parts WHERE matter_id='mat_a' AND n=4")
    tamper("UPDATE archives SET parts=4 WHERE matter_id='mat_a'")  # and the count made to fit
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_a", "papers", tmp_path / "out.bin")  # the last part says it is last
    store.destroy("mat_a", "papers")

    store.seal("mat_a", "papers", source)
    with sqlite3.connect(store.db_path) as con:
        rows = con.execute("SELECT n, data FROM archive_parts WHERE matter_id='mat_a'").fetchall()
        swapped = {0: rows[1][1], 1: rows[0][1]}
        for n, data in swapped.items():
            con.execute(
                "UPDATE archive_parts SET data=? WHERE matter_id='mat_a' AND n=?", (data, n)
            )
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_a", "papers", tmp_path / "out.bin")
    store.destroy("mat_a", "papers")

    store.seal("mat_a", "papers", source)
    with sqlite3.connect(store.db_path) as con:
        con.execute("UPDATE archives SET matter_id='mat_b' WHERE matter_id='mat_a'")
        con.execute("UPDATE archive_parts SET matter_id='mat_b' WHERE matter_id='mat_a'")
    (tmp_path / "keys" / "mat_a.papers.key").rename(tmp_path / "keys" / "mat_b.papers.key")
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_b", "papers", tmp_path / "out.bin")
    store.destroy("mat_b", "papers")

    store.seal("mat_a", "papers", source)  # one kind passed off as another
    with sqlite3.connect(store.db_path) as con:
        con.execute("UPDATE archives SET kind='reports' WHERE matter_id='mat_a'")
        con.execute("UPDATE archive_parts SET kind='reports' WHERE matter_id='mat_a'")
    (tmp_path / "keys" / "mat_a.papers.key").rename(tmp_path / "keys" / "mat_a.reports.key")
    with pytest.raises(AuditIntegrityError):
        store.open_to("mat_a", "reports", tmp_path / "out.bin")


def test_when_retention_ends_the_key_is_destroyed_unless_a_preservation_hold_keeps_it(demo):
    sv, mid = demo
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=0)
    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    key = sv.ctx.archive._key_path(mid, "papers")
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
    assert retention.acted and "keys are gone" in retention.acted[0]
    assert not sv.ctx.archive.has(mid) and not key.exists()
    [event] = _events(sv, mid, "retention_purge")
    receipt = Path(sv.ctx.settings.artifacts_dir) / "disposals" / mid / event["payload"]["receipt"]
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["archives_sha256"] == event["output_hash"] and "key" in body["erasure"]
    assert "papers" in body["archives"]
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
    assert "papers" in done["archives_destroyed"]
    assert sv.matters.closed_overview(A)[0]["content"] == "deleted"
    with pytest.raises(InvalidState, match="already deleted"):
        sv.matters.delete_content(mid, actor_id=A, reason="Data-protection erasure request.")


# ── 0.8.16: each kind for its own period, every case file sealed ─────────────


def test_every_table_belongs_to_exactly_one_kind_of_information():
    from eli_legal.governance.retention import CONTENT, RECORD
    from eli_legal.persistence.sqlite import _KEPT_ON_PURGE, _SPECS

    placed = [t for k in (*CONTENT, RECORD) for t in k.tables]
    assert len(placed) == len(set(placed)), "no table in two kinds"
    assert set(placed) == {s.table for s in _SPECS.values()} | {"chunks"}, "a new table is placed"
    assert set(RECORD.tables) == set(_KEPT_ON_PURGE)


def test_each_kind_goes_when_its_own_period_ends_and_reopening_says_what_is_not_there(held_run):
    sv, mid, run_id = held_run
    report = Path(sv.ctx.settings.artifacts_dir) / "runs" / mid / run_id / "report_v9.md"
    sv.ctx.files.write(mid, report, b"# A report kept ten years")
    sv.compliance.set_retention(
        actor_id=G, audit_days=400, closed_matter_days=0, reports_days=3650, record_days=3650
    )
    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert retention.acted and "case papers, the analysis" in retention.acted[0]
    assert sv.ctx.archive.kinds(mid) == ["reports"], "the reports are kept for their own period"
    [listed] = sv.matters.closed_overview(A)
    kinds = listed["kinds"]
    assert kinds["papers"]["state"] == "deleted" and kinds["reports"]["state"] == "archived"
    assert (kinds["reports"]["until"] - listed["closed_on"]).days == 3650
    assert (kinds["record"]["until"] - listed["closed_on"]).days == 3650

    done = sv.matters.reopen(mid, actor_id=A, reason="Reopened to answer a question on costs.")
    assert (
        done["content"].startswith("restored from its archive") and "case papers" in done["content"]
    )
    assert sv.ctx.files.read(mid, report) == b"# A report kept ten years"
    assert not sv.ctx.store.list(Document, mid), "the papers were not brought back from nowhere"


def test_the_decision_record_goes_last_and_only_when_nothing_it_accounts_for_is_left(demo):
    sv, mid = demo
    with pytest.raises(Exception, match="at least as long"):
        sv.compliance.set_retention(
            actor_id=G, audit_days=400, closed_matter_days=30, record_days=10
        )
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=0, record_days=0)
    sv.matters.close(mid, actor_id=A, purge_content=False, archive=True, reason=WHY)
    retention = {r.check_id: r for r in sv.checks.run().results}["retention"]
    assert any("decision record" in line for line in retention.acted)
    assert sv.ctx.store.get_matter(mid) is None and not sv.ctx.archive.has(mid)
    assert _events(sv, mid, "record_disposed") and sv.ctx.audit.report().ok, "the ledger keeps it"


def test_case_files_are_sealed_on_disk_old_plain_ones_at_start_and_a_destroyed_key_ends_them(
    demo,
):
    from eli_legal.application import archive_service
    from eli_legal.security.sealed import is_sealed

    sv, mid = demo
    vault = Path(sv.ctx.settings.data_dir) / mid / "vault"
    files = [p for p in vault.rglob("*") if p.is_file()]
    assert files and all(is_sealed(p.read_bytes()) for p in files), "originals sealed"
    text = next(d for d in sv.ctx.store.list(Document, mid) if d.filename.endswith(".txt"))
    raw = sv.ctx.vault.read(mid, text.sha256)
    assert hashlib.sha256(raw).hexdigest() == text.sha256, "read back exactly"

    # As an earlier version left them: plain on disk.
    plain_copy = vault / text.sha256[:2] / text.sha256
    plain_copy.chmod(0o600)
    plain_copy.write_bytes(raw)
    old_report = Path(sv.ctx.settings.artifacts_dir) / "runs" / mid / "run_old" / "report_v1.md"
    old_report.parent.mkdir(parents=True)
    old_report.write_bytes(b"# An old plain report")
    counts = archive_service.upgrade(sv.ctx)
    assert counts["originals_sealed"] == 1 and counts["files_sealed"] == 1
    assert is_sealed(plain_copy.read_bytes()) and is_sealed(old_report.read_bytes())
    assert sv.ctx.vault.read(mid, text.sha256) == raw
    assert sv.ctx.files.read(mid, old_report) == b"# An old plain report"
    assert archive_service.upgrade(sv.ctx) == {
        "originals_sealed": 0,
        "files_sealed": 0,
        "archives_split": 0,
    }, "nothing done twice"

    sv.ctx.files.keys.destroy(mid, "reports")
    with pytest.raises(AuditIntegrityError, match="key was destroyed"):
        sv.ctx.files.read(mid, old_report)


def test_an_archive_made_by_0815_is_split_by_kind_at_start_and_reopens_whole(held_run, monkeypatch):
    from eli_legal.adapters.local.archive import LEGACY
    from eli_legal.application import archive_service
    from eli_legal.governance.retention import CONTENT

    sv, mid, _run = held_run
    before = _snapshot(sv, mid)
    sv.matters.close(mid, actor_id=A, purge_content=False, reason=WHY)
    matter = sv.ctx.store.get_matter(mid)
    # What 0.8.15 made: one archive of everything, format 1, under the matter's one key.
    whole = archive_service._Pack({}, {}, {})
    for kind in CONTENT:
        pack, paths = archive_service._take(sv.ctx, matter, kind)
        whole.rows.update(pack.rows)
        whole.originals.update(pack.originals)
        whole.files.update(pack.files)
    monkeypatch.setattr(archive_mod, "FORMAT", 1)
    archive_service._seal_pack(sv.ctx, matter, LEGACY, whole, A, WHY)
    monkeypatch.setattr(archive_mod, "FORMAT", 2)
    for kind in CONTENT:
        archive_service._remove(sv.ctx, matter, kind, archive_service._files(sv.ctx, mid, kind))
    assert sv.ctx.archive.kinds(mid) == [LEGACY]
    assert sv.ctx.archive._key_path(mid, LEGACY).name == f"{mid}.key"

    counts = archive_service.upgrade(sv.ctx)
    assert counts["archives_split"] == 1
    assert LEGACY not in sv.ctx.archive.kinds(mid) and "papers" in sv.ctx.archive.kinds(mid)
    sv.matters.reopen(mid, actor_id=A, reason="The award was set aside; rehearing ordered.")
    assert _snapshot(sv, mid) == before


def test_the_0815_archive_database_layout_is_carried_over(tmp_path):
    db = tmp_path / "archive.sqlite3"
    with sqlite3.connect(db) as con:
        con.executescript(
            "CREATE TABLE archives (matter_id TEXT PRIMARY KEY, format INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, nonce_prefix BLOB NOT NULL, parts INTEGER NOT NULL, "
            "plain_sha256 TEXT NOT NULL, plain_bytes INTEGER NOT NULL);"
            "CREATE TABLE archive_parts (matter_id TEXT NOT NULL, n INTEGER NOT NULL, "
            "data BLOB NOT NULL, PRIMARY KEY (matter_id, n));"
            "INSERT INTO archives VALUES ('mat_x', 1, '2026-11-23T18:00:00+00:00', x'00', 1, "
            "'ab', 3);"
            "INSERT INTO archive_parts VALUES ('mat_x', 0, x'0102');"
        )
    store = MatterArchive(db, tmp_path / "keys")
    assert store.kinds("mat_x") == ["all"] and store.info("mat_x", "all").format == 1
