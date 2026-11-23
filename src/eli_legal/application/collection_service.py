"""Reports released to me: where each person a report was released to finds it, reads it, and
takes a copy as PDF, Word or Markdown.

ELI Legal sends nothing out of the building. A released report is staged for collection, and
every person it was released to is told on their own screen. They collect it in the
application or the browser, under the same rules that govern everything else:

- they must be one of the recipients a named person confirmed, still on the matter, still an
  active account; a party's people never collect a tribunal's or neutral's report;
- the report must still be approved and not suspended from reliance (a later problem with an
  authority it relies on stops collection at once);
- the file must still hash to the SHA-256 the reviewer approved; if it does not, nothing is given
  out and the mismatch is recorded.

Every reading and every copy is written to the audit trail (who, when, which format, the report's
hash), and each copy is stamped with who collected it. Copies are made when they are collected;
nothing is kept in a per-person folder or database, so retention, legal holds and erasure reach
the one report and its one record (GDPR Arts. 5 and 17; AI Act Art. 12; ISO/IEC 42001 7.5).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.local import renditions
from eli_legal.application.container import AppContext
from eli_legal.application.reliance_service import barring
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import Matter, utcnow
from eli_legal.domain.profiles import profile_spec
from eli_legal.domain.release import ReleasePackage
from eli_legal.security import access, authn

READY = ("delivery_attempted",)
FORMATS = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
}


@dataclass(slots=True)
class CollectionService:
    ctx: AppContext

    def mine(self, actor_id: str) -> list[dict[str, Any]]:
        """Every report released to this person, newest first, with whether it can be opened."""
        authn.require(actor_id)
        out = []
        for matter in self.ctx.store.list_matters():
            if not self._on_matter(matter, actor_id):
                continue
            for package in self.ctx.store.list(ReleasePackage, matter.matter_id):
                if package.status not in READY or not self._recipient(package, actor_id):
                    continue
                problem = self._problem(matter, package, actor_id)
                out.append(
                    {
                        "matter_id": matter.matter_id,
                        "matter_name": matter.name,
                        "release_id": package.release_id,
                        "run_id": package.run_id,
                        "report_version": package.report_version,
                        "report_hash": package.report_hash,
                        "classification": package.classification,
                        "approved_by": package.approved_by,
                        "released_at": (package.approved_at or package.created_at).isoformat(),
                        "collected": actor_id in package.collected,
                        "can_open": problem is None,
                        "why_not": problem or "",
                        "formats": [f for f in FORMATS if f != "pdf" or renditions.pdf_available()],
                    }
                )
        out.sort(key=lambda r: str(r["released_at"]), reverse=True)
        return out

    def read(self, matter_id: str, release_id: str, actor_id: str) -> str:
        """The approved report's text, to read on screen. Recorded like a copy."""
        _name, data, _type = self.collect(matter_id, release_id, actor_id, "md", reading=True)
        return data.decode("utf-8")

    def collect(
        self, matter_id: str, release_id: str, actor_id: str, fmt: str, *, reading: bool = False
    ) -> tuple[str, bytes, str]:
        """A copy of the report as ``md``, ``docx`` or ``pdf``: (file name, bytes, media type)."""
        authn.require(actor_id)
        if fmt not in FORMATS:
            raise InvalidInput("format: one of " + ", ".join(FORMATS))
        matter = self.ctx.store.get_matter(matter_id)
        package = (
            self.ctx.store.get(ReleasePackage, matter_id, release_id)
            if matter is not None
            else None
        )
        if matter is None or package is None or not self._recipient(package, actor_id):
            self._refused(matter_id, release_id, actor_id, "not_a_recipient")
            raise NotFound("no report was released to you under that release")
        problem = self._problem(matter, package, actor_id)
        if problem:
            self._refused(matter_id, release_id, actor_id, "not_collectable")
            raise PolicyDenied(problem)
        text = self.ctx.files.read(matter_id, package.artifact_ref)
        if hashlib.sha256(text).hexdigest() != package.report_hash:
            self.ctx.log(
                "report_integrity_failure",
                actor_id=actor_id,
                matter_id=matter_id,
                run_id=package.run_id,
                action="report.collect",
                subject_id=release_id,
                outcome="refused",
                object_type="release_package",
                output_hash=package.report_hash,
            )
            raise InvalidState(
                "the report file no longer matches the version that was approved; nothing was "
                "given out, and this has been recorded. Tell the matter's lead."
            )
        user = self.ctx.user(actor_id)
        now = utcnow()
        stamp = [
            f"Collected by {user.display_name} ({actor_id}) on {now:%d %B %Y at %H:%M} UTC",
            f"{matter.name} · release {release_id} · report version {package.report_version}",
            f"Approved by {package.approved_by} · classification {package.classification}",
            f"The authoritative text is the approved report with SHA-256 {package.report_hash}; "
            "this copy is a rendition of it. Do not pass it to anyone the release does not name.",
        ]
        title = f"{matter.name}: report v{package.report_version}"
        if fmt == "md":
            data = text
        elif fmt == "docx":
            data = renditions.to_docx(text.decode("utf-8"), stamp, title=title)
        else:
            try:
                data = renditions.to_pdf(text.decode("utf-8"), stamp, title=title)
            except renditions.RenditionUnavailable as exc:
                raise InvalidState(str(exc)) from exc
        if actor_id not in package.collected:
            package.collected[actor_id] = now.isoformat()
            self.ctx.store.put(package)
        self.ctx.log(
            "report_collected",
            actor_id=actor_id,
            matter_id=matter_id,
            run_id=package.run_id,
            action="report.collect",
            subject_id=release_id,
            outcome="read" if reading else fmt,
            object_type="release_package",
            output_hash=package.report_hash,
            payload={"format": "read" if reading else fmt, "bytes": len(data)},
        )
        media, ext = FORMATS[fmt]
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in matter.name)[:60]
        return f"{safe}_report_v{package.report_version}.{ext}", data, media

    # ── the rules ────────────────────────────────────────────────────────────
    @staticmethod
    def _recipient(package: ReleasePackage, actor_id: str) -> bool:
        return any(r.recipient_id == actor_id for r in package.recipients)

    @staticmethod
    def _on_matter(matter: Matter, actor_id: str) -> bool:
        return actor_id == matter.owner_user_id or actor_id in matter.authorised_user_ids

    def _problem(self, matter: Matter, package: ReleasePackage, actor_id: str) -> str | None:
        """Why this person may not open this report now, or None."""
        user = self.ctx.store.get_user(actor_id)
        if user is None or not user.active:
            return "your account is not active"
        if not self._on_matter(matter, actor_id):
            return "you are no longer on this matter"
        if access.is_party_member(matter, actor_id) and profile_spec(matter.profile).party_roles:
            return "a tribunal's or neutral's report is not released to a party"
        if barring(self.ctx, matter.matter_id, package.run_id):
            return (
                "the report is suspended from reliance: a problem was found with an authority it "
                "relies on, and a named reviewer must deal with it first"
            )
        if not Path(package.artifact_ref).is_file():
            return "the report file is missing; tell the matter's lead"
        return None

    def _refused(self, matter_id: str, release_id: str, actor_id: str, reason: str) -> None:
        self.ctx.log(
            "access_denied",
            actor_id=actor_id,
            matter_id=matter_id if self.ctx.store.get_matter(matter_id) else "-",
            action="report.collect",
            subject_id=release_id,
            outcome="denied",
            object_type="release_package",
            payload={"reason": reason},
        )
