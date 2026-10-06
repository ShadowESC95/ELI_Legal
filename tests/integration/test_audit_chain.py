import sqlite3

import pytest

from eli_legal.adapters.local.hmac_audit import HmacAuditLedger
from eli_legal.domain.errors import AuditIntegrityError, MissingAuditKey
from eli_legal.domain.models import AuditEvent


def test_missing_audit_key_fails_closed(tmp_path):
    with pytest.raises(MissingAuditKey):
        HmacAuditLedger(tmp_path / "audit.db", tmp_path / "missing.key")


def test_audit_tamper_detected(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(b"x" * 64)
    key.chmod(0o600)
    db = tmp_path / "audit.db"
    ledger = HmacAuditLedger(db, key)
    ledger.append(AuditEvent("test", "human", "m1", "r1", "review", "c1", "ok"))
    assert ledger.verify_chain()
    with sqlite3.connect(db) as con:
        con.execute("UPDATE audit_events SET event_json='{}' WHERE id=1")
    with pytest.raises(AuditIntegrityError):
        ledger.verify_chain()
