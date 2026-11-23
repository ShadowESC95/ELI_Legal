"""The parties' own place on a court's, tribunal's or neutral's matter.

Everyone in a case signs in with their own account: the tribunal's people (judge, panel,
registrar), and each party's people (prosecution, defence, a claimant's or respondent's
solicitors and barristers, or a party acting for themselves). A party's people are on the matter
in the matter role ``party``, always acting for one named party, and may do three things there:

- read what is served on all parties, and what their own side filed in confidence;
- file papers for their own side (never for another party);
- answer a hold on one of their own filings: file a readable copy, ask to withdraw it, or
  explain. The answer closes nothing; the tribunal reads it and decides the hold.

They never see the tribunal's analysis: no findings, checks, runs, chat, report or record of
actions. Those stay behind ``matter.read`` and ``document.read``, which the party role does not
hold, so every other page refuses them by the same rules that refuse anyone else.

When a hold on a party's filing waits for an answer, that party's people are told on their own
screen (see ``NotificationService``). When they answer, the tribunal's people who can decide the
hold are told. Each filing and each answer is signed into the audit trail under the name of the
person who made it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.application.ingestion_service import IngestionService
from eli_legal.domain import plain
from eli_legal.domain.enums import AccessScope, DocumentType, HoldScope, HoldStatus
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import Document, Hold, HoldAnswer, Matter, Party, Run
from eli_legal.domain.profiles import profile_spec
from eli_legal.security import access, authn

ANSWERS: dict[str, str] = {
    "refiled": "filed a readable copy",
    "withdraw": "asks to withdraw it",
    "explain": "explains",
}

# What a party may do about each kind of hold on its filing, in plain words.
_WHAT_YOU_CAN_DO: dict[str, str] = {
    "coverage_gap": "File a readable copy of it, or explain why it cannot be read.",
    "pages_not_read": "File a copy with readable text on those pages, or explain.",
    "image_text_unread": "File a copy with the images' text readable, or explain.",
    "ocr_low_confidence": "File a clearer copy of it, or explain.",
    "prompt_injection_detected": (
        "Explain where the flagged text came from, or ask to withdraw it and file a clean copy."
    ),
}


@dataclass(slots=True)
class PartyService:
    ctx: AppContext
    ingestion: IngestionService

    # ── which matters, and as whom ───────────────────────────────────────────
    def cases(self, actor_id: str) -> list[dict[str, Any]]:
        """The matters on which this person acts for a party, with what waits for them."""
        authn.require(actor_id)
        authz = self.ctx.authorizer()
        out = []
        for matter in self.ctx.store.list_matters():
            if not access.is_party_member(matter, actor_id):
                continue
            if not authz.can_matter(matter, actor_id, "filing.read"):
                continue
            party = self._party_of(matter, actor_id)
            if party is None:
                continue
            out.append(
                {
                    "matter_id": matter.matter_id,
                    "name": matter.name,
                    "status": matter.status.value,
                    "profile": matter.profile.value,
                    "for": profile_spec(matter.profile).label,
                    "forum": matter.forum,
                    "party_id": party.party_id,
                    "party_name": party.name,
                    "waiting": sum(1 for h in self._holds_on(matter, party) if not h.answers),
                }
            )
        return out

    def case(self, matter_id: str, actor_id: str) -> dict[str, Any]:
        """One matter as a party's representative sees it: the parties, the papers they may
        read, and the holds on their own side's filings."""
        matter, party = self._as_party(matter_id, actor_id, "filing.read")
        seen = self.ctx.authorizer().visibility(matter, actor_id)
        names = {p.party_id: p.name for p in matter.parties}
        papers = []
        for d in self.ctx.store.list(Document, matter.matter_id):
            if not seen.document_visible(d):
                continue  # another party's confidential papers are not even listed
            papers.append(
                {
                    "document_id": d.document_id,
                    "filename": d.filename,
                    "title": d.title,
                    "doc_type": d.doc_type.value,
                    "filed_by": names.get(d.party_id or "", "the tribunal"),
                    "yours": d.party_id == party.party_id,
                    "served": d.access_scope is AccessScope.ALL_PARTIES,
                    "status": d.status.value,
                    "unread_pages": list(d.unread_pages),
                    "passages": d.segment_count,
                }
            )
        return {
            "matter_id": matter.matter_id,
            "name": matter.name,
            "status": matter.status.value,
            "for": profile_spec(matter.profile).label,
            "forum": matter.forum,
            "jurisdiction": matter.jurisdiction,
            "parties": [{"name": p.name, "role": p.role} for p in matter.parties],
            "you_act_for": party.name,
            "papers": papers,
            "holds": [self._hold_row(matter, h) for h in self._holds_on(matter, party)],
        }

    # ── filing ───────────────────────────────────────────────────────────────
    def file(
        self,
        matter_id: str,
        *,
        actor_id: str,
        filename: str,
        raw: bytes,
        doc_type: DocumentType | None = None,
        title: str = "",
        confidential: bool = False,
        document_date: date | None = None,
    ) -> Document:
        """File a paper for the party this person acts for: served on all parties, or (when
        ``confidential``) for the tribunal alone, never shown to another party."""
        matter, party = self._as_party(matter_id, actor_id, "filing.add")
        if not raw:
            raise InvalidInput("the file is empty")
        scope = AccessScope.PARTY_CONFIDENTIAL if confidential else AccessScope.ALL_PARTIES
        before = {d.document_id for d in self.ctx.store.list(Document, matter.matter_id)}
        document = self.ingestion.register_checked(
            matter=matter,
            actor_id=actor_id,
            filename=filename,
            raw=raw,
            doc_type=doc_type,
            party_id=party.party_id,
            access_scope=scope,
            custodian=f"filed by {party.name}",
            title=title,
            document_date=document_date,
        )
        if document.document_id in before:
            # The same bytes are one piece of evidence however often filed. Who filed them
            # first is not said: it may be another party's confidential paper.
            raise InvalidState("this exact file is already on the case")
        self.ctx.log(
            "document_filed_by_party",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="filing.add",
            subject_id=document.document_id,
            outcome="filed",
            object_type="document",
            input_hash=document.sha256,
            payload={"party": party.party_id, "access_scope": scope.value},
        )
        return self.ingestion.process(document, actor_id=actor_id, type_given=doc_type is not None)

    def passages(self, matter_id: str, document_id: str, actor_id: str) -> list[dict[str, Any]]:
        """A paper's text, passage by passage, if this person may read it."""
        matter, _party = self._as_party(matter_id, actor_id, "filing.read")
        document = self.ctx.store.get(Document, matter.matter_id, document_id)
        if document is None:
            self._foreign(Document, matter, document_id, actor_id, "filing.read")
        seen = self.ctx.authorizer().visibility(matter, actor_id)
        if document is None or not seen.document_visible(document):
            raise NotFound("no such paper on this case")
        return [
            {"ordinal": c.ordinal, "locator": c.locator, "text": seen.chunk(c, document).text}
            for c in self.ctx.store.chunks_for(matter.matter_id, document_id)
        ]

    # ── answering a hold on one's own filing ─────────────────────────────────
    def answer(
        self,
        matter_id: str,
        hold_id: str,
        *,
        actor_id: str,
        kind: str,
        reasons: str,
        replacement_document_id: str | None = None,
    ) -> Hold:
        """Answer a hold on one of this party's filings. The tribunal decides the hold."""
        authn.require_step_up(actor_id, "answer a hold")
        matter, party = self._as_party(matter_id, actor_id, "hold.respond")
        hold = self.ctx.store.get(Hold, matter.matter_id, hold_id)
        if hold is None:
            self._foreign(Hold, matter, hold_id, actor_id, "hold.respond")
        document = (
            self.ctx.store.get(Document, matter.matter_id, hold.subject_id)
            if hold is not None and hold.scope is HoldScope.DOCUMENT
            else None
        )
        if hold is None or document is None or document.party_id != party.party_id:
            raise NotFound("no such hold on your side's filings")  # another's is not revealed
        if hold.status is not HoldStatus.OPEN:
            raise InvalidState("the tribunal has already decided this hold")
        if kind not in ANSWERS:
            raise InvalidInput("answer with one of: " + ", ".join(ANSWERS))
        if len(reasons.strip()) < 10:
            raise InvalidInput("say what you have done, or why, in a sentence or two")
        if kind == "refiled":
            copy = (
                self.ctx.store.get(Document, matter.matter_id, replacement_document_id)
                if replacement_document_id
                else None
            )
            if copy is None and replacement_document_id:
                self._foreign(Document, matter, replacement_document_id, actor_id, "hold.respond")
            if copy is None or copy.party_id != party.party_id:
                raise InvalidInput("file the readable copy first, then name it in your answer")
            if copy.document_id == document.document_id:
                raise InvalidInput("the copy must be a different file from the one that is held")
        elif replacement_document_id:
            raise InvalidInput("only an answer that files a readable copy names a document")
        hold.answers.append(
            HoldAnswer(
                by=actor_id,
                party_id=party.party_id,
                kind=kind,
                reasons=reasons.strip()[:2000],
                replacement_document_id=replacement_document_id if kind == "refiled" else None,
            )
        )
        self.ctx.store.put(hold)
        self.ctx.log(
            "hold_answered",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=hold.run_id,
            action="hold.respond",
            subject_id=hold.hold_id,
            outcome=kind,
            object_type=f"hold:{hold.scope.value}",
            payload={
                "party": party.party_id,
                "document": document.document_id,
                "replacement": replacement_document_id if kind == "refiled" else None,
            },
        )
        return hold

    # ── helpers ──────────────────────────────────────────────────────────────
    def _as_party(self, matter_id: str, actor_id: str, action: str) -> tuple[Matter, Party]:
        matter = self.ctx.matter_for(matter_id, actor_id, action)
        if not access.is_party_member(matter, actor_id):
            raise PolicyDenied(
                "these pages are for a party's representatives; on this matter you work for "
                "the tribunal, so use its own pages"
            )
        party = self._party_of(matter, actor_id)
        if party is None:
            raise PolicyDenied("you act for no party on this matter; ask its lead to say which")
        return matter, party

    def _foreign(
        self, cls: type, matter: Matter, record_id: str, actor_id: str, action: str
    ) -> None:
        """A record id from another matter was presented: record the attempt (C-02) and reveal
        nothing about it. The caller then answers "not found", as for an id that exists nowhere."""
        owner = self.ctx.store.owner_matter(cls, record_id)
        if owner is not None and owner != matter.matter_id:
            self.ctx.authorizer().record_cross_matter_attempt(
                user_id=actor_id,
                matter_id=matter.matter_id,
                action=action,
                object_type=cls.__name__.lower(),
                object_id=record_id,
            )

    @staticmethod
    def _party_of(matter: Matter, actor_id: str) -> Party | None:
        party_id = matter.member_parties.get(actor_id)
        return next((p for p in matter.parties if p.party_id == party_id), None)

    def _holds_on(self, matter: Matter, party: Party) -> list[Hold]:
        """Open holds on this party's filings, in the matter's latest run."""
        runs = self.ctx.store.list(Run, matter.matter_id)
        if not runs:
            return []
        latest = max(runs, key=lambda r: r.created_at)
        docs = {
            d.document_id
            for d in self.ctx.store.list(Document, matter.matter_id)
            if d.party_id == party.party_id
        }
        return [
            h
            for h in self.ctx.holds.open_holds(matter.matter_id, latest.run_id)
            if h.scope is HoldScope.DOCUMENT and h.subject_id in docs
        ]

    def _hold_row(self, matter: Matter, hold: Hold) -> dict[str, Any]:
        document = self.ctx.store.get(Document, matter.matter_id, hold.subject_id)
        return {
            "hold_id": hold.hold_id,
            "document_id": hold.subject_id,
            "document": (document.title or document.filename) if document else "",
            "reason": hold.reason_code,
            "why": plain.hold_reason(hold.reason_code),
            "detail": hold.detail,
            "what_you_can_do": _WHAT_YOU_CAN_DO.get(
                hold.reason_code, "File a corrected copy, ask to withdraw it, or explain."
            ),
            "answers": [answer_row(a) for a in hold.answers],
            "raised_at": hold.created_at.isoformat(),
        }


def answer_row(a: HoldAnswer) -> dict[str, Any]:
    return {
        "by": a.by,
        "party_id": a.party_id,
        "kind": a.kind,
        "what": ANSWERS.get(a.kind, a.kind),
        "reasons": a.reasons,
        "replacement_document_id": a.replacement_document_id,
        "at": a.at.isoformat(),
    }
