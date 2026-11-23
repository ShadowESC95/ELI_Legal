"""The working database and the audit ledger are encrypted at rest (SQLCipher): nothing of a case
is readable in their files; a wrong or missing key is refused, never answered with a new empty
database; a database an earlier version left plain is converted, checked and the plain file
destroyed; and where SQLCipher is missing, the checks say the databases are not encrypted."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from eli_legal.application import container
from eli_legal.application.services import build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import demo_settings, setup_demo
from eli_legal.domain.errors import DatabaseKeyError
from eli_legal.persistence import connect
from eli_legal.persistence.connect import (
    ENCRYPTION_AVAILABLE,
    DatabaseBusy,
    encrypt_in_place,
    is_encrypted,
    is_plaintext,
    recover_interrupted,
)
from eli_legal.persistence.sqlite import Store
from eli_legal.security import db_key
from eli_legal.security.db_key import database_key, key_path, open_existing, read_key


@dataclass
class Probe:
    x: int


needs_sqlcipher = pytest.mark.skipif(not ENCRYPTION_AVAILABLE, reason="SQLCipher not installed")


def _services(tmp_path: Path):
    workspace = build_demo_workspace(tmp_path / "demo")
    sv = build_services(demo_settings(tmp_path, workspace), install_network_guard=False)
    return sv, workspace


def _phrase(sv, mid) -> bytes:
    text = max((c.text for c in sv.ctx.store.chunks_for(mid)), key=len)
    words = text.split()
    return " ".join(words[len(words) // 2 : len(words) // 2 + 5]).encode("utf-8")


def _bytes_of(database: Path) -> bytes:
    return b"".join(p.read_bytes() for p in (database, Path(f"{database}-wal")) if p.exists())


@needs_sqlcipher
def test_a_new_database_is_encrypted_and_nothing_of_the_case_is_readable_in_its_files(tmp_path):
    sv, workspace = _services(tmp_path)
    mid = setup_demo(sv, workspace)
    settings = sv.ctx.settings
    assert sv.ctx.store.encrypted and sv.ctx.audit.encrypted
    phrase = _phrase(sv, mid)
    for database in (Path(settings.db_path), Path(settings.audit_db_path)):
        assert not is_plaintext(database) and is_encrypted(database)
        content = _bytes_of(database)
        assert not content.startswith(b"SQLite format 3") and phrase not in content
        assert b"arb.keane" not in content, "not even who did what"
    key = key_path(settings.audit_key_file)
    assert key.parent == Path(settings.audit_key_file).parent
    if os.name != "nt":
        assert key.stat().st_mode & 0o777 == 0o600
    assert len(read_key(key)) == 32
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(settings.db_path).execute("SELECT * FROM matters").fetchall()
    with open_existing(settings.db_path, settings.audit_key_file) as con:
        assert con.execute("SELECT count(*) FROM matters").fetchone()[0] == 1
    encryption = {r.check_id: r for r in sv.checks.run().results}["encryption"]
    assert encryption.state == "ok"


@needs_sqlcipher
def test_a_wrong_or_missing_key_is_refused_never_answered_with_a_new_database(tmp_path):
    path = tmp_path / "data" / "eli_legal.sqlite3"
    first = os.urandom(32)
    store = Store(path, key=first)
    store.put_registry("probe", "one", Probe(1))
    store.close()
    size = path.stat().st_size
    with pytest.raises(DatabaseKeyError, match="could not be opened with its key"):
        Store(path, key=os.urandom(32))
    assert path.stat().st_size == size, "nothing written over it"
    audit_key = tmp_path / "secrets" / "audit_hmac.key"
    audit_key.parent.mkdir()
    with pytest.raises(DatabaseKeyError, match="is missing"):
        database_key(audit_key, path)
    assert not key_path(audit_key).exists(), "no new key made for an encrypted database"
    again = Store(path, key=first)
    assert again.get_registry("probe", "one", Probe) == Probe(1)
    again.close()


@needs_sqlcipher
def test_a_plain_database_from_an_earlier_version_is_converted_checked_and_destroyed(
    tmp_path, monkeypatch
):
    # An earlier version: the same data, written plain.
    monkeypatch.setattr(container, "database_key", lambda *a, **k: None)
    sv, workspace = _services(tmp_path)
    mid = setup_demo(sv, workspace)
    settings = sv.ctx.settings
    assert not sv.ctx.store.encrypted and is_plaintext(settings.db_path)
    phrase = _phrase(sv, mid)
    word = max(phrase.decode().split(), key=len).strip(".,;:()")
    found = [c.chunk_id for c, _score in sv.ctx.store.search_chunks(mid, word)]
    events = sv.ctx.audit.report().count
    documents = sorted(d.document_id for d in sv.matters.documents(mid, "arb.keane"))

    # The working database still open in another program (here, the earlier copy): left as it
    # is, and said so. The ledger, which nothing holds open between writes, is converted.
    monkeypatch.undo()
    busy = build_services(settings, install_network_guard=False)
    assert not busy.ctx.store.encrypted and is_plaintext(settings.db_path)
    assert busy.ctx.audit.encrypted
    said = {
        e["subject_id"]: e
        for e in busy.ctx.audit.events()
        if e["event_type"] == "database_encrypted"
    }
    refused = said["working database"]
    assert refused["outcome"] == "not_converted" and "in use" in refused["payload"]["why"]
    assert said["audit ledger"]["outcome"] == "encrypted"
    encryption = {r.check_id: r for r in busy.checks.run().results}["encryption"]
    assert encryption.state == "attention" and "not encrypted" in encryption.summary
    for services in (sv, busy):
        services.ctx.store.close()

    now = build_services(settings, install_network_guard=False)
    assert now.ctx.store.encrypted and now.ctx.audit.encrypted
    for database in (Path(settings.db_path), Path(settings.audit_db_path)):
        assert is_encrypted(database) and phrase not in _bytes_of(database)
        for leftover in (".plaintext", ".encrypting"):
            assert not database.with_name(database.name + leftover).exists()
    assert sorted(d.document_id for d in now.matters.documents(mid, "arb.keane")) == documents
    assert [c.chunk_id for c, _s in now.ctx.store.search_chunks(mid, word)] == found
    report = now.ctx.audit.report()
    assert report.ok and report.count > events
    done = [e for e in now.ctx.audit.events() if e["event_type"] == "database_encrypted"]
    assert {e["subject_id"] for e in done if e["outcome"] == "encrypted"} == {
        "audit ledger",
        "working database",
    }
    assert all("rows" in e["payload"] for e in done if e["outcome"] == "encrypted")
    now.ctx.store.close()


@needs_sqlcipher
def test_a_conversion_cut_short_is_put_right_before_anything_opens_the_database(tmp_path):
    key = os.urandom(32)
    path = tmp_path / "eli_legal.sqlite3"
    aside = tmp_path / "eli_legal.sqlite3.plaintext"
    plain = Store(path)
    plain.put_registry("probe", "one", Probe(1))
    plain.close()
    # Power lost after the plain file went aside and before the encrypted one came in.
    os.replace(path, aside)
    assert recover_interrupted(path, key) == "restored"
    assert is_plaintext(path) and not aside.exists()
    # Power lost after the encrypted one came in, before the plain one was destroyed.
    assert encrypt_in_place(path, key) is not None
    aside.write_bytes(b"SQLite format 3\x00 left behind")
    assert recover_interrupted(path, key) == "completed"
    assert not aside.exists() and is_encrypted(path)
    assert Store(path, key=key).get_registry("probe", "one", Probe) == Probe(1)


@needs_sqlcipher
def test_a_database_open_elsewhere_is_never_converted_under_it(tmp_path):
    path = tmp_path / "eli_legal.sqlite3"
    holder = Store(path)
    with pytest.raises(DatabaseBusy):
        encrypt_in_place(path, os.urandom(32))
    assert is_plaintext(path)
    holder.put_registry("probe", "still", Probe(2))
    holder.close()


def test_without_sqlcipher_the_databases_are_plain_and_the_checks_say_so(tmp_path, monkeypatch):
    monkeypatch.setattr(container, "database_key", lambda *a, **k: None)
    sv, _workspace = _services(tmp_path)
    assert not sv.ctx.store.encrypted and not sv.ctx.audit.encrypted
    encryption = {r.check_id: r for r in sv.checks.run().results}["encryption"]
    assert encryption.state == "attention"
    assert encryption.summary.startswith("The databases are not encrypted")
    sv.ctx.store.close()


def test_an_encrypted_database_without_sqlcipher_is_refused_plainly(tmp_path, monkeypatch):
    path = tmp_path / "eli_legal.sqlite3"
    path.write_bytes(os.urandom(4096))  # what an encrypted file looks like from outside
    monkeypatch.setattr(connect, "ENCRYPTION_AVAILABLE", False)
    with pytest.raises(DatabaseKeyError, match="SQLCipher"):
        connect.open_database(path, os.urandom(32))


@pytest.mark.skipif(os.name != "nt", reason="the Windows Data Protection API")
def test_on_windows_the_key_file_is_useless_off_this_account(tmp_path):
    secret = os.urandom(32)
    wrapped = db_key._dpapi(secret, protect=True)
    assert secret not in wrapped and db_key._dpapi(wrapped, protect=False) == secret
    audit_key = tmp_path / "secrets" / "audit_hmac.key"
    audit_key.parent.mkdir()
    key = database_key(audit_key)
    assert key is not None and key_path(audit_key).read_bytes().startswith(b"dpapi:")
    assert key.hex().encode() not in key_path(audit_key).read_bytes()
    assert read_key(key_path(audit_key)) == key


@needs_sqlcipher
def test_the_key_can_be_exported_for_safekeeping_and_restored_from_it(tmp_path, monkeypatch):
    import argparse

    from eli_legal import cli

    audit_key = tmp_path / "secrets" / "audit_hmac.key"
    audit_key.parent.mkdir()
    key = database_key(audit_key)
    assert key is not None
    monkeypatch.setenv("ELI_LEGAL_AUDIT_KEY_FILE", str(audit_key))
    out = tmp_path / "safe" / "database-key.txt"
    out.parent.mkdir()
    assert cli.cmd_database_key(argparse.Namespace(out=str(out))) == 0
    assert out.read_text(encoding="ascii").strip() == key.hex()
    if os.name != "nt":
        assert out.stat().st_mode & 0o777 == 0o600
    assert cli.cmd_database_key(argparse.Namespace(out=str(out))) == 1, "never over a file"
    key_path(audit_key).unlink()  # lost; restored from the safe copy
    os.replace(out, key_path(audit_key))
    assert read_key(key_path(audit_key)) == key
