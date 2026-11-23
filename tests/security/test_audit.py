import os
import sqlite3

import pytest

from eli_legal.adapters.local.hmac_audit import Checkpoint, HmacAuditLedger
from eli_legal.domain.errors import AuditIntegrityError, MissingAuditKey
from eli_legal.domain.models import AuditEvent
from eli_legal.security.db_key import open_existing
from tests.conftest import make_key


def _ledger(tmp_path, events=5) -> HmacAuditLedger:
    ledger = HmacAuditLedger(tmp_path / "audit.db", make_key(tmp_path / "keys" / "audit.key"))
    for i in range(events):
        ledger.append(AuditEvent("test", "user", "m1", "r1", "act", f"s{i}", "ok"))
    return ledger


def _sql(tmp_path, statement):
    with sqlite3.connect(tmp_path / "audit.db") as con:
        con.execute(statement)


def test_missing_audit_key_fails_closed(tmp_path):
    with pytest.raises(MissingAuditKey):
        HmacAuditLedger(tmp_path / "audit.db", tmp_path / "missing.key")


def test_a_short_or_world_readable_key_is_refused(tmp_path):
    short = tmp_path / "short.key"
    short.write_text("abc", encoding="utf-8")
    short.chmod(0o600)
    with pytest.raises(MissingAuditKey):
        HmacAuditLedger(tmp_path / "a.db", short)
    if os.name != "nt":  # Windows has no group/other permission bits to check
        loose = make_key(tmp_path / "loose.key")
        loose.chmod(0o644)
        with pytest.raises(MissingAuditKey):
            HmacAuditLedger(tmp_path / "a.db", loose)


def test_audit_tamper_detected(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.verify_chain()
    _sql(tmp_path, "UPDATE audit_log SET event_json='{}' WHERE seq=2")
    with pytest.raises(AuditIntegrityError, match="signature"):
        ledger.verify_chain()


def test_removing_an_event_from_the_middle_is_detected(tmp_path):
    ledger = _ledger(tmp_path)
    _sql(tmp_path, "DELETE FROM audit_log WHERE seq=3")
    assert not ledger.report().ok


def test_audit_truncation_detected(tmp_path):
    """Deleting the most recent events leaves a chain that is internally consistent; the head
    anchor kept beside the key is what exposes it."""
    ledger = _ledger(tmp_path)
    _sql(tmp_path, "DELETE FROM audit_log WHERE seq > 3")
    report = ledger.report()
    assert not report.ok and "removed" in report.error
    with pytest.raises(AuditIntegrityError):
        ledger.verify_chain()


def test_deleting_every_event_is_detected(tmp_path):
    ledger = _ledger(tmp_path)
    _sql(tmp_path, "DELETE FROM audit_log")
    assert not ledger.report().ok


def test_removing_or_forging_the_head_anchor_is_detected(tmp_path):
    ledger = _ledger(tmp_path)
    anchor = ledger.anchor_file
    original = anchor.read_text(encoding="utf-8")
    anchor.unlink()
    assert "anchor missing" in ledger.report().error
    forged = Checkpoint.from_json(original)
    anchor.write_text(
        Checkpoint(3, forged.head_sig, forged.key_id, forged.created_at, forged.mac).to_json(),
        encoding="utf-8",
    )
    assert "signature mismatch" in ledger.report().error


def test_rolling_back_database_and_anchor_together_is_caught_by_an_off_machine_checkpoint(tmp_path):
    ledger = _ledger(tmp_path, events=3)
    old_db = (tmp_path / "audit.db").read_bytes()
    old_anchor = ledger.anchor_file.read_text(encoding="utf-8")
    for i in range(2):
        ledger.append(AuditEvent("test", "user", "m1", "r1", "act", f"later{i}", "ok"))
    external = ledger.checkpoint()
    for suffix in ("-wal", "-shm"):
        (tmp_path / f"audit.db{suffix}").unlink(missing_ok=True)
    (tmp_path / "audit.db").write_bytes(old_db)
    ledger.anchor_file.write_text(old_anchor, encoding="utf-8")
    assert ledger.report().ok, (
        "a consistent rollback is invisible locally; that is the stated limit"
    )
    assert not ledger.report(expected=external).ok


def test_the_ledger_refuses_content_so_logs_stay_minimal(tmp_path):
    ledger = _ledger(tmp_path, events=0)
    for payload in (
        {"text": "privileged advice"},
        {"nested": {"quote": "x"}},
        {"note": "y" * 301},
        {"address": "a@b.example"},
    ):
        with pytest.raises(ValueError):
            ledger.append(AuditEvent("t", "u", "m", "r", "a", "s", "ok", payload=payload))
    assert ledger.count() == 0


def test_a_run_never_starts_on_a_ledger_that_does_not_verify(held_run):
    sv, mid, _rid = held_run
    settings = sv.ctx.settings
    with open_existing(settings.audit_db_path, settings.audit_key_file) as con:
        con.execute("DELETE FROM audit_log WHERE seq = (SELECT MAX(seq) FROM audit_log)")
    with pytest.raises(AuditIntegrityError):
        sv.runs.start(mid, actor_id="sec.byrne")
