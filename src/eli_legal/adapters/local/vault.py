"""Evidence vault: original files, stored once, never altered.

Files are addressed by their SHA-256 and written read-only. Reading verifies the hash again, so
an original that has been changed on disk is reported rather than served.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from eli_legal.domain.errors import AuditIntegrityError, NotFound


class EvidenceVault:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _matter_dir(self, matter_id: str) -> Path:
        if not matter_id or any(c in matter_id for c in "/\\.") or matter_id.startswith("-"):
            raise ValueError("invalid matter id for vault path")
        return self.root / matter_id / "vault"

    def _path(self, matter_id: str, sha256: str) -> Path:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("invalid content hash")
        return self._matter_dir(matter_id) / sha256[:2] / sha256

    def store(self, matter_id: str, raw: bytes) -> tuple[str, str]:
        """Store bytes; returns (sha256, vault reference). Idempotent for identical content."""
        digest = hashlib.sha256(raw).hexdigest()
        target = self._path(matter_id, digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            try:
                target.chmod(0o400)
            except OSError:  # permission bits are advisory on some filesystems
                pass
        return digest, f"vault:{matter_id}/{digest}"

    def read(self, matter_id: str, sha256: str) -> bytes:
        target = self._path(matter_id, sha256)
        if not target.exists():
            raise NotFound(f"original not found in vault: {sha256[:12]}")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise AuditIntegrityError(f"vault content does not match its hash: {sha256[:12]}")
        return raw

    def verify(self, matter_id: str, sha256: str) -> bool:
        try:
            self.read(matter_id, sha256)
        except (NotFound, AuditIntegrityError):
            return False
        return True

    def has_files(self, matter_id: str) -> bool:
        """Whether any original of the matter is still held."""
        directory = self._matter_dir(matter_id)
        return directory.exists() and any(p.is_file() for p in directory.rglob("*"))

    def purge_matter(self, matter_id: str, *, keep: Iterable[str] = ()) -> int:
        """Delete every original for a matter (retention at matter close), except those whose
        SHA-256 is in ``keep`` (under a preservation hold). Returns files removed."""
        directory = self._matter_dir(matter_id)
        if not directory.exists():
            return 0
        kept = set(keep)
        if kept:
            removed = 0
            for path in sorted(directory.rglob("*"), reverse=True):
                if path.is_file() and path.name not in kept:
                    path.chmod(0o600)
                    path.unlink()
                    removed += 1
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            return removed
        count = sum(1 for p in directory.rglob("*") if p.is_file())
        for path in directory.rglob("*"):
            if path.is_file():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
        shutil.rmtree(directory)
        return count
