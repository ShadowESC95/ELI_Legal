from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path

from eli_legal.domain.errors import AuditIntegrityError, MissingAuditKey
from eli_legal.domain.models import AuditEvent

GENESIS = "ELI-LEGAL-AUDIT-GENESIS"


class HmacAuditLedger:
    """Minimal fail-closed HMAC-SHA256 chain. Production deployment still needs key management, backups and checkpoints."""

    def __init__(self, db_path: str | Path, key_file: str | Path) -> None:
        self.db_path = Path(db_path)
        self.key_file = Path(key_file)
        self.key = self._load_key()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _load_key(self) -> bytes:
        if not self.key_file.exists():
            raise MissingAuditKey(f"audit key unavailable: {self.key_file}")
        key = self.key_file.read_bytes().strip()
        if len(key) < 32:
            raise MissingAuditKey("audit key must contain at least 32 bytes")
        return key

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_json TEXT NOT NULL,
                prev_sig TEXT NOT NULL,
                chain_sig TEXT NOT NULL
            )""")

    def _sign(self, prev_sig: str, event_json: str) -> str:
        return hmac.new(self.key, (prev_sig + "\x1f" + event_json).encode(), hashlib.sha256).hexdigest()

    def append(self, event: AuditEvent) -> int:
        event_json = json.dumps({
            "event_type": event.event_type, "actor_id": event.actor_id,
            "matter_id": event.matter_id, "run_id": event.run_id,
            "action": event.action, "subject_id": event.subject_id,
            "outcome": event.outcome, "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as con:
            row = con.execute("SELECT chain_sig FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            sig = self._sign(prev, event_json)
            cur = con.execute("INSERT INTO audit_events(event_json, prev_sig, chain_sig) VALUES(?,?,?)", (event_json, prev, sig))
            return int(cur.lastrowid)

    def verify_chain(self) -> bool:
        prev = GENESIS
        with self._connect() as con:
            rows = con.execute("SELECT event_json, prev_sig, chain_sig FROM audit_events ORDER BY id").fetchall()
        for event_json, recorded_prev, chain_sig in rows:
            if recorded_prev != prev:
                raise AuditIntegrityError("audit chain linkage mismatch")
            expected = self._sign(prev, event_json)
            if not hmac.compare_digest(expected, chain_sig):
                raise AuditIntegrityError("audit chain signature mismatch")
            prev = chain_sig
        return True
