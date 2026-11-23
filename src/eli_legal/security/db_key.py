"""The key the databases are encrypted with.

One 256-bit key, made the first time ELI Legal starts, kept in the secrets folder beside the
audit key (``database.key``), readable only by the account running ELI Legal. On Windows it is
also wrapped by the Data Protection API for that account, so the file copied elsewhere, or read
by another account, is useless. On macOS and Linux the file itself is the key: anyone who can
read it, and the databases, can read the case. Keep the secrets folder off the data folder's
backups' path, or back it up separately, and keep the machine's disk encrypted.

**Losing this key loses the databases.** Back it up with the audit key, separately from the data.
A database that is encrypted is never answered with a new key: a missing key is an error.
"""

from __future__ import annotations

import base64
import ctypes
import os
import secrets
import sqlite3
from pathlib import Path

from eli_legal.domain.errors import DatabaseKeyError
from eli_legal.persistence.connect import (
    ENCRYPTION_AVAILABLE,
    KEY_BYTES,
    is_encrypted,
    open_database,
)
from eli_legal.security.files import POSIX, private_dir

NAME = "database.key"
_DPAPI = b"dpapi:"
# Bound into the Windows wrapping, so a blob made for something else does not unwrap as this.
_ENTROPY = b"ELI Legal database key v1"


def key_path(audit_key_file: str | Path) -> Path:
    """Where the database key is kept: beside the audit key."""
    return Path(audit_key_file).parent / NAME


# ── Windows: the Data Protection API, for the current user ───────────────────


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return _Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    blob_p = ctypes.POINTER(_Blob)
    call.argtypes = [
        blob_p,
        wintypes.LPCWSTR if protect else ctypes.POINTER(wintypes.LPWSTR),
        blob_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_p,
    ]
    call.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source, _keep = blob(data)
    entropy, _keep2 = blob(_ENTROPY)
    out = _Blob()
    ui_forbidden = 0x1
    description = "ELI Legal database key" if protect else None
    if not call(
        ctypes.byref(source),
        description,
        ctypes.byref(entropy),
        None,
        None,
        ui_forbidden,
        ctypes.byref(out),
    ):
        raise DatabaseKeyError(
            "Windows would not "
            + ("protect" if protect else "unwrap")
            + " the database key for this account"
            + ("" if protect else ": it was made by another Windows account or on another machine")
            + f" (error {ctypes.get_last_error()})"  # type: ignore[attr-defined,unused-ignore]
        )
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _encode(key: bytes) -> bytes:
    if os.name == "nt":
        return _DPAPI + base64.b64encode(_dpapi(key, protect=True)) + b"\n"
    return key.hex().encode("ascii") + b"\n"


def _decode(raw: bytes, path: Path) -> bytes:
    text = raw.strip()
    if text.startswith(_DPAPI):
        if os.name != "nt":
            raise DatabaseKeyError(
                f"{path} is protected by Windows for one account: it cannot be read here"
            )
        key = _dpapi(base64.b64decode(text[len(_DPAPI) :]), protect=False)
    else:
        try:
            key = bytes.fromhex(text.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DatabaseKeyError(f"{path} is not a database key") from exc
    if len(key) != KEY_BYTES:
        raise DatabaseKeyError(f"{path} is not a database key (it must hold 32 bytes)")
    return key


# ── the key ──────────────────────────────────────────────────────────────────


def read_key(path: str | Path) -> bytes:
    """The key in ``path``. Refused if others may read it (where permissions apply)."""
    target = Path(path)
    if POSIX and target.stat().st_mode & 0o077:
        raise DatabaseKeyError(f"{target} may be read by others: make it 0600 (chmod 600)")
    return _decode(target.read_bytes(), target)


def database_key(audit_key_file: str | Path, *databases: str | Path) -> bytes | None:
    """The databases' key: read, or made on first start. None where SQLCipher is not installed
    (the databases stay plain, and the checks say so). A missing key with an encrypted database
    in ``databases`` is an error, never a new key."""
    path = key_path(audit_key_file)
    if path.exists():
        return read_key(path)
    locked = [Path(d).name for d in databases if is_encrypted(d)]
    if locked:
        raise DatabaseKeyError(
            f"the database key ({path}) is missing, and {', '.join(locked)} cannot be opened "
            "without it: restore it from the backup of the secrets folder"
        )
    if not ENCRYPTION_AVAILABLE:
        return None
    key = secrets.token_bytes(KEY_BYTES)
    private_dir(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process made it a moment ago: use that one
        return read_key(path)
    with os.fdopen(fd, "wb") as fh:
        fh.write(_encode(key))
        fh.flush()
        os.fsync(fh.fileno())
    if POSIX:
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    return key


def open_existing(path: str | Path, audit_key_file: str | Path) -> sqlite3.Connection:
    """Open one of ELI Legal's databases, or a copy of one, with the key kept beside the audit
    key, for a tool or a test that reads or edits it directly. A plain file opens as plain
    SQLite; an encrypted one needs its key."""
    held = key_path(audit_key_file)
    return open_database(path, read_key(held) if held.exists() else None)
