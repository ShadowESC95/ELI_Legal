"""Law and standards packages: the library, an organisation's own packages, and which apply to a
matter. Every change is recorded; approving or validating a package is a decision in a named
person's name and needs their passphrase again."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.domain.errors import InvalidInput
from eli_legal.domain.models import Matter
from eli_legal.governance.registers import load_register
from eli_legal.legal.framework_library import PackState, scan_pack
from eli_legal.legal.frameworks import (
    FrameworkPack,
    compile_context,
    pack_from,
    pack_from_csv,
    pack_from_paragraphs,
    pack_to_dict,
    slug,
)
from eli_legal.security import authn

# The builtin, for annotations in a class with a method named `list`.
_List = list
MAX_IMPORT_BYTES = 20 * 1024 * 1024


class FrameworkService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # ── reading: any signed-in person may read the library ────────────────────
    def list(self, *, actor_id: str) -> _List[PackState]:
        authn.require(actor_id)
        return self.ctx.frameworks.states()

    def get(self, pack_id: str, *, actor_id: str) -> PackState:
        authn.require(actor_id)
        return self.ctx.frameworks.state(self.ctx.frameworks.require(pack_id))

    def export(self, pack_id: str, *, actor_id: str) -> str:
        """The package as JSON, to edit and import again as an organisation's own."""
        authn.require(actor_id)
        return (
            json.dumps(
                pack_to_dict(self.ctx.frameworks.require(pack_id)), indent=2, ensure_ascii=False
            )
            + "\n"
        )

    def recommended(self, profile: str, jurisdiction: str, *, actor_id: str) -> _List[str]:
        authn.require(actor_id)
        probe = Matter(name="-", purpose="-", jurisdiction=jurisdiction, owner_user_id=actor_id)
        return self.ctx.frameworks.recommended(
            profile, self.ctx.jurisdictions.jurisdiction_codes(probe)
        )

    # ── an organisation's own packages ────────────────────────────────────────
    def import_file(
        self,
        filename: str,
        raw: bytes,
        *,
        actor_id: str,
        title: str = "",
        pack_id: str = "",
        issuer: str = "",
        version: str = "1",
    ) -> PackState:
        """Import a package: a JSON pack, a CSV requirements register, or a document of the
        organisation's rules (PDF, Word, ODT, RTF, HTML, e-mail or text). It cannot be used on any
        matter until someone with the right approves it."""
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        if len(raw) > MAX_IMPORT_BYTES:
            raise InvalidInput("the file is too large for a law or standards package")
        name = Path(filename).name or "package"
        suffix = Path(name).suffix.lower()
        stem = title.strip() or Path(name).stem.replace("_", " ").strip() or "Organisation standard"
        wanted_id = (pack_id.strip().lower() or f"org-{slug(stem)}")[:64]
        if suffix == ".json":
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise InvalidInput(f"{name} is not valid JSON") from exc
            if isinstance(data, dict):
                data = {**data, "scope": data.get("scope") or "organisational"}
                if pack_id:
                    data["id"] = wanted_id
                data.pop("example", None)
            pack = pack_from(data, origin="organisation")
        elif suffix == ".csv":
            pack = pack_from_csv(raw, pack_id=wanted_id, title=stem, issuer=issuer, version=version)
        else:
            parsed = self.ctx.parser.parse(name, raw)
            paragraphs = [
                (seg.locator, para)
                for seg in parsed.segments
                for para in re.split(
                    r"\n\s*\n|\n(?=\s*(?:\d+[.)]|\([a-z0-9]+\)|[A-Z][.)])\s)", seg.text
                )
                if para.strip()
            ]
            pack = pack_from_paragraphs(
                paragraphs, pack_id=wanted_id, title=stem, issuer=issuer, version=version
            )
        self._check_controls(pack)
        flags = scan_pack(pack, self.ctx.detector)
        self.ctx.frameworks.put_organisation_pack(
            pack, by=actor_id, imported_from=name, flags=flags
        )
        self._log(actor_id, pack, "framework_imported", "imported", flags=flags, file=name)
        return self.ctx.frameworks.state(pack)

    def _check_controls(self, pack: FrameworkPack) -> None:
        known = {row["control_id"] for row in load_register("controls")}
        unknown = sorted({c for r in pack.requirements for c in r.controls} - known)
        if unknown:
            raise InvalidInput(
                f"requirement(s) name control(s) that do not exist: {', '.join(unknown)}. Use "
                "'instruction', 'attestation', 'disclosure' or 'note' for a requirement the system's "
                "own controls do not carry out."
            )

    def approve(self, pack_id: str, *, actor_id: str) -> PackState:
        authn.require_step_up(actor_id, "approve a law or standards package")
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        state = self.ctx.frameworks.approve(pack_id, by=actor_id)
        self._log(actor_id, state.pack, "framework_approved", "approved")
        return state

    def validate(self, pack_id: str, *, actor_id: str, lawyer: str) -> PackState:
        """Record that a qualified lawyer has checked this exact version against its source."""
        authn.require_step_up(actor_id, "record a lawyer's validation of a package")
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        state = self.ctx.frameworks.validate(pack_id, lawyer=lawyer, by=actor_id)
        self._log(actor_id, state.pack, "framework_validated", "validated", lawyer=lawyer[:200])
        return state

    def withdraw(self, pack_id: str, *, actor_id: str) -> PackState:
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        state = self.ctx.frameworks.withdraw(pack_id, by=actor_id)
        self._log(actor_id, state.pack, "framework_withdrawn", "withdrawn")
        return state

    def reinstate(self, pack_id: str, *, actor_id: str) -> PackState:
        authn.require_step_up(actor_id, "reinstate a law or standards package")
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        state = self.ctx.frameworks.reinstate(pack_id)
        self._log(actor_id, state.pack, "framework_reinstated", "reinstated")
        return state

    def remove(self, pack_id: str, *, actor_id: str) -> None:
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        pack = self.ctx.frameworks.require(pack_id)
        self.ctx.frameworks.remove(pack_id)
        self._log(actor_id, pack, "framework_removed", "removed")

    # ── a matter's packages ──────────────────────────────────────────────────
    def for_matter(self, matter_id: str, *, actor_id: str) -> _List[PackState]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        return [
            self.ctx.frameworks.state(self.ctx.frameworks.require(i))
            for i in matter.framework_ids
            if self.ctx.frameworks.get(i)
        ]

    def set_for_matter(self, matter_id: str, *, actor_id: str, pack_ids: Iterable[str]) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        chosen = list(dict.fromkeys(pack_ids))
        packs = self.ctx.frameworks.usable(chosen)
        matter.framework_ids = [p.pack_id for p in packs]
        self.ctx.store.put_matter(matter)
        self.ctx.log(
            "matter_updated",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="matter.manage",
            subject_id=matter.matter_id,
            outcome="frameworks_set",
            object_type="matter",
            payload={"frameworks": {p.pack_id: p.fingerprint for p in packs}},
        )
        return matter

    def context_for(self, matter_id: str, *, actor_id: str) -> str:
        """Exactly what the model is told about the law and standards on this matter."""
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        packs = [p for p in (self.ctx.frameworks.get(i) for i in matter.framework_ids) if p]
        return compile_context(packs, matter.profile.value)

    def _log(
        self, actor_id: str, pack: FrameworkPack, event: str, outcome: str, **extra: Any
    ) -> None:
        self.ctx.log(
            event,
            actor_id=actor_id,
            matter_id="-",
            action="framework.manage",
            subject_id=pack.pack_id,
            outcome=outcome,
            object_type="framework",
            output_hash=pack.sha256,
            payload={
                "version": pack.version,
                "origin": pack.origin,
                **{k: v for k, v in extra.items() if v},
            },
        )


def default_frameworks(
    ctx: AppContext, matter: Matter, chosen: Sequence[str] | None, *, recommended: bool
) -> list[str]:
    """The packages a new matter starts with: the recommended ones for its kind and legal system,
    plus any chosen, or only those chosen."""
    picks = list(chosen or [])
    if recommended:
        codes = ctx.jurisdictions.jurisdiction_codes(matter)
        picks = ctx.frameworks.recommended(matter.profile.value, codes) + picks
    return [p.pack_id for p in ctx.frameworks.usable(dict.fromkeys(picks))]
