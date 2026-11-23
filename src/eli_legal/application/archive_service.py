"""A closed matter's content, archived out of the way kind by kind, and brought back when it is
reopened.

Each kind of content (governance/retention.py: papers, analysis, reports, evidence packs) is
packed into one file: its rows in the working database, and its files (the originals for papers;
the report and outbox files for reports; the packs for evidence). It is sealed under a key of its
own (adapters/local/archive.py: AES-256-GCM), opened again to prove it reads back exactly, and only
then removed from the working database and folders, overwritten. Each kind can then be destroyed
when its own retention period ends, by destroying its key, while the others are kept.

The matter's record and its decision record (runs, reviews, releases, holds, incidents and the
audit ledger) stay where they are, so the matter is still listed, its history can still be read
and verified, and it can be reopened. Reopening checks each archive, every original's and every
file's fingerprint, puts the content back and destroys the archives: one copy of a case's
content, never two.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.adapters.local.archive import LEGACY
from eli_legal.application.container import AppContext
from eli_legal.application.preservation_service import (
    PreservationHeld,
    _generated,
    _prune,
    active_holds,
)
from eli_legal.domain.errors import AuditIntegrityError, InvalidState
from eli_legal.domain.models import Document, Matter, utcnow
from eli_legal.governance.retention import (
    CONTENT,
    KINDS,
    RECORD,
    Kind,
    kind_of_file,
    kind_of_table,
)
from eli_legal.security.files import private_dir, shred

FORMAT = "eli-legal-matter-archive"
SYSTEM = "system"


def _work(ctx: AppContext, matter_id: str, what: str) -> Path:
    """A private scratch file beside the working database, for a plain archive in transit.
    It is shredded as soon as it has been used."""
    folder = private_dir(Path(ctx.settings.db_path).parent / "archive_work")
    return folder / f"{matter_id}-{what}-{secrets.token_hex(4)}.zip"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(ctx: AppContext, matter_id: str, kind: Kind) -> list[Path]:
    made = _generated(ctx, matter_id)
    return [p for f in kind.files for p in made.get(f, [])]


def live(ctx: AppContext, matter: Matter, kind: Kind) -> bool:
    """Whether any of this kind of the matter's content is in the working database or folders."""
    mid = matter.matter_id
    if kind.tables and ctx.store.count_rows(mid, kind.tables):
        return True
    if kind.vault and ctx.vault.has_files(mid):
        return True
    return bool(_files(ctx, mid, kind))


def kind_state(ctx: AppContext, matter: Matter, kind: Kind) -> str:
    """'archived', 'kept' (in the working database) or 'deleted' (or never had any)."""
    if ctx.archive.has(matter.matter_id, kind.code):
        return "archived"
    return "kept" if live(ctx, matter, kind) else "deleted"


def content_state(ctx: AppContext, matter: Matter) -> str:
    """The matter's content as a whole: 'archived' if any of it is, else 'kept' if any of it is
    in the working database, else 'deleted'."""
    states = {kind_state(ctx, matter, k) for k in CONTENT}
    if ctx.archive.has(matter.matter_id, LEGACY) or "archived" in states:
        return "archived"
    return "kept" if "kept" in states else "deleted"


# ── packing ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Pack:
    rows: dict[str, Any]
    originals: dict[str, bytes]
    files: dict[str, bytes]  # path under the artifacts folder → plain bytes


def _write_pack(
    ctx: AppContext, matter: Matter, kind: str, pack: _Pack, actor_id: str, reason: str
) -> Path:
    plain = _work(ctx, matter.matter_id, f"seal-{kind}")
    records = json.dumps(pack.rows, ensure_ascii=False).encode("utf-8")
    manifest = {
        "format": FORMAT,
        "version": 2,
        "kind": kind,
        "matter_id": matter.matter_id,
        "matter_name": matter.name,
        "sealed_at": utcnow().isoformat(),
        "sealed_by": actor_id,
        "reason": reason,
        "eli_legal": __version__,
        "rows": {table: len(block["rows"]) for table, block in pack.rows.items()},
        "content_sha256": _sha(records),
        "originals": sorted(pack.originals),
        "generated": {rel: _sha(data) for rel, data in sorted(pack.files.items())},
    }
    with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.json", records)
        for digest, data in pack.originals.items():
            z.writestr(f"originals/{digest}", data)
        for rel, data in pack.files.items():
            z.writestr(f"generated/{rel}", data)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return plain


def _read_pack(path: Path, matter_id: str, root: Path) -> tuple[dict[str, Any], _Pack]:
    """Open a plain archive and check every fingerprint in it. Nothing is written."""
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("matter_id") != matter_id:
            raise AuditIntegrityError("the archive is not this matter's")
        raw = z.read("content.json")
        if _sha(raw) != manifest.get("content_sha256"):
            raise AuditIntegrityError("the archived records do not match their fingerprint")
        originals = {}
        for digest in manifest["originals"]:
            data = z.read(f"originals/{digest}")
            if _sha(data) != digest:
                raise AuditIntegrityError(f"an archived original does not match: {digest[:12]}")
            originals[digest] = data
        files = {}
        for rel, digest in manifest["generated"].items():
            target = (root / rel).resolve()
            if root not in target.parents:
                raise AuditIntegrityError("the archive names a file outside its own folders")
            data = z.read(f"generated/{rel}")
            if _sha(data) != digest:
                raise AuditIntegrityError(f"an archived file does not match: {rel}")
            files[rel] = data
    return manifest, _Pack(json.loads(raw), originals, files)


def _seal_pack(
    ctx: AppContext, matter: Matter, kind: str, pack: _Pack, actor_id: str, reason: str
) -> dict[str, Any]:
    """Seal one kind and prove it reads back. Nothing is removed here."""
    mid = matter.matter_id
    plain = _write_pack(ctx, matter, kind, pack, actor_id, reason)
    check = _work(ctx, mid, f"check-{kind}")
    try:
        plain_sha = _sha(plain.read_bytes())
        info = ctx.archive.seal(mid, kind, plain)
        try:
            ctx.archive.open_to(mid, kind, check)
            if _sha(check.read_bytes()) != plain_sha:
                raise AuditIntegrityError("the archive did not read back as it was written")
        except Exception:
            ctx.archive.destroy(mid, kind)
            raise
    finally:
        for scratch in (plain, check):
            if scratch.exists():
                shred(scratch)
    return {
        "sha256": info.plain_sha256,
        "bytes": info.plain_bytes,
        "rows": sum(len(b["rows"]) for b in pack.rows.values()),
        "originals": len(pack.originals),
        "files": len(pack.files),
    }


def _take(ctx: AppContext, matter: Matter, kind: Kind) -> tuple[_Pack, list[Path]]:
    """One kind of the matter's live content, read in plain, and the files it came from."""
    mid = matter.matter_id
    root = Path(ctx.settings.artifacts_dir)
    rows = ctx.store.export_matter_content(mid, list(kind.tables)) if kind.tables else {}
    originals = {d: ctx.vault.read(mid, d) for d in ctx.vault.stored(mid)} if kind.vault else {}
    paths = _files(ctx, mid, kind)
    files = {p.relative_to(root).as_posix(): ctx.files.read(mid, p) for p in paths}
    return _Pack(rows, originals, files), paths


def _remove(ctx: AppContext, matter: Matter, kind: Kind, paths: list[Path]) -> None:
    """Take one kind out of the working database and folders, overwritten, its key destroyed."""
    mid = matter.matter_id
    if kind.tables:
        ctx.store.purge_tables(mid, kind.tables)
    if kind.vault:
        ctx.vault.purge_matter(mid)
    for path in paths:
        shred(path)
    _prune(Path(ctx.settings.artifacts_dir), paths)
    if kind.files:
        ctx.files.keys.destroy(mid, kind.code)


# ── archive, restore, destroy ────────────────────────────────────────────────


def seal(ctx: AppContext, matter: Matter, *, actor_id: str, reason: str) -> dict[str, Any]:
    """Archive a closed matter's content, each kind under its own key, and take it out of the
    working database and folders."""
    mid = matter.matter_id
    present = [k for k in CONTENT if live(ctx, matter, k)]
    if not present:
        if content_state(ctx, matter) == "archived":
            raise InvalidState("this matter's content is already archived")
        raise InvalidState("this matter's content was deleted: there is nothing to archive")
    taken = {k.code: _take(ctx, matter, k) for k in present if not ctx.archive.has(mid, k.code)}
    if not taken:
        raise InvalidState("this matter's content is already archived")
    sealed: dict[str, Any] = {}
    try:
        for code, (pack, _paths) in taken.items():
            sealed[code] = _seal_pack(ctx, matter, code, pack, actor_id, reason)
    except Exception:
        for code in sealed:  # all or nothing: what was sealed is undone, nothing was removed
            ctx.archive.destroy(mid, code)
        raise
    holds = active_holds(ctx, mid)
    for code, (_pack, paths) in taken.items():
        _remove(ctx, matter, KINDS[code], paths)
    erased = ctx.store.compact()
    matter.archived_at = utcnow()
    ctx.store.put_matter(matter)
    ctx.store.empty_log()
    summary = {
        "kinds": sealed,
        "encryption": "AES-256-GCM, each kind under a key of its own, kept apart from the archive",
        "working_copy": "overwritten and removed; database rebuilt"
        if erased["vacuumed"]
        else f"overwritten and removed; rebuild not done ({erased['error']}), retried later",
        "preservation_holds": [h.hold_id for h in holds],
    }
    ctx.log(
        "matter_archived",
        actor_id=actor_id,
        matter_id=mid,
        action="matter.close",
        subject_id=mid,
        outcome="archived",
        object_type="matter",
        output_hash=_sha("\n".join(f"{k} {v['sha256']}" for k, v in sealed.items()).encode()),
        payload={"why": reason, **summary},
    )
    return summary


def _put_back(ctx: AppContext, mid: str, pack: _Pack) -> dict[str, int]:
    root = Path(ctx.settings.artifacts_dir)
    for data in pack.originals.values():
        ctx.vault.store(mid, data)
    for rel, data in pack.files.items():
        ctx.files.write(mid, root / rel, data)
    return ctx.store.import_matter_content(mid, pack.rows) if pack.rows else {}


def restore(ctx: AppContext, matter: Matter) -> dict[str, Any]:
    """Put a matter's archived content back, every fingerprint checked, then destroy the
    archives. Nothing is written until every archive has been opened and checked."""
    mid = matter.matter_id
    root = Path(ctx.settings.artifacts_dir).resolve()
    opened: dict[str, tuple[dict[str, Any], _Pack]] = {}
    for kind in ctx.archive.kinds(mid):
        plain = _work(ctx, mid, f"restore-{kind}")
        try:
            ctx.archive.open_to(mid, kind, plain)
            opened[kind] = _read_pack(plain, mid, root)
        finally:
            if plain.exists():
                shred(plain)
    restored: dict[str, Any] = {}
    for kind, (manifest, pack) in opened.items():
        rows = _put_back(ctx, mid, pack)
        restored[kind] = {
            "rows": sum(rows.values()),
            "originals": len(pack.originals),
            "files": len(pack.files),
            "sealed_at": manifest.get("sealed_at", ""),
        }
    missing = [
        d.filename for d in ctx.store.list(Document, mid) if not ctx.vault.verify(mid, d.sha256)
    ]
    if missing:
        raise AuditIntegrityError(
            "restored, but these originals do not check out: " + ", ".join(missing[:5])
        )
    for kind in opened:
        ctx.archive.destroy(mid, kind)
    return restored


def destroy(
    ctx: AppContext,
    matter: Matter,
    *,
    actor_id: str,
    why: str,
    event: str = "content_disposed",
    kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Destroy a matter's archives (or those of the kinds named) for good: each key, then its
    ciphertext. Refused, and the refusal recorded, while any preservation hold is in force."""
    mid = matter.matter_id
    wanted = list(ctx.archive.kinds(mid) if kinds is None else kinds)
    holds = active_holds(ctx, mid)
    if holds:
        ctx.log(
            "disposal_refused",
            actor_id=actor_id,
            matter_id=mid,
            action="matter.close",
            subject_id=holds[0].hold_id,
            outcome="preserved",
            object_type="preservation_hold",
            payload={"holds": [h.hold_id for h in holds], "why": why, "kinds": wanted},
        )
        raise PreservationHeld(
            f"a preservation hold is in force on this matter ({holds[0].hold_id}, "
            f"{holds[0].authority}): its archive may not be destroyed until the hold is released"
        )
    gone = {}
    for kind in wanted:
        info = ctx.archive.destroy(mid, kind)
        if info is not None:
            gone[kind] = {
                "sealed_at": info.created_at.isoformat(),
                "sha256": info.plain_sha256,
                "bytes": info.plain_bytes,
            }
    if not gone:
        raise InvalidState("this matter has no archive of that content")
    at = utcnow()
    digest = _sha("\n".join(f"{k} {v['sha256']}" for k, v in sorted(gone.items())).encode())
    receipt = {
        "matter_id": mid,
        "at": at.isoformat(),
        "actor_id": actor_id,
        "why": why,
        "archives": gone,
        "archives_sha256": digest,
        "erasure": {
            "key": "each key overwritten with zeros, then removed: no copy of those archives, "
            "backups included, can be decrypted again",
            "archive": "ciphertext deleted with secure_delete; the archive database rebuilt",
        },
    }
    folder = Path(ctx.settings.artifacts_dir) / "disposals" / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    if not ctx.archive.has(mid):
        matter.archived_at = None
        ctx.store.put_matter(matter)
    ctx.log(
        event,
        actor_id=actor_id,
        matter_id=mid,
        action="matter.close",
        subject_id=mid,
        outcome="purged",
        object_type="matter",
        output_hash=digest,
        payload={"why": why, "archives_destroyed": sorted(gone), "receipt": path.name},
    )
    return {"archives_destroyed": sorted(gone), "archives_sha256": digest, "receipt": path.name}


def forget_record(ctx: AppContext, matter: Matter, *, actor_id: str, why: str) -> dict[str, Any]:
    """Remove a closed matter's decision record and the matter itself, once its own retention
    has ended and nothing it accounts for is left. The audit ledger keeps what happened."""
    mid = matter.matter_id
    if active_holds(ctx, mid):
        raise PreservationHeld("a preservation hold is in force on this matter")
    if any(ctx.archive.has(mid, k.code) or live(ctx, matter, k) for k in CONTENT):
        raise InvalidState("the decision record outlives the content it accounts for")
    counts = ctx.store.purge_tables(mid, RECORD.tables)
    ctx.store.delete_matter(mid)
    for kind in CONTENT:
        ctx.files.keys.destroy(mid, kind.code)
    erased = ctx.store.compact()
    ctx.store.empty_log()
    at = utcnow()
    receipt = {
        "matter_id": mid,
        "matter_name": matter.name,
        "at": at.isoformat(),
        "actor_id": actor_id,
        "why": why,
        "record_rows_deleted": counts,
        "database_rebuilt": erased["vacuumed"],
    }
    folder = Path(ctx.settings.artifacts_dir) / "disposals" / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{at.strftime('%Y%m%dT%H%M%S%fZ')}-record.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    ctx.log(
        "record_disposed",
        actor_id=actor_id,
        matter_id=mid,
        action="matter.close",
        subject_id=mid,
        outcome="purged",
        object_type="matter",
        payload={"why": why, "deleted": counts, "receipt": path.name},
    )
    return {"deleted": counts, "receipt": path.name}


# ── at start: what earlier versions left ─────────────────────────────────────


def _split_legacy(ctx: AppContext, matter: Matter) -> list[str]:
    """0.8.15 kept one archive for all of a matter's content. Split it into kinds, each sealed
    under its own key and proved, then destroy the old one."""
    mid = matter.matter_id
    root = Path(ctx.settings.artifacts_dir).resolve()
    plain = _work(ctx, mid, "legacy")
    try:
        ctx.archive.open_to(mid, LEGACY, plain)
        manifest, whole = _read_pack(plain, mid, root)
    finally:
        if plain.exists():
            shred(plain)
    packs: dict[str, _Pack] = {}

    def pack(kind: str) -> _Pack:
        return packs.setdefault(kind, _Pack({}, {}, {}))

    for table, block in whole.rows.items():
        if block["rows"]:
            pack(kind_of_table(table)).rows[table] = block
    for digest, data in whole.originals.items():
        pack("papers").originals[digest] = data
    for rel, data in whole.files.items():
        pack(kind_of_file(rel)).files[rel] = data
    reason = str(manifest.get("reason", "")) or "archived by an earlier version"
    done: list[str] = []
    try:
        for kind, p in packs.items():
            if not ctx.archive.has(mid, kind):
                _seal_pack(ctx, matter, kind, p, str(manifest.get("sealed_by", "")), reason)
                done.append(kind)
    except Exception:
        for kind in done:
            ctx.archive.destroy(mid, kind)
        raise
    ctx.archive.destroy(mid, LEGACY)
    return done


def upgrade(ctx: AppContext) -> dict[str, int]:
    """Bring what earlier versions stored up to this one's protection: originals and the files
    made from each matter sealed on disk, and 0.8.15's single archives split by kind. Safe to run
    at every start; what is done already is left."""
    counts = {"originals_sealed": 0, "files_sealed": 0, "archives_split": 0}
    matters = {m.matter_id: m for m in ctx.store.list_matters()}
    for mid, matter in matters.items():
        counts["originals_sealed"] += ctx.vault.seal_existing(mid)
        for paths in _generated(ctx, mid).values():
            for path in paths:
                counts["files_sealed"] += int(ctx.files.seal_existing(mid, path))
        if ctx.archive.has(mid, LEGACY):
            _split_legacy(ctx, matter)
            counts["archives_split"] += 1
    if any(counts.values()):
        ctx.log(
            "storage_upgraded",
            actor_id=SYSTEM,
            matter_id="-",
            action="config.manage",
            subject_id="-",
            outcome="sealed",
            object_type="storage",
            payload=counts,
        )
    return counts


def kinds_named(codes: Sequence[str]) -> list[Kind]:
    return [KINDS[c] for c in codes]
