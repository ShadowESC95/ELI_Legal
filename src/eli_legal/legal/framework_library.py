"""The library of law and standards packages, and who approved what.

Shipped packs are summaries prepared for this software. They may be used at once, and every report
says that they are unvalidated until a qualified lawyer's sign-off is recorded against the exact
version. An organisation's own packs are refused until an authorised person approves the exact
version in their own name; changing a pack's content withdraws that approval.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eli_legal.domain.errors import InvalidInput, NotFound, VerificationGateFailed
from eli_legal.domain.models import utcnow
from eli_legal.legal.frameworks import SHIPPED_DIR, FrameworkPack, load_shipped, pack_from
from eli_legal.persistence.sqlite import Store
from eli_legal.security.prompt_injection import PromptInjectionDetector

_PACK = "framework_pack"
_STATUS = "framework_status"


@dataclass(slots=True)
class StoredPack:
    """An organisation's pack as imported."""

    pack_id: str
    content: str  # the pack as JSON
    imported_by: str
    imported_from: str = ""  # the file it came from
    imported_at: datetime = field(default_factory=utcnow)
    flags: list[str] = field(default_factory=list)  # text that looks addressed to an AI system


@dataclass(slots=True)
class PackStatus:
    pack_id: str
    approved_sha: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    validated_sha: str = ""
    validated_by: str = ""  # the qualified lawyer who signed it off
    validation_recorded_by: str = ""
    validated_at: datetime | None = None
    withdrawn: bool = False
    withdrawn_by: str = ""
    withdrawn_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PackState:
    pack: FrameworkPack
    usable: bool
    why: str  # why not, or the standing it has
    validated: bool
    approved_by: str
    validated_by: str
    flags: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        p = self.pack
        return {
            "id": p.pack_id,
            "title": p.title,
            "short_title": p.short_title,
            "scope": p.scope,
            "jurisdictions": list(p.jurisdictions),
            "instrument": p.instrument,
            "issuer": p.issuer,
            "version": p.version,
            "as_at": p.as_at,
            "origin": p.origin,
            "example": p.example,
            "requirements": len(p.requirements),
            "recommend_for": list(p.recommend_for),
            "fingerprint": p.fingerprint,
            "usable": self.usable,
            "standing": self.why,
            "validated": self.validated,
            "approved_by": self.approved_by,
            "validated_by": self.validated_by,
            "flags": list(self.flags),
        }


def scan_pack(pack: FrameworkPack, detector: PromptInjectionDetector) -> list[str]:
    """Requirements whose text reads as an attempt to steer an AI system outside its rules."""
    flags = []
    for r in pack.requirements:
        for text in (r.text, r.instruction, r.statement):
            if text and detector.assess(text).suspicious:
                flags.append(r.req_id)
                break
    return flags


class FrameworkLibrary:
    def __init__(self, store: Store, shipped_dir: Path = SHIPPED_DIR) -> None:
        self.store = store
        self.shipped = load_shipped(shipped_dir)

    # ── reading ──────────────────────────────────────────────────────────────
    def _stored(self) -> dict[str, StoredPack]:
        return {s.pack_id: s for s in self.store.list_registry(_PACK, StoredPack)}

    def _status(self, pack_id: str) -> PackStatus:
        return self.store.get_registry(_STATUS, pack_id, PackStatus) or PackStatus(pack_id)

    def get(self, pack_id: str) -> FrameworkPack | None:
        if pack_id in self.shipped:
            return self.shipped[pack_id]
        stored = self.store.get_registry(_PACK, pack_id, StoredPack)
        return pack_from(json.loads(stored.content), origin="organisation") if stored else None

    def require(self, pack_id: str) -> FrameworkPack:
        pack = self.get(pack_id)
        if pack is None:
            raise NotFound(f"no law or standards package with the id {pack_id!r}")
        return pack

    def all(self) -> list[FrameworkPack]:
        org = [
            pack_from(json.loads(s.content), origin="organisation") for s in self._stored().values()
        ]
        return sorted([*self.shipped.values(), *org], key=lambda p: (_ORDER[p.scope], p.title))

    def state(self, pack: FrameworkPack) -> PackState:
        status = self._status(pack.pack_id)
        stored = (
            None
            if pack.origin == "shipped"
            else self.store.get_registry(_PACK, pack.pack_id, StoredPack)
        )
        flags = tuple(stored.flags) if stored else ()
        validated = bool(pack.validated_by) or status.validated_sha == pack.sha256
        validated_by = pack.validated_by or (status.validated_by if validated else "")
        if status.withdrawn:
            usable, why = False, f"withdrawn by {status.withdrawn_by}"
        elif pack.origin == "shipped":
            usable = True
            why = (
                f"validated by {validated_by}"
                if validated
                else "summary prepared for this software; not validated by a qualified lawyer"
            )
        elif flags:
            usable, why = (
                False,
                f"cannot be used: requirement(s) {', '.join(flags)} read as instructions aimed at an AI system",
            )
        elif status.approved_sha == pack.sha256:
            usable, why = True, f"approved by {status.approved_by}"
        elif status.approved_sha:
            usable, why = False, "changed since it was approved; it must be approved again"
        else:
            usable, why = False, "not yet approved"
        return PackState(pack, usable, why, validated, status.approved_by, validated_by, flags)

    def states(self) -> list[PackState]:
        return [self.state(p) for p in self.all()]

    def usable(self, pack_ids: Iterable[str]) -> list[FrameworkPack]:
        """The packs named, refusing any that cannot be used, with the reason."""
        out = []
        for pack_id in pack_ids:
            state = self.state(self.require(pack_id))
            if not state.usable:
                raise InvalidInput(f"{state.pack.title}: {state.why}")
            out.append(state.pack)
        return out

    def recommended(self, profile: str, codes: Iterable[str]) -> list[str]:
        codes = set(codes)
        return [
            s.pack.pack_id
            for s in self.states()
            if s.usable
            and not s.pack.example
            and profile in s.pack.recommend_for
            and s.pack.covers(codes)
        ]

    def for_run(self, versions: dict[str, str]) -> list[FrameworkPack]:
        """The packs a run was prepared under, exactly as they were. A pack that has changed
        since cannot silently stand in for the one the run used."""
        out = []
        for pack_id, fingerprint in versions.items():
            pack = self.get(pack_id)
            if pack is None or pack.fingerprint != fingerprint:
                raise VerificationGateFailed(
                    f"the law and standards package {pack_id!r} has changed or been removed since "
                    "this run was prepared; restart the run so the report reflects what applies now"
                )
            out.append(pack)
        return out

    # ── changing ─────────────────────────────────────────────────────────────
    def put_organisation_pack(
        self, pack: FrameworkPack, *, by: str, imported_from: str, flags: Sequence[str]
    ) -> None:
        if pack.pack_id in self.shipped:
            raise InvalidInput(
                f"{pack.pack_id!r} is the id of a package that ships with the software; choose another"
            )
        from eli_legal.legal.frameworks import pack_to_dict

        content = json.dumps(pack_to_dict(pack), ensure_ascii=False, sort_keys=True)
        self.store.put_registry(
            _PACK,
            pack.pack_id,
            StoredPack(pack.pack_id, content, by, imported_from[:200], flags=list(flags)),
        )

    def approve(self, pack_id: str, *, by: str) -> PackState:
        pack = self.require(pack_id)
        if pack.origin == "shipped":
            raise InvalidInput(
                "a package shipped with the software needs no approval to be used; record a "
                "qualified lawyer's validation of it instead"
            )
        stored = self.store.get_registry(_PACK, pack_id, StoredPack)
        if stored and stored.flags:
            raise InvalidInput(
                f"requirement(s) {', '.join(stored.flags)} read as instructions aimed at an AI "
                "system; remove or reword them and import the package again"
            )
        status = self._status(pack_id)
        status.approved_sha, status.approved_by, status.approved_at = pack.sha256, by, utcnow()
        status.withdrawn = False
        self.store.put_registry(_STATUS, pack_id, status)
        return self.state(pack)

    def validate(self, pack_id: str, *, lawyer: str, by: str) -> PackState:
        pack = self.require(pack_id)
        if len(lawyer.strip()) < 3:
            raise InvalidInput("name the qualified lawyer who validated the package")
        status = self._status(pack_id)
        status.validated_sha, status.validated_by = pack.sha256, lawyer.strip()[:200]
        status.validation_recorded_by, status.validated_at = by, utcnow()
        self.store.put_registry(_STATUS, pack_id, status)
        return self.state(pack)

    def withdraw(self, pack_id: str, *, by: str) -> PackState:
        pack = self.require(pack_id)
        status = self._status(pack_id)
        status.withdrawn, status.withdrawn_by, status.withdrawn_at = True, by, utcnow()
        self.store.put_registry(_STATUS, pack_id, status)
        return self.state(pack)

    def remove(self, pack_id: str) -> None:
        """Delete an organisation's pack. Runs that used it keep its fingerprint in their record;
        a report built on it can no longer be approved, which is the point."""
        if pack_id in self.shipped:
            raise InvalidInput("a package shipped with the software can be withdrawn, not deleted")
        if not self.store.delete_registry(_PACK, pack_id):
            raise NotFound(f"no organisation package with the id {pack_id!r}")
        self.store.delete_registry(_STATUS, pack_id)

    def reinstate(self, pack_id: str) -> PackState:
        pack = self.require(pack_id)
        status = self._status(pack_id)
        status.withdrawn = False
        self.store.put_registry(_STATUS, pack_id, status)
        return self.state(pack)


_ORDER = {
    s: i
    for i, s in enumerate(
        ("international", "regional", "national", "sectoral", "professional", "organisational")
    )
}
