"""A party's own pages on a court's, tribunal's or neutral's matter.

Prosecution, defence, a claimant's or respondent's lawyers, or a party acting for themselves,
each signed in with their own account: the papers they may read, filing for their own side, and
answering holds on their own filings. Nothing of the tribunal's analysis is reachable from here,
and every other route refuses them by the same rules that refuse anyone else.
"""

# No "from __future__ import annotations": see routes_auth.
import contextvars
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from eli_legal.application.party_service import answer_row
from eli_legal.application.services import Services
from eli_legal.domain.enums import DocumentType
from eli_legal.domain.models import Document

from . import schemas
from .auth import Access
from .config import ServerConfig
from .routes_matters import _UNSAFE_NAME, document_row


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]

    @app.get("/v1/party/cases")
    def cases(actor: Actor) -> Any:
        """The cases on which you act for a party, with how many of your filings await your answer."""
        return sv.parties.cases(actor)

    @app.get("/v1/party/cases/{matter_id}")
    def case(matter_id: str, actor: Actor) -> Any:
        """One case as your side sees it: the parties, the papers you may read, and holds on your filings."""
        return sv.parties.case(matter_id, actor)

    @app.post("/v1/party/cases/{matter_id}/filings", status_code=201)
    async def file(
        matter_id: str,
        filename: str,
        request: Request,
        actor: Actor,
        doc_type: str | None = None,
        title: str = "",
        confidential: bool = False,
    ) -> dict[str, Any]:
        """File a paper for the party you act for. The body is the file itself. Served on all
        parties unless ``confidential``, when it is for the tribunal alone."""
        name = _UNSAFE_NAME.sub("", filename).strip().lstrip(".")
        if not name or len(name) > 255:
            raise HTTPException(400, "give the file's name, without any folder")
        raw = await request.body()
        if len(raw) > cfg.max_upload_bytes:
            raise HTTPException(413, "the file is too large")
        try:
            given = DocumentType(doc_type) if doc_type else None
        except ValueError as exc:
            raise HTTPException(422, "unknown document type") from exc

        def file_it() -> Document:
            return sv.parties.file(
                matter_id,
                actor_id=actor,
                filename=name,
                raw=raw,
                doc_type=given,
                title=title[:200],
                confidential=confidential,
            )

        return document_row(await run_in_threadpool(contextvars.copy_context().run, file_it))

    @app.get("/v1/party/cases/{matter_id}/filings/{document_id}/passages")
    def passages(matter_id: str, document_id: str, actor: Actor) -> Any:
        """A paper's text, passage by passage, if you may read it."""
        return sv.parties.passages(matter_id, document_id, actor)

    @app.post("/v1/party/cases/{matter_id}/holds/{hold_id}/answer")
    def answer(matter_id: str, hold_id: str, body: schemas.HoldAnswerIn, actor: Actor) -> Any:
        """Answer a hold on one of your side's filings (needs your passphrase again). The tribunal
        reads your answer and decides the hold."""
        hold = sv.parties.answer(
            matter_id,
            hold_id,
            actor_id=actor,
            kind=body.kind,
            reasons=body.reasons,
            replacement_document_id=body.replacement_document_id,
        )
        return {"hold_id": hold.hold_id, "answers": [answer_row(a) for a in hold.answers]}
