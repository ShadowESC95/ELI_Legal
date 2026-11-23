"""Case material on disk is readable by the person running ELI Legal and no one else.

The databases hold document text, passphrase hashes and second-factor secrets; the vault holds
the originals; the artifacts folder holds reports, outbox copies and evidence packs. Each folder
is made 0700 and each file 0600 (an original in the vault stays 0400), on a new installation and
on one that was set up before this rule: what an earlier version left group- or world-readable is
tightened when the program starts. The audit key is already refused if it is readable by others.

On Windows the permission bits do not apply; the user's profile folder already keeps others out.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

POSIX = os.name != "nt"
# What a process of ours creates from now on: no group, no other (the entry points set it, never a
# host such as ELI v3, whose own files are its own business).
PRIVATE_UMASK = 0o077


def private_process() -> None:
    """For ELI Legal's own programs: every file and folder created from here on is private."""
    if POSIX:
        os.umask(PRIVATE_UMASK)


def _tighten(path: Path) -> bool:
    """Take away group and other permissions, keeping the owner's as they are. Returns whether
    anything changed. Never follows a link out of the tree."""
    try:
        info = path.lstat()
    except OSError:
        return False
    if sys.platform == "win32":  # permission bits do not apply; the profile folder keeps others out
        return False
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        return False
    mode = stat.S_IMODE(info.st_mode)
    if not mode & 0o077:
        return False
    try:
        path.chmod(mode & 0o700)
    except OSError:
        return False
    return True


def private_dir(path: str | Path) -> Path:
    """A folder of ours, created 0700 if new, tightened if it was not."""
    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if POSIX:
        _tighten(folder)
    return folder


def private_file(path: str | Path) -> None:
    """A database or other file of ours, and SQLite's write-ahead files beside it, 0600."""
    if not POSIX:
        return
    base = Path(path)
    for candidate in (base, Path(f"{base}-wal"), Path(f"{base}-shm"), Path(f"{base}-journal")):
        if candidate.exists():
            _tighten(candidate)


def private_tree(root: str | Path) -> int:
    """Tighten a whole folder of ours, as left by an earlier version. Returns how many changed."""
    if not POSIX:
        return 0
    top = Path(root)
    if not top.exists():
        return 0
    changed = int(_tighten(top))
    for folder, dirs, files in os.walk(top, followlinks=False):
        for name in [*dirs, *files]:
            changed += _tighten(Path(folder) / name)
    return changed


def shred(path: str | Path) -> None:
    """Overwrite a file with zeros, flush it to the disk, then remove it. On a solid-state disk
    or a copy-on-write filesystem the old blocks may survive the overwrite; full-disk encryption
    is what makes them unreadable there. Still far better than unlinking, which leaves them all."""
    target = Path(path)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    size = target.stat().st_size
    with open(target, "r+b", buffering=0) as fh:
        block = b"\0" * min(size, 1 << 20) if size else b""
        left = size
        while left > 0:
            fh.write(block[: min(left, len(block))])
            left -= len(block)
        fh.flush()
        os.fsync(fh.fileno())
    target.unlink()
