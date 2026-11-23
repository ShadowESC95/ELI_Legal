"""A closed matter's content, archived out of the way and brought back when it is reopened.

Archiving packs everything a matter's content consists of (its rows in the working database,
its original documents and the files made from it: reports, outbox copies, evidence packs) into
one file, seals it (adapters/local/archive.py: AES-256-GCM, a key of its own), opens it again to
prove it can be read back exactly, and only then removes the content from the working database
and folders, overwritten. The matter's record and its accountability records (runs, reviews,
releases, holds, incidents and the audit ledger) stay where they are, so the matter is still
listed, its history can still be read and verified, and it can be reopened.

Reopening checks the archive, every original's fingerprint and every file's, puts the content
back, and destroys the archive: there is one copy of a case's content, never two.

Destroying an archive (when its retention ends, or by its lead's decision) destroys its key, so
no copy of it anywhere, backups included, can be read again. A preservation hold forbids it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.application.container import AppContext
from eli_legal.application.preservation_service import (
    PreservationHeld,
    _generated,
    _prune,
    active_holds,
)
from eli_legal.domain.errors import AuditIntegrityError, InvalidState
from eli_legal.domain.models import Document, Matter, utcnow
from eli_legal.security.files import private_dir, shred

FORMAT = "eli-legal-matter-archive"


def _work(ctx: AppContext, matter_id: str, what: str) -> Path:
    """A private scratch file beside the working database, for the plain archive in transit.
    It is shredded as soon as it has been used."""
    folder = private_dir(Path(ctx.settings.db_path).parent / "archive_work")
    return folder / f"{matter_id}-{what}-{secrets.token_hex(4)}.zip"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_state(ctx: AppContext, matter: Matter) -> str:
    """'archived' (sealed, out of the working database), 'kept' (still in it) or 'deleted'."""
    if ctx.archive.has(matter.matter_id):
        return "archived"
    mid = matter.matter_id
    if ctx.store.list(Document, mid) or ctx.vault.has_files(mid) or _generated(ctx, mid):
        return "kept"
    return "deleted"


def seal(ctx: AppContext, matter: Matter, *, actor_id: str, reason: str) -> dict[str, Any]:
    """Archive a closed matter's content and take it out of the working database."""
    mid = matter.matter_id
    if ctx.archive.has(mid):
        raise InvalidState("this matter's content is already archived")
    if content_state(ctx, matter) == "deleted":
        raise InvalidState("this matter's content was deleted: there is nothing to archive")
    root = Path(ctx.settings.artifacts_dir)
    content = ctx.store.export_matter_content(mid)
    originals = ctx.vault.stored(mid)
    generated = [p for paths in _generated(ctx, mid).values() for p in paths]
    plain = _work(ctx, mid, "seal")
    check = _work(ctx, mid, "check")
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "version": 1,
        "matter_id": mid,
        "matter_name": matter.name,
        "sealed_at": utcnow().isoformat(),
        "sealed_by": actor_id,
        "reason": reason,
        "eli_legal": __version__,
        "rows": {table: len(block["rows"]) for table, block in content.items()},
        "originals": originals,
        "generated": {},
    }
    try:
        with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_DEFLATED) as z:
            records = json.dumps(content, ensure_ascii=False).encode("utf-8")
            manifest["content_sha256"] = _sha(records)
            z.writestr("content.json", records)
            for digest in originals:
                z.writestr(f"originals/{digest}", ctx.vault.read(mid, digest))  # hash-checked
            for path in generated:
                rel = path.relative_to(root).as_posix()
                data = path.read_bytes()
                manifest["generated"][rel] = _sha(data)
                z.writestr(f"generated/{rel}", data)
            z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        plain_sha = _sha(plain.read_bytes())
        info = ctx.archive.seal(mid, plain)
        # Proved readable before anything is removed: opened again with its own key, and
        # compared with what was sealed.
        try:
            ctx.archive.open_to(mid, check)
            if _sha(check.read_bytes()) != plain_sha:
                raise AuditIntegrityError("the archive did not read back as it was written")
        except Exception:
            ctx.archive.destroy(mid)
            raise
    finally:
        for scratch in (plain, check):
            if scratch.exists():
                shred(scratch)
    # Now out of the working database and folders, overwritten.
    holds = active_holds(ctx, mid)
    rows = ctx.store.purge_matter_content(mid)
    files = ctx.vault.purge_matter(mid)
    for path in generated:
        shred(path)
    _prune(root, generated)
    erased = ctx.store.compact()
    matter.archived_at = utcnow()
    ctx.store.put_matter(matter)
    ctx.store.empty_log()
    summary = {
        "rows": {k: v for k, v in rows.items() if v},
        "originals": files,
        "generated_files": len(generated),
        "archive_bytes": info.plain_bytes,
        "archive_sha256": info.plain_sha256,
        "encryption": "AES-256-GCM, a key of its own, kept apart from the archive",
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
        output_hash=info.plain_sha256,
        payload={"why": reason, **summary},
    )
    return summary


def restore(ctx: AppContext, matter: Matter) -> dict[str, Any]:
    """Put an archived matter's content back, every fingerprint checked, then destroy the
    archive. Nothing is written until the whole archive has been checked."""
    mid = matter.matter_id
    root = Path(ctx.settings.artifacts_dir).resolve()
    plain = _work(ctx, mid, "restore")
    try:
        info = ctx.archive.open_to(mid, plain)
        with zipfile.ZipFile(plain) as z:
            manifest = json.loads(z.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("matter_id") != mid:
                raise AuditIntegrityError("the archive is not this matter's")
            raw_content = z.read("content.json")
            if _sha(raw_content) != manifest.get("content_sha256"):
                raise AuditIntegrityError("the archived records do not match their fingerprint")
            originals = {}
            for digest in manifest["originals"]:
                data = z.read(f"originals/{digest}")
                if _sha(data) != digest:
                    raise AuditIntegrityError(f"an archived original does not match: {digest[:12]}")
                originals[digest] = data
            files: dict[Path, bytes] = {}
            for rel, digest in manifest["generated"].items():
                target = (root / rel).resolve()
                if root not in target.parents:
                    raise AuditIntegrityError("the archive names a file outside its own folders")
                data = z.read(f"generated/{rel}")
                if _sha(data) != digest:
                    raise AuditIntegrityError(f"an archived file does not match: {rel}")
                files[target] = data
        # All of it checks out: put it back.
        for data in originals.values():
            ctx.vault.store(mid, data)
        for target, data in files.items():
            private_dir(target.parent)
            target.write_bytes(data)
        rows = ctx.store.import_matter_content(mid, json.loads(raw_content))
        missing = [
            d.filename for d in ctx.store.list(Document, mid) if not ctx.vault.verify(mid, d.sha256)
        ]
        if missing:
            raise AuditIntegrityError(
                "restored, but these originals do not check out: " + ", ".join(missing[:5])
            )
    finally:
        if plain.exists():
            shred(plain)
    ctx.archive.destroy(mid)
    return {
        "rows": {k: v for k, v in rows.items() if v},
        "originals": len(originals),
        "generated_files": len(files),
        "archive_sha256": info.plain_sha256,
        "sealed_at": manifest.get("sealed_at", ""),
    }


def destroy(
    ctx: AppContext, matter: Matter, *, actor_id: str, why: str, event: str = "content_disposed"
) -> dict[str, Any]:
    """Destroy a matter's archive for good: its key, then its ciphertext. Refused, and the
    refusal recorded, while any preservation hold is in force on the matter."""
    mid = matter.matter_id
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
            payload={"holds": [h.hold_id for h in holds], "why": why},
        )
        raise PreservationHeld(
            f"a preservation hold is in force on this matter ({holds[0].hold_id}, "
            f"{holds[0].authority}): its archive may not be destroyed until the hold is released"
        )
    info = ctx.archive.destroy(mid)
    if info is None:
        raise InvalidState("this matter has no archive")
    at = utcnow()
    receipt = {
        "matter_id": mid,
        "at": at.isoformat(),
        "actor_id": actor_id,
        "why": why,
        "archive": {
            "sealed_at": info.created_at.isoformat(),
            "sha256": info.plain_sha256,
            "bytes": info.plain_bytes,
        },
        "erasure": {
            "key": "overwritten with zeros, then removed: no copy of the archive, backups "
            "included, can be decrypted again",
            "archive": "ciphertext deleted with secure_delete; the archive database rebuilt",
        },
    }
    folder = Path(ctx.settings.artifacts_dir) / "disposals" / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
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
        output_hash=info.plain_sha256,
        payload={"why": why, "archive_destroyed": True, "receipt": path.name},
    )
    return {"archive_destroyed": True, "archive_sha256": info.plain_sha256, "receipt": path.name}


def sealed_on(ctx: AppContext, matter: Matter) -> datetime | None:
    info = ctx.archive.info(matter.matter_id)
    return info.created_at if info else None
