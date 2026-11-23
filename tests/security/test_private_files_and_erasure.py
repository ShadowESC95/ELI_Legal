"""Case material on disk is readable by the person running ELI Legal and no one else, and what is
deleted is gone from the files as well as from the records.

Folders are 0700 and the databases (with their write-ahead files) 0600; an original in the vault
is 0400. What an earlier version left open is tightened at start. A file ELI Legal deletes is
overwritten before it is removed; after a matter's content is deleted the database is rebuilt
and its write-ahead log emptied, so none of the deleted text is left in either file, and the
deletion receipt says so.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from eli_legal.application.services import build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import demo_settings, setup_demo
from eli_legal.security import files

pytestmark = pytest.mark.skipif(os.name == "nt", reason="permission bits are a POSIX matter")

A, S = "arb.keane", "sec.byrne"


def _mode(path) -> int:
    return stat.S_IMODE(Path(path).lstat().st_mode)


def _originals(settings) -> list[Path]:
    return [p for p in Path(settings.data_dir).rglob("*") if p.is_file()]


def test_the_databases_the_vault_and_their_folders_are_private_to_the_user(demo):
    sv, _mid = demo
    s = sv.ctx.settings
    for db in (s.db_path, s.audit_db_path):
        assert _mode(db) == 0o600, db
        for extra in ("-wal", "-shm"):
            beside = Path(f"{db}{extra}")
            if beside.exists():
                assert _mode(beside) & 0o077 == 0, beside
    for folder in (Path(s.db_path).parent, Path(s.data_dir), Path(s.artifacts_dir)):
        assert _mode(folder) & 0o077 == 0, folder
    originals = _originals(s)
    assert originals and all(_mode(p) == 0o400 for p in originals), "originals are read-only"
    assert all(_mode(p.parent) & 0o077 == 0 for p in originals)
    assert sv.ctx.store._con.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_what_an_earlier_version_left_open_is_tightened_at_start(tmp_path):
    ws = build_demo_workspace(tmp_path / "demo")
    settings = demo_settings(tmp_path, ws)
    sv = build_services(settings, install_network_guard=False)
    setup_demo(sv, ws)
    outside = tmp_path / "not_ours.txt"
    outside.write_text("someone else's file")
    outside.chmod(0o644)
    report = Path(settings.artifacts_dir) / "reports" / "old.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("an old report")
    (Path(settings.artifacts_dir) / "link").symlink_to(outside)
    for path, mode in (
        (settings.db_path, 0o644),
        (Path(settings.db_path).parent, 0o755),
        (Path(settings.data_dir), 0o755),
        (report, 0o664),
        (report.parent, 0o775),
    ):
        Path(path).chmod(mode)
    build_services(settings, install_network_guard=False)  # as at the next start
    assert _mode(settings.db_path) == 0o600
    assert _mode(Path(settings.db_path).parent) == 0o700
    assert _mode(Path(settings.data_dir)) == 0o700
    assert _mode(report) == 0o600 and _mode(report.parent) == 0o700
    assert all(_mode(p) == 0o400 for p in _originals(settings)), "never widened"
    assert _mode(outside) == 0o644, "a link out of the tree is not followed"


def test_a_deleted_file_is_overwritten_before_it_is_removed(tmp_path):
    secret = b"privileged advice " * 600
    target = tmp_path / "report.md"
    target.write_bytes(secret)
    same = tmp_path / "same_file"
    os.link(target, same)  # a second name for the same data, to look at it afterwards
    files.shred(target)
    assert not target.exists()
    assert same.read_bytes() == b"\0" * len(secret)


def test_deleting_a_matters_content_leaves_none_of_it_in_the_database_file_or_its_log(demo):
    sv, mid = demo
    token = "qzxvbnmkjhwtoken"
    matter = sv.matters.get(mid, A)
    document = sv.ingestion.register(
        matter=matter,
        actor_id=S,
        filename="private_note.txt",
        raw=f"A private note that mentions {token}, and {token} again.".encode(),
    )
    sv.ingestion.process(document, actor_id=S)
    db = Path(sv.ctx.settings.db_path)
    wal = Path(f"{db}-wal")

    def on_disk() -> bytes:
        return b"".join(p.read_bytes() for p in (db, wal) if p.exists())

    assert token.encode() in on_disk(), "stored before the deletion"
    sv.matters.close(mid, actor_id=A, purge_content=True, reason="Award issued; content deleted.")
    left = on_disk()
    assert token.encode() not in left and token[:9].encode() not in left
    assert not wal.exists() or wal.stat().st_size == 0, "the write-ahead log is emptied"
    assert sv.ctx.store._con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert token.encode() not in Path(sv.ctx.settings.audit_db_path).read_bytes()
    folder = Path(sv.ctx.settings.artifacts_dir) / "disposals" / mid
    receipt = json.loads(sorted(folder.glob("*.json"))[-1].read_text(encoding="utf-8"))
    assert receipt["erasure"]["write_ahead_log_emptied"] is True
    assert "VACUUM" in receipt["erasure"]["database"]
    assert receipt["erasure"]["files"] == "overwritten with zeros, then removed"
    assert not _originals(sv.ctx.settings) or all(
        mid not in str(p) for p in _originals(sv.ctx.settings)
    ), "the matter's originals are gone"
