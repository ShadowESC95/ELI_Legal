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
AUDIT_SCHEMA_VERSION = 2


class HmacAuditLedger:
    """Fail-closed HMAC-SHA256 chain for governance events.

    The ledger stores identifiers, hashes and control metadata. Callers should not place privileged
    document/report bodies or unnecessary personal data in ``payload``.
    """

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
        if os.name != "nt":
            mode = self.key_file.stat().st_mode & 0o777
            if mode & 0o077:
                raise MissingAuditKey("audit key permissions must not permit group/other access")
        return key

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL,
                    prev_sig TEXT NOT NULL,
                    chain_sig TEXT NOT NULL
                )"""
            )

    def _sign(self, prev_sig: str, event_json: str) -> str:
        message = (prev_sig + "\x1f" + event_json).encode("utf-8")
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def _canonical_event(self, event: AuditEvent) -> str:
        return json.dumps(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "matter_id": event.matter_id,
                "run_id": event.run_id,
                "action": event.action,
                "subject_id": event.subject_id,
                "object_type": event.object_type,
                "outcome": event.outcome,
                "model_id": event.model_id,
                "prompt_version": event.prompt_version,
                "tool_id": event.tool_id,
                "source_ids": event.source_ids,
                "input_hash": event.input_hash,
                "output_hash": event.output_hash,
                "verification_status": event.verification_status,
                "reviewer_id": event.reviewer_id,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def append(self, event: AuditEvent) -> int:
        event_json = self._canonical_event(event)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT chain_sig FROM audit_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev = row[0] if row else GENESIS
            sig = self._sign(prev, event_json)
            cur = con.execute(
                "INSERT INTO audit_events(event_json, prev_sig, chain_sig) VALUES(?,?,?)",
                (event_json, prev, sig),
            )
            return int(cur.lastrowid)

    def verify_chain(self) -> bool:
        prev = GENESIS
        with self._connect() as con:
            rows = con.execute(
                "SELECT event_json, prev_sig, chain_sig FROM audit_events ORDER BY id"
            ).fetchall()
        for event_json, recorded_prev, chain_sig in rows:
            if recorded_prev != prev:
                raise AuditIntegrityError("audit chain linkage mismatch")
            expected = self._sign(prev, event_json)
            if not hmac.compare_digest(expected, chain_sig):
                raise AuditIntegrityError("audit chain signature mismatch")
            prev = chain_sig
        return True

    def last_signature(self) -> str:
        with self._connect() as con:
            row = con.execute(
                "SELECT chain_sig FROM audit_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return str(row[0]) if row else GENESIS
