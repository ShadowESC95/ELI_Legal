from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.domain.errors import AuditIntegrityError, MissingAuditKey
from eli_legal.domain.models import AuditEvent, utcnow
from eli_legal.security import authn

GENESIS = "ELI-LEGAL-AUDIT-GENESIS"
AUDIT_SCHEMA_VERSION = 3
_SEP = "\x1f"

# Minimisation is enforced here, not left to callers: the ledger refuses content-bearing keys and
# long strings, so privileged or personal text cannot be copied into the audit trail by accident.
MAX_PAYLOAD_STRING = 300
PROHIBITED_PAYLOAD_KEYS = frozenset(
    {"text", "content", "body", "quote", "document_text", "prompt", "completion", "address"}
)


@dataclass(frozen=True, slots=True)
class ChainReport:
    ok: bool
    count: int
    head_sig: str
    key_ids: tuple[str, ...]
    error: str = ""


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """A signed statement of how long the chain is and where it ends.

    Keep copies outside the machine (governance mailbox, write-once storage). A chain that later
    verifies against an older checkpoint but is shorter than a newer one has been rolled back.
    """

    count: int
    head_sig: str
    key_id: str
    created_at: str
    mac: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "count": self.count,
                "head_sig": self.head_sig,
                "key_id": self.key_id,
                "created_at": self.created_at,
                "mac": self.mac,
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> Checkpoint:
        d = json.loads(raw)
        return cls(int(d["count"]), d["head_sig"], d["key_id"], d["created_at"], d["mac"])


def _auth_label(actor_id: str) -> str:
    return "system" if actor_id == "system" else authn.method_for(actor_id)


def key_id_of(key: bytes) -> str:
    return hashlib.sha256(b"eli-legal-audit-key-id" + key).hexdigest()[:12]


def _check_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).lower() in PROHIBITED_PAYLOAD_KEYS:
                raise ValueError(f"audit payload must not carry content field {path}.{k}")
            _check_payload(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_payload(v, f"{path}[{i}]")
    elif isinstance(value, str) and len(value) > MAX_PAYLOAD_STRING:
        raise ValueError(f"audit payload string too long at {path}; store an id or hash instead")


class HmacAuditLedger:
    """Fail-closed, tamper-evident audit chain (HMAC-SHA-256).

    Detects: an edited event, a reordered or removed event, and — through the head anchor kept
    beside the key rather than beside the database — removal of the most recent events.
    Does not detect: an event that was never written, or a rollback of database and anchor
    together; ``checkpoint()`` and per-run completeness checks cover those.
    """

    def __init__(
        self,
        db_path: str | Path,
        key_file: str | Path,
        *,
        anchor_file: str | Path | None = None,
        retired_key_files: tuple[str | Path, ...] = (),
    ) -> None:
        self.db_path = Path(db_path)
        self.key_file = Path(key_file)
        self.key = self._load_key(self.key_file)
        self.key_id = key_id_of(self.key)
        self._keys: dict[str, bytes] = {self.key_id: self.key}
        for retired in retired_key_files:
            old = self._load_key(Path(retired))
            self._keys[key_id_of(old)] = old
        self.anchor_file = (
            Path(anchor_file) if anchor_file else self.key_file.with_suffix(".head.json")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    # ── key and storage ──────────────────────────────────────────────────────
    @staticmethod
    def _load_key(key_file: Path) -> bytes:
        if not key_file.exists():
            raise MissingAuditKey(f"audit key unavailable: {key_file}")
        key = key_file.read_bytes().strip()
        if len(key) < 32:
            raise MissingAuditKey("audit key must contain at least 32 bytes")
        if os.name != "nt":
            mode = key_file.stat().st_mode & 0o777
            if mode & 0o077:
                raise MissingAuditKey("audit key permissions must not permit group/other access")
        return key

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """CREATE TABLE IF NOT EXISTS audit_log (
                    seq INTEGER PRIMARY KEY,
                    event_json TEXT NOT NULL,
                    prev_sig TEXT NOT NULL,
                    chain_sig TEXT NOT NULL,
                    key_id TEXT NOT NULL
                )"""
            )
        finally:
            con.close()

    def _mac(self, key: bytes, *parts: str) -> str:
        return hmac.new(key, _SEP.join(parts).encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _canonical_event(event: AuditEvent) -> str:
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

    # ── head anchor ──────────────────────────────────────────────────────────
    def _write_anchor(self, count: int, head_sig: str) -> None:
        cp = self._make_checkpoint(count, head_sig)
        tmp = self.anchor_file.with_suffix(self.anchor_file.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(cp.to_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.anchor_file)

    def _make_checkpoint(self, count: int, head_sig: str) -> Checkpoint:
        created = utcnow().isoformat()
        mac = self._mac(self.key, "HEAD", str(count), head_sig, created)
        return Checkpoint(count, head_sig, self.key_id, created, mac)

    def _read_anchor(self) -> Checkpoint | None:
        if not self.anchor_file.exists():
            return None
        try:
            cp = Checkpoint.from_json(self.anchor_file.read_text(encoding="utf-8"))
        except (ValueError, KeyError) as exc:
            raise AuditIntegrityError("audit head anchor is unreadable") from exc
        self._check_checkpoint_mac(cp, "audit head anchor")
        return cp

    def _check_checkpoint_mac(self, cp: Checkpoint, what: str) -> None:
        key = self._keys.get(cp.key_id)
        if key is None:
            raise AuditIntegrityError(f"{what} was signed with an unknown key")
        expected = self._mac(key, "HEAD", str(cp.count), cp.head_sig, cp.created_at)
        if not hmac.compare_digest(expected, cp.mac):
            raise AuditIntegrityError(f"{what} signature mismatch")

    # ── append / verify ──────────────────────────────────────────────────────
    def append(self, event: AuditEvent) -> int:
        # Who acted is only evidence together with how they proved it.
        event.payload = {"auth": _auth_label(event.actor_id), **event.payload}
        _check_payload(event.payload)
        event_json = self._canonical_event(event)
        with self._lock:
            con = self._connect()
            try:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    "SELECT seq, chain_sig FROM audit_log ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq = int(row[0]) + 1 if row else 1
                prev = str(row[1]) if row else GENESIS
                sig = self._mac(self.key, prev, str(seq), event_json)
                con.execute(
                    "INSERT INTO audit_log(seq, event_json, prev_sig, chain_sig, key_id) "
                    "VALUES (?,?,?,?,?)",
                    (seq, event_json, prev, sig, self.key_id),
                )
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK") if con.in_transaction else None
                raise
            finally:
                con.close()
            self._write_anchor(seq, sig)
            return seq

    def _rows(self) -> list[tuple[int, str, str, str, str]]:
        con = self._connect()
        try:
            return con.execute(
                "SELECT seq, event_json, prev_sig, chain_sig, key_id FROM audit_log ORDER BY seq"
            ).fetchall()
        finally:
            con.close()

    def report(self, *, expected: Checkpoint | None = None) -> ChainReport:
        """Verify the whole chain. Never raises; ``verify_chain`` is the raising form."""
        with self._lock:
            rows = self._rows()
            prev = GENESIS
            key_ids: list[str] = []
            for index, (seq, event_json, recorded_prev, chain_sig, key_id) in enumerate(rows, 1):
                if seq != index:
                    return ChainReport(False, len(rows), prev, tuple(key_ids), "sequence gap")
                if recorded_prev != prev:
                    return ChainReport(False, len(rows), prev, tuple(key_ids), "linkage mismatch")
                key = self._keys.get(key_id)
                if key is None:
                    return ChainReport(False, len(rows), prev, tuple(key_ids), "unknown key id")
                if not hmac.compare_digest(self._mac(key, prev, str(seq), event_json), chain_sig):
                    return ChainReport(False, len(rows), prev, tuple(key_ids), "signature mismatch")
                if key_id not in key_ids:
                    key_ids.append(key_id)
                prev = chain_sig
            try:
                anchor = self._read_anchor()
            except AuditIntegrityError as exc:
                return ChainReport(False, len(rows), prev, tuple(key_ids), str(exc))
            if anchor is None and rows:
                return ChainReport(
                    False,
                    len(rows),
                    prev,
                    tuple(key_ids),
                    "head anchor missing for a non-empty chain",
                )
            for label, cp in (("head anchor", anchor), ("supplied checkpoint", expected)):
                if cp is None:
                    continue
                if label == "supplied checkpoint":
                    try:
                        self._check_checkpoint_mac(cp, label)
                    except AuditIntegrityError as exc:
                        return ChainReport(False, len(rows), prev, tuple(key_ids), str(exc))
                if len(rows) < cp.count:
                    return ChainReport(
                        False,
                        len(rows),
                        prev,
                        tuple(key_ids),
                        f"chain is shorter than the {label}: events have been removed",
                    )
                at_cp = rows[cp.count - 1][3] if cp.count else GENESIS
                if at_cp != cp.head_sig:
                    return ChainReport(
                        False, len(rows), prev, tuple(key_ids), f"chain does not match the {label}"
                    )
            return ChainReport(True, len(rows), prev, tuple(key_ids))

    def verify_chain(self, *, expected: Checkpoint | None = None) -> bool:
        result = self.report(expected=expected)
        if not result.ok:
            raise AuditIntegrityError(f"audit chain invalid: {result.error}")
        return True

    def checkpoint(self) -> Checkpoint:
        """Verify, then return a signed head statement for retention outside this machine."""
        result = self.report()
        if not result.ok:
            raise AuditIntegrityError(f"audit chain invalid: {result.error}")
        return self._make_checkpoint(result.count, result.head_sig)

    def last_signature(self) -> str:
        rows = self._rows()
        return rows[-1][3] if rows else GENESIS

    def count(self) -> int:
        return len(self._rows())

    def events(
        self, *, matter_id: str | None = None, run_id: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Decoded events in order. Callers must hold ``audit.read`` for the matter."""
        for seq, event_json, _prev, chain_sig, key_id in self._rows():
            event = json.loads(event_json)
            if matter_id is not None and event.get("matter_id") != matter_id:
                continue
            if run_id is not None and event.get("run_id") != run_id:
                continue
            event["seq"] = seq
            event["chain_sig"] = chain_sig
            event["key_id"] = key_id
            yield event
