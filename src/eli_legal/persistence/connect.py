"""Opening ELI Legal's databases, encrypted at rest.

The working database (matters, documents' text, findings, reports) and the audit ledger are
SQLCipher databases: every page of the file, its write-ahead log and its search index is
encrypted with AES-256 under a 256-bit key kept in the secrets folder (security/db_key.py). The
key is given raw, so opening costs no key stretching; a wrong key fails at once with a clear
error, never with a new empty database in its place.

A database written by an earlier version is converted the first time this version starts
(``encrypt_in_place``): copied into a new encrypted file, the copy checked (integrity, every
table's row count, the search index, and for the ledger its whole chain), swapped in, and only
then the plain file overwritten and removed. If anything does not check out, the plain database
is left as it was and keeps working, and the routine checks say it is not encrypted.

Where SQLCipher is not installed (a source checkout without it) the databases are plain SQLite,
and the routine checks and ``eli-legal doctor`` say so.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from eli_legal.domain.errors import DatabaseKeyError
from eli_legal.security.files import shred

try:
    from sqlcipher3 import dbapi2 as _cipher  # type: ignore[import-not-found,unused-ignore]
except ImportError:  # a source checkout without it: plain SQLite, and the checks say so
    _cipher = None  # type: ignore[assignment,unused-ignore]

ENCRYPTION_AVAILABLE = _cipher is not None
# What a database call may raise: the standard library's errors, and SQLCipher's own.
DB_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error,) + (
    (_cipher.Error,) if _cipher is not None else ()
)
HEADER = b"SQLite format 3\x00"
KEY_BYTES = 32


class DatabaseBusy(Exception):
    """Another program has the database open: it is converted another time."""


class ConversionFailed(Exception):
    """The encrypted copy did not check out; the plain database is untouched."""


def is_plaintext(path: str | Path) -> bool:
    """A plain SQLite file (readable by anyone who can read the file)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(HEADER)) == HEADER
    except OSError:
        return False


def is_encrypted(path: str | Path) -> bool:
    """A file that is there, not empty, and not plain SQLite: encrypted (or not a database)."""
    target = Path(path)
    try:
        return target.is_file() and target.stat().st_size > 0 and not is_plaintext(target)
    except OSError:
        return False


def will_encrypt(path: str | Path, key: bytes | None) -> bool:
    """Whether opening ``path`` with ``key`` gives an encrypted database: there is a key, SQLCipher
    is installed, and the file is new or already encrypted (a plain file is converted first)."""
    return (
        key is not None
        and ENCRYPTION_AVAILABLE
        and str(path) != ":memory:"
        and not is_plaintext(path)
    )


def _keyed(key: bytes) -> str:
    if len(key) != KEY_BYTES:
        raise DatabaseKeyError("a database key is 32 bytes")
    return f"\"x'{key.hex()}'\""


def open_database(path: str | Path, key: bytes | None, **kwargs: Any) -> sqlite3.Connection:
    """Open one of ELI Legal's databases: encrypted with ``key`` where it can be (see
    ``will_encrypt``), else plain SQLite. A wrong key, or an encrypted file without SQLCipher to
    read it, is refused with DatabaseKeyError."""
    target = str(path)
    if not will_encrypt(path, key):
        if key is not None and is_encrypted(path) and not ENCRYPTION_AVAILABLE:
            raise DatabaseKeyError(
                f"{Path(target).name} is encrypted and this copy of ELI Legal cannot read it: "
                "SQLCipher (the sqlcipher3-wheels package) is not installed"
            )
        return cast(sqlite3.Connection, sqlite3.connect(target, **kwargs))
    assert key is not None and _cipher is not None
    con = _cipher.connect(target, **kwargs)
    # A wrong key is answered below, in words; SQLCipher's own log would only repeat it.
    con.execute("PRAGMA cipher_log_level = NONE")
    con.execute(f"PRAGMA key = {_keyed(key)}")
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except _cipher.DatabaseError as exc:
        con.close()
        raise DatabaseKeyError(
            f"{Path(target).name} could not be opened with its key: the key is not the one it "
            "was encrypted with, or the file is not an ELI Legal database"
        ) from exc
    return cast(sqlite3.Connection, con)


# ── converting a plain database ──────────────────────────────────────────────


def _tables(con: Any) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _counts(con: Any) -> dict[str, int]:
    return {
        name: int(con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        for name in _tables(con)
    }


def _search_sample(con: Any) -> tuple[str, list[str]] | None:
    """A word from a stored passage and the passages the search index finds for it."""
    if "chunks_fts" not in _tables(con):
        return None
    row = con.execute("SELECT text FROM chunks ORDER BY rowid LIMIT 1").fetchone()
    words = re.findall(r"[^\W\d_]{4,}", str(row[0])) if row else []
    if not words:
        return None
    term = f'"{words[0]}"'
    found = con.execute(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY chunk_id", (term,)
    ).fetchall()
    return term, [str(r[0]) for r in found]


def _sync(path: Path) -> None:
    # Opened for writing: Windows will not flush a file through a read-only handle (EBADF).
    with open(path, "r+b") as fh:
        os.fsync(fh.fileno())
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _companions(path: Path) -> list[Path]:
    return [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm", "-journal")]


def encrypt_in_place(
    path: str | Path, key: bytes, *, check: Callable[[Path], None] | None = None
) -> dict[str, int] | None:
    """Convert a plain database into an encrypted one, in place. Returns how many tables and
    rows were converted, or None if there was nothing to convert (no file, already encrypted,
    no SQLCipher). Raises DatabaseBusy if another program has it open, and ConversionFailed if
    the encrypted copy does not check out; either way the plain database is untouched.

    ``check`` is given the encrypted copy before it is swapped in, to check what only its
    owner can (the audit ledger's chain); it raises to stop the conversion."""
    target = Path(path)
    if _cipher is None or not is_plaintext(target):
        return None
    keyed = _keyed(key)
    plain = sqlite3.connect(str(target), isolation_level=None, timeout=0)
    try:
        # Nothing else may have it open, even idle: an exclusive lock is refused if anything does
        # (another program, an older ELI Legal still running on the same data).
        try:
            plain.execute("PRAGMA locking_mode=EXCLUSIVE")
            plain.execute("BEGIN EXCLUSIVE")
            plain.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            raise DatabaseBusy(f"{target.name} is in use by another program") from exc
        busy = plain.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if busy and int(busy[0]):
            raise DatabaseBusy(f"{target.name} is in use by another program")
        if plain.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ConversionFailed(f"{target.name} does not pass its own integrity check")
        counts = _counts(plain)
        sample = _search_sample(plain)
        # Out of write-ahead mode, so closing leaves no log beside it.
        plain.execute("PRAGMA journal_mode=DELETE")
    finally:
        plain.close()
    copy = target.with_name(target.name + ".encrypting")
    for leftover in (copy, *_companions(copy)):
        if leftover.exists():
            shred(leftover)
    try:
        con = _cipher.connect(str(target), isolation_level=None)
        try:
            quoted = str(copy).replace("'", "''")
            con.execute(f"ATTACH DATABASE '{quoted}' AS encrypted KEY {keyed}")
            con.execute("SELECT sqlcipher_export('encrypted')")
            con.execute("DETACH DATABASE encrypted")
        finally:
            con.close()
        made = open_database(copy, key)
        try:
            if made.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ConversionFailed("the encrypted copy does not pass its integrity check")
            if _counts(made) != counts:
                raise ConversionFailed("the encrypted copy does not hold every row")
            if sample is not None:
                found = made.execute(
                    "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY chunk_id",
                    (sample[0],),
                ).fetchall()
                if [str(r[0]) for r in found] != sample[1]:
                    raise ConversionFailed("the encrypted copy's search index finds otherwise")
        finally:
            made.close()
        if is_plaintext(copy):
            raise ConversionFailed("the copy was written unencrypted")
        if check is not None:
            check(copy)
        _sync(copy)
    except Exception:
        for leftover in (copy, *_companions(copy)):
            if leftover.exists():
                shred(leftover)
        raise
    # Swap: the plain file aside, the encrypted one in, checked, then the plain one destroyed.
    for stale in _companions(target):
        if stale.exists():
            shred(stale)
    aside = target.with_name(target.name + ".plaintext")
    os.replace(target, aside)
    os.replace(copy, target)
    try:
        reopened = open_database(target, key)
        try:
            if _counts(reopened) != counts:
                raise ConversionFailed("the encrypted database did not reopen whole")
        finally:
            reopened.close()
    except Exception:
        os.replace(target, copy)
        os.replace(aside, target)
        shred(copy)
        raise
    _sync(target)
    shred(aside)
    return {"tables": len(counts), "rows": sum(counts.values())}


def recover_interrupted(path: str | Path, key: bytes | None) -> str | None:
    """After a conversion cut short (the machine lost power mid-swap): put things right before
    anything opens the database. Returns "completed" (the encrypted database opens, the plain
    one left aside is destroyed), "restored" (the plain one put back) or None."""
    target = Path(path)
    aside = target.with_name(target.name + ".plaintext")
    if not aside.exists():
        return None
    if target.exists() and key is not None and is_encrypted(target):
        try:
            con = open_database(target, key)
            try:
                con.execute("PRAGMA integrity_check").fetchone()
            finally:
                con.close()
        except DB_ERRORS + (DatabaseKeyError,):
            pass
        else:
            shred(aside)
            return "completed"
    for stale in _companions(target):
        if stale.exists():
            shred(stale)
    os.replace(aside, target)
    return "restored"
