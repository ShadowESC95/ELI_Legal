"""Preservation: a legal hold that stops a matter's content from being deleted (EL-004).

A matter's documents can be deleted when it is closed, or by the routine checks once its
retention period ends. A *preservation hold* (litigation hold, a regulator's or court's order,
an expected claim) overrides both: nothing it covers is deleted until it is released.

- ``dispose`` is the only way a matter's content is deleted. A hold on the whole matter refuses
  it outright; a hold on named documents keeps those (their originals, records and text) and
  lets the rest go. Every disposal writes a receipt: the SHA-256 of each original deleted, what
  was kept and under which hold, who and why. The receipt and the audit event hold hashes and
  ids, never content.
- ``PreservationService.place`` may be used by the matter's lead or by anyone who manages
  compliance; preserving more is always safe. ``release`` only by someone who manages
  compliance (the legal or data-protection owner), with identity confirmed again and the reason
  written down. Both are written to the audit trail.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eli_legal.application.container import AppContext
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import Document, Matter, PreservationHold, Run, utcnow
from eli_legal.security import authn
from eli_legal.security.files import shred

MIN_TEXT = 20
MANAGES = "compliance.manage"


class PreservationHeld(InvalidState):
    """A preservation hold covers the whole matter: its content may not be deleted."""


def active_holds(ctx: AppContext, matter_id: str) -> list[PreservationHold]:
    return [h for h in ctx.store.list(PreservationHold, matter_id) if h.status == "active"]


def dispose(
    ctx: AppContext, matter: Matter, *, actor_id: str, why: str, event: str = "content_disposed"
) -> dict[str, int]:
    """Delete a matter's content, keeping whatever a preservation hold covers, with a receipt.
    Raises PreservationHeld, and records the refusal, if a hold covers the whole matter."""
    mid = matter.matter_id
    holds = active_holds(ctx, mid)
    whole = [h for h in holds if h.scope == "matter"]
    if whole:
        ctx.log(
            "disposal_refused",
            actor_id=actor_id,
            matter_id=mid,
            action="matter.close",
            subject_id=whole[0].hold_id,
            outcome="preserved",
            object_type="preservation_hold",
            payload={"holds": [h.hold_id for h in whole], "why": why},
        )
        raise PreservationHeld(
            f"a preservation hold covers this matter ({whole[0].hold_id}, {whole[0].authority}): "
            "its content may not be deleted until the hold is released"
        )
    keep_ids = sorted({d for h in holds for d in h.document_ids})
    generated = _generated(ctx, mid)
    documents = ctx.store.list(Document, mid)
    kept = [d for d in documents if d.document_id in keep_ids]
    going = [d for d in documents if d.document_id not in keep_ids]
    counts = ctx.store.purge_matter_content(mid, keep_document_ids=keep_ids)
    counts["vault_files"] = ctx.vault.purge_matter(mid, keep={d.sha256 for d in kept})
    counts["preserved_documents"] = len(kept)
    deleted = sorted({d.sha256 for d in going} - {d.sha256 for d in kept})
    # What the application made from the matter: reports, outbox copies, evidence packs in its
    # own folders. A report can quote any document, a held one included, so any hold in force
    # keeps them all. Packs exported elsewhere are beyond its control: named, not deleted.
    files_deleted: dict[str, str] = {}
    files_kept: list[str] = []
    for kind, paths in generated.items():
        for path in paths:
            name = f"{kind}/{path.relative_to(Path(ctx.settings.artifacts_dir)).as_posix()}"
            if holds:
                files_kept.append(name)
                continue
            files_deleted[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            shred(path)
    if not holds:
        for paths in generated.values():
            _prune(Path(ctx.settings.artifacts_dir), paths)
    elsewhere = [
        e for e in ctx.audit.events(matter_id=mid)
        if e["event_type"] == "evidence_exported" and not e["payload"].get("managed", False)
    ]  # fmt: skip
    # Nothing of what was deleted is left readable in the database file or its log.
    erased = ctx.store.compact()
    counts["generated_files_deleted"] = len(files_deleted)
    counts["generated_files_kept"] = len(files_kept)
    counts["exported_elsewhere"] = len(elsewhere)
    manifest = hashlib.sha256(
        "\n".join(deleted + [f"{n} {h}" for n, h in sorted(files_deleted.items())]).encode()
    ).hexdigest()
    at = utcnow()
    receipt = {
        "matter_id": mid,
        "at": at.isoformat(),
        "actor_id": actor_id,
        "why": why,
        "deleted_originals_sha256": deleted,
        "manifest_sha256": manifest,
        "preserved_document_ids": keep_ids,
        "generated_files_deleted_sha256": files_deleted,
        "generated_files_kept": files_kept,
        "exported_outside_the_application": [
            {
                "at": e["created_at"],
                "by": e["actor_id"],
                "run_id": e.get("run_id"),
                "manifest_sha256": e.get("output_hash"),
            }
            for e in elsewhere
        ],  # fmt: skip
        "preservation_holds": [h.hold_id for h in holds],
        "counts": counts,
        "erasure": {
            "files": "overwritten with zeros, then removed",
            "database": "deleted rows overwritten; search index merged; file rebuilt (VACUUM)"
            if erased["vacuumed"]
            else f"deleted rows overwritten; rebuild not done ({erased['error']}), retried later",
            "write_ahead_log_emptied": erased["wal_truncated"],
        },
    }
    folder = Path(ctx.settings.artifacts_dir) / "disposals" / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    ctx.log(
        event,
        actor_id=actor_id,
        matter_id=mid,
        action="matter.close",
        subject_id=mid,
        outcome="purged",
        object_type="matter",
        output_hash=manifest,
        payload={
            "why": why,
            "deleted": counts,
            "originals_deleted": len(deleted),
            "preserved_documents": len(kept),
            "holds": [h.hold_id for h in holds],
            "receipt": path.name,
        },
    )
    return counts


def _generated(ctx: AppContext, matter_id: str) -> dict[str, list[Path]]:
    """Every file the application made from a matter, in its own folders, by kind."""
    root = Path(ctx.settings.artifacts_dir)
    runs = [r.run_id for r in ctx.store.list(Run, matter_id)]
    found: dict[str, list[Path]] = {
        "reports": _files(root / "runs" / matter_id),
        "outbox": _files(root / "outbox" / matter_id),
        "evidence": [p for r in runs for p in _files(root / "evidence" / f"evidence_pack_{r}")],
    }
    return {k: v for k, v in found.items() if v}


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []


def _prune(root: Path, paths: list[Path]) -> None:
    """Remove the folders left empty, up to the kind's own folder."""
    for folder in sorted({p.parent for p in paths}, key=lambda f: len(f.parts), reverse=True):
        while folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent


@dataclass(slots=True)
class PreservationService:
    ctx: AppContext

    def _matter(self, matter_id: str) -> Matter:
        matter = self.ctx.store.get_matter(matter_id)
        if matter is None:
            raise NotFound(f"matter not found: {matter_id}")
        return matter

    def _may_place(self, matter: Matter, actor_id: str) -> None:
        bindings = self.ctx.authorizer().bindings
        if bindings.can(actor_id, MANAGES):
            self.ctx.authorizer().require_global(actor_id, MANAGES)
            return
        self.ctx.authorizer().require_matter(matter, actor_id, "matter.close")

    def list(self, matter_id: str, *, actor_id: str) -> list[PreservationHold]:
        matter = self._matter(matter_id)
        if not self.ctx.authorizer().bindings.can(actor_id, MANAGES):
            self.ctx.matter_for(matter.matter_id, actor_id, "matter.read")
        return self.ctx.store.list(PreservationHold, matter.matter_id)

    def place(
        self,
        matter_id: str,
        *,
        actor_id: str,
        legal_basis: str,
        authority: str,
        document_ids: Sequence[str] | None = None,
        review_by: date | None = None,
    ) -> PreservationHold:
        authn.require_step_up(actor_id, "place a preservation hold")
        matter = self._matter(matter_id)
        self._may_place(matter, actor_id)
        legal_basis, authority = " ".join(legal_basis.split()), " ".join(authority.split())
        if len(legal_basis) < MIN_TEXT or not authority:
            raise InvalidInput(
                "say what requires the hold (the order, claim or instruction) and on whose "
                f"authority (at least {MIN_TEXT} characters for the basis)"
            )
        chosen = sorted(set(document_ids or []))
        if chosen:
            known = {d.document_id for d in self.ctx.store.list(Document, matter.matter_id)}
            unknown = [d for d in chosen if d not in known]
            if unknown:
                raise InvalidInput(f"not documents of this matter: {', '.join(unknown)}")
        hold = PreservationHold(
            matter_id=matter.matter_id,
            legal_basis=legal_basis,
            authority=authority,
            opened_by=actor_id,
            scope="documents" if chosen else "matter",
            document_ids=chosen,
            review_by=review_by,
        )
        self.ctx.store.put(hold)
        self.ctx.log(
            "preservation_hold_placed",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="matter.close",
            subject_id=hold.hold_id,
            outcome="active",
            object_type="preservation_hold",
            payload={"scope": hold.scope, "documents": len(chosen)},
        )
        return hold

    def release(
        self, matter_id: str, hold_id: str, *, actor_id: str, reason: str
    ) -> PreservationHold:
        authn.require_step_up(actor_id, "release a preservation hold")
        matter = self._matter(matter_id)
        if not self.ctx.authorizer().bindings.can(actor_id, MANAGES):
            raise PolicyDenied(
                "only the legal or data-protection owner (an account that manages compliance) "
                "may release a preservation hold"
            )
        self.ctx.authorizer().require_global(actor_id, MANAGES)
        reason = " ".join(reason.split())
        if len(reason) < MIN_TEXT:
            raise InvalidInput(
                f"say why the hold may end, and on whose authority (at least {MIN_TEXT} characters)"
            )

        def end(h: PreservationHold) -> None:
            if h.status != "active":
                raise InvalidState("this preservation hold has already been released")
            h.status, h.released_by, h.released_at = "released", actor_id, utcnow()
            h.release_reason = reason

        hold = self.ctx.store.change(PreservationHold, matter.matter_id, hold_id, end)
        self.ctx.log(
            "preservation_hold_released",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action=MANAGES,
            subject_id=hold.hold_id,
            outcome="released",
            object_type="preservation_hold",
            payload={"scope": hold.scope},
        )
        return hold
