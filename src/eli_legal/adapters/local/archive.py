"""Closed matters' content, sealed: encrypted at rest, restorable, and destroyable for good.

A matter's content (its database rows, original documents and the files made from it) is packed
into one file, encrypted with AES-256-GCM under a key of its own, and kept in an archive database
beside the main one. The key is kept apart, in the secrets folder. Destroying the key makes every
copy of the archive unreadable, backups included: deletion that does not depend on finding every
copy.

The encryption is in parts of 16 MiB (the STREAM construction): each part's nonce carries its
position and whether it is the last, and the matter id is authenticated with every part, so a
part cannot be swapped between matters, reordered, repeated or cut off without the archive failing
to open.

What this protects: a copy of the data folder, a backup or a lost disk image without the secrets
folder. What it does not: someone who holds this account's files, secrets folder included. That
is what full-disk encryption and the operating system's account protections are for.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eli_legal.domain.errors import AuditIntegrityError, NotFound
from eli_legal.security.files import private_dir, private_file, shred

FORMAT = 1
PART = 16 * 1024 * 1024
_PREFIX = 7  # bytes of random nonce prefix; then a 4-byte part counter and a 1-byte last flag


@dataclass(frozen=True, slots=True)
class ArchiveInfo:
    matter_id: str
    created_at: datetime
    plain_sha256: str
    plain_bytes: int
    parts: int


def _aad(matter_id: str) -> bytes:
    return f"eli-legal-matter-archive:{FORMAT}:{matter_id}".encode()


def _nonce(prefix: bytes, index: int, last: bool) -> bytes:
    return prefix + struct.pack(">IB", index, 1 if last else 0)


class MatterArchive:
    def __init__(self, db_path: str | Path, keys_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.keys_dir = Path(keys_dir)
        self._lock = threading.RLock()

    # ── storage ──────────────────────────────────────────────────────────────
    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            private_dir(self.db_path.parent)
            con = sqlite3.connect(self.db_path)
            try:
                # Deleted pages are overwritten, so a destroyed archive leaves no ciphertext behind.
                con.execute("PRAGMA secure_delete=ON")
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS archives (
                        matter_id TEXT PRIMARY KEY,
                        format INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        nonce_prefix BLOB NOT NULL,
                        parts INTEGER NOT NULL,
                        plain_sha256 TEXT NOT NULL,
                        plain_bytes INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS archive_parts (
                        matter_id TEXT NOT NULL,
                        n INTEGER NOT NULL,
                        data BLOB NOT NULL,
                        PRIMARY KEY (matter_id, n)
                    );
                    """
                )
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise
            finally:
                con.close()
                private_file(self.db_path)

    def _key_path(self, matter_id: str) -> Path:
        if not matter_id or any(c in matter_id for c in "/\\.") or matter_id.startswith("-"):
            raise ValueError("invalid matter id for an archive")
        return self.keys_dir / f"{matter_id}.key"

    # ── the archive ──────────────────────────────────────────────────────────
    def has(self, matter_id: str) -> bool:
        return self.info(matter_id) is not None

    def info(self, matter_id: str) -> ArchiveInfo | None:
        if not self.db_path.exists():
            return None
        with self._db() as con:
            row = con.execute(
                "SELECT created_at, plain_sha256, plain_bytes, parts FROM archives "
                "WHERE matter_id=?",
                (matter_id,),
            ).fetchone()
        if row is None:
            return None
        return ArchiveInfo(matter_id, datetime.fromisoformat(row[0]), row[1], row[2], row[3])

    def seal(self, matter_id: str, source: Path) -> ArchiveInfo:
        """Encrypt ``source`` as this matter's archive. Refuses if one is already kept."""
        if self.has(matter_id):
            raise ValueError("this matter already has an archive")
        key = AESGCM.generate_key(bit_length=256)
        prefix = secrets.token_bytes(_PREFIX)
        cipher = AESGCM(key)
        aad = _aad(matter_id)
        size = source.stat().st_size
        total = max(1, -(-size // PART))
        digest = hashlib.sha256()
        # The key first, durably: an archive whose key was lost would be no archive at all.
        key_path = self._key_path(matter_id)
        private_dir(self.keys_dir)
        tmp = key_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, key_path)
        created = datetime.now(timezone.utc)
        try:
            with self._db() as con, source.open("rb") as fh:
                for index in range(total):
                    chunk = fh.read(PART)
                    digest.update(chunk)
                    sealed = cipher.encrypt(_nonce(prefix, index, index == total - 1), chunk, aad)
                    con.execute(
                        "INSERT INTO archive_parts (matter_id, n, data) VALUES (?,?,?)",
                        (matter_id, index, sealed),
                    )
                con.execute(
                    "INSERT INTO archives (matter_id, format, created_at, nonce_prefix, parts, "
                    "plain_sha256, plain_bytes) VALUES (?,?,?,?,?,?,?)",
                    (
                        matter_id,
                        FORMAT,
                        created.isoformat(),
                        prefix,
                        total,
                        digest.hexdigest(),
                        size,
                    ),
                )
        except BaseException:
            shred(key_path)
            raise
        return ArchiveInfo(matter_id, created, digest.hexdigest(), size, total)

    def open_to(self, matter_id: str, target: Path) -> ArchiveInfo:
        """Decrypt this matter's archive into ``target`` (a private file), checking every part
        and the whole. Raises AuditIntegrityError if anything does not check out."""
        info = self.info(matter_id)
        if info is None:
            raise NotFound("this matter has no archive")
        key_path = self._key_path(matter_id)
        if not key_path.is_file():
            raise AuditIntegrityError("the archive's key is missing: it cannot be opened")
        cipher = AESGCM(key_path.read_bytes())
        aad = _aad(matter_id)
        digest = hashlib.sha256()
        with self._db() as con:
            prefix = con.execute(
                "SELECT nonce_prefix FROM archives WHERE matter_id=?", (matter_id,)
            ).fetchone()[0]
            rows = con.execute(
                "SELECT n, data FROM archive_parts WHERE matter_id=? ORDER BY n", (matter_id,)
            )
            private_dir(target.parent)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out:
                seen = 0
                for n, data in rows:
                    if n != seen:
                        raise AuditIntegrityError("the archive is missing a part")
                    try:
                        chunk = cipher.decrypt(
                            _nonce(prefix, n, n == info.parts - 1), bytes(data), aad
                        )
                    except InvalidTag as exc:
                        raise AuditIntegrityError(
                            f"part {n + 1} of the archive does not authenticate: it was altered, "
                            "or is not this matter's"
                        ) from exc
                    digest.update(chunk)
                    out.write(chunk)
                    seen += 1
                out.flush()
                os.fsync(out.fileno())
        if seen != info.parts or digest.hexdigest() != info.plain_sha256:
            shred(target)
            raise AuditIntegrityError("the archive is incomplete or does not match its hash")
        return info

    def destroy(self, matter_id: str) -> ArchiveInfo | None:
        """Destroy the key (overwritten, then removed), then the ciphertext. Without the key, no
        copy of this archive, anywhere, can be read again."""
        info = self.info(matter_id)
        key_path = self._key_path(matter_id)
        if key_path.exists():
            shred(key_path)
        if info is None:
            return None
        with self._db() as con:
            con.execute("DELETE FROM archive_parts WHERE matter_id=?", (matter_id,))
            con.execute("DELETE FROM archives WHERE matter_id=?", (matter_id,))
        with self._lock:
            con = sqlite3.connect(self.db_path)
            try:
                con.execute("VACUUM")
            finally:
                con.close()
        return info
