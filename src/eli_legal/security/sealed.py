"""Case files encrypted at rest: the original documents, the reports and the evidence packs
ELI Legal keeps, each matter's each kind (governance/retention.py) under a key of its own.

A sealed file is ``MAGIC``, a 12-byte nonce, then AES-256-GCM ciphertext whose additional data is
the matter, the kind and the file's own name, so a file moved to another matter or another place
does not open. Destroying a kind's key makes every copy of those files unreadable, backups
included, which is how a kind's retention ends even where a copy was missed.

Files written before 0.8.16 are plain; they are still read, and sealed when ELI Legal starts.
What is exported on purpose (an evidence pack written to a folder someone chose, a report saved
as PDF or Word) is plain where it is put: that is a hand-over, and it is recorded.

The keys are in the secrets folder, apart from the data folder. They protect a copy of the data
folder, a backup or a disk image made without the secrets folder; the operating-system account
and full-disk encryption protect the machine itself.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eli_legal.domain.errors import AuditIntegrityError
from eli_legal.governance.retention import kind_of_file
from eli_legal.security.files import private_dir, shred

MAGIC = b"ELI-LEGAL-SEALED-1\n"


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


class FileKeys:
    """One key per matter and kind, in a private folder."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    def _path(self, matter_id: str, kind: str) -> Path:
        for part in (matter_id, kind):
            if not part or any(c in part for c in "/\\.") or part.startswith("-"):
                raise ValueError("invalid matter or kind for a file key")
        return self.folder / f"{matter_id}.{kind}.key"

    def get(self, matter_id: str, kind: str, *, create: bool) -> bytes | None:
        path = self._path(matter_id, kind)
        if path.is_file():
            return path.read_bytes()
        if not create:
            return None
        private_dir(self.folder)
        key = AESGCM.generate_key(bit_length=256)
        tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)  # never replaces a key another thread made meanwhile
        except FileExistsError:
            pass
        except OSError:  # a filesystem without hard links
            if not path.exists():
                os.replace(tmp, path)
        if tmp.exists():
            tmp.unlink()
        return path.read_bytes()

    def has(self, matter_id: str, kind: str) -> bool:
        return self._path(matter_id, kind).is_file()

    def destroy(self, matter_id: str, kind: str) -> bool:
        """Overwrite and remove the key: what it sealed can no longer be read, anywhere."""
        path = self._path(matter_id, kind)
        if not path.exists():
            return False
        shred(path)
        return True


def _aad(matter_id: str, kind: str, name: str) -> bytes:
    return f"eli-legal-sealed:1:{matter_id}:{kind}:{name}".encode()


def seal(keys: FileKeys, matter_id: str, kind: str, name: str, data: bytes) -> bytes:
    key = keys.get(matter_id, kind, create=True)
    assert key is not None
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, _aad(matter_id, kind, name))


def unseal(keys: FileKeys, matter_id: str, kind: str, name: str, blob: bytes) -> bytes:
    if not is_sealed(blob):
        return blob  # written before files were sealed; sealed at the next start
    key = keys.get(matter_id, kind, create=False)
    if key is None:
        raise AuditIntegrityError(
            f"this file's key was destroyed (its retention ended or it was deleted): {name}"
        )
    body = blob[len(MAGIC) :]
    try:
        return AESGCM(key).decrypt(body[:12], body[12:], _aad(matter_id, kind, name))
    except InvalidTag as exc:
        raise AuditIntegrityError(
            f"a sealed file does not authenticate: it was altered or moved: {name}"
        ) from exc


def write_private(path: Path, blob: bytes) -> None:
    """Write durably, 0600, replacing what was there (overwritten first, if it was plain)."""
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        try:
            old = path.read_bytes()[: len(MAGIC)]
        except OSError:
            old = MAGIC
        if not is_sealed(old):
            shred(path)  # plain case content: overwritten, not just replaced
    os.replace(tmp, path)


class SealedFiles:
    """The files ELI Legal makes from a matter (reports, outbox copies, evidence packs), sealed
    in its artifacts folder. Paths elsewhere are written and read as they are."""

    def __init__(self, keys: FileKeys, root: str | Path) -> None:
        self.keys = keys
        self.root = Path(root)

    def _place(self, path: Path) -> tuple[str, str] | None:
        """(kind, name) for a path in the artifacts folder; None for anywhere else."""
        try:
            relative = Path(os.path.abspath(path)).relative_to(os.path.abspath(self.root))
        except ValueError:
            return None
        name = relative.as_posix()
        return kind_of_file(name), name

    def write(self, matter_id: str, path: str | Path, data: bytes) -> None:
        target = Path(path)
        place = self._place(target)
        if place is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return
        kind, name = place
        write_private(target, seal(self.keys, matter_id, kind, name, data))

    def read(self, matter_id: str, path: str | Path) -> bytes:
        source = Path(path)
        blob = source.read_bytes()
        place = self._place(source)
        if place is None:
            return blob
        kind, name = place
        return unseal(self.keys, matter_id, kind, name, blob)

    def seal_existing(self, matter_id: str, path: Path) -> bool:
        """Seal a file written before 0.8.16. False if it was already sealed or is elsewhere."""
        place = self._place(path)
        if place is None:
            return False
        with open(path, "rb") as fh:
            if is_sealed(fh.read(len(MAGIC))):
                return False
        blob = path.read_bytes()
        kind, name = place
        write_private(path, seal(self.keys, matter_id, kind, name, blob))
        return True
