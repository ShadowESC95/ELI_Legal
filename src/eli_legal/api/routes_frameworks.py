"""Law and standards packages over HTTP: the library, an organisation's own, and a matter's."""

# No "from __future__ import annotations": see routes_auth.
import contextvars
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from eli_legal.application.services import Services
from eli_legal.legal.frameworks import pack_to_dict

from . import schemas
from .auth import Access
from .config import ServerConfig
from .routes_matters import _UNSAFE_NAME


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]

    @app.get("/v1/frameworks")
    def frameworks(actor: Actor) -> Any:
        """Every law and standards package, with its standing: usable or not, and why."""
        return [s.as_dict() for s in sv.frameworks.list(actor_id=actor)]

    @app.get("/v1/frameworks/recommended")
    def recommended(actor: Actor, profile: str, jurisdiction: str) -> Any:
        """The packages recommended for a kind of matter in a legal system."""
        return sv.frameworks.recommended(profile, jurisdiction, actor_id=actor)

    @app.get("/v1/frameworks/{pack_id}")
    def framework(pack_id: str, actor: Actor) -> Any:
        """One package in full: every requirement and how the system meets it."""
        state = sv.frameworks.get(pack_id, actor_id=actor)
        return {**state.as_dict(), "pack": pack_to_dict(state.pack)}

    @app.get("/v1/frameworks/{pack_id}/export", response_class=PlainTextResponse)
    def export(pack_id: str, actor: Actor) -> PlainTextResponse:
        """The package as JSON, to edit and import again as the organisation's own."""
        return PlainTextResponse(
            sv.frameworks.export(pack_id, actor_id=actor),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{pack_id}.json"'},
        )

    @app.post("/v1/frameworks/upload", status_code=201)
    async def upload(
        request: Request,
        actor: Actor,
        filename: str,
        title: str = "",
        pack_id: str = "",
        issuer: str = "",
        version: str = "1",
    ) -> Any:
        """Import a package: JSON, a CSV requirements register, or a document of the
        organisation's rules. The body is the file. It cannot be used until approved."""
        name = _UNSAFE_NAME.sub("", filename).strip().lstrip(".")
        if not name or len(name) > 255:
            raise HTTPException(400, "give the file's name, without any folder")
        raw = await request.body()

        def import_it() -> Any:
            return sv.frameworks.import_file(
                name, raw, actor_id=actor, title=title[:300], pack_id=pack_id[:64],
                issuer=issuer[:300], version=version[:80] or "1",
            )  # fmt: skip

        # A scanned PDF of rules is read by OCR: off the event loop, as the person importing it.
        state = await run_in_threadpool(contextvars.copy_context().run, import_it)
        return state.as_dict()

    @app.post("/v1/frameworks/{pack_id}/approve")
    def approve(pack_id: str, actor: Actor) -> Any:
        """Approve an organisation's package for use. A decision."""
        return sv.frameworks.approve(pack_id, actor_id=actor).as_dict()

    @app.post("/v1/frameworks/{pack_id}/validate")
    def validate(pack_id: str, body: schemas.ValidationIn, actor: Actor) -> Any:
        """Record that a qualified lawyer checked this exact version against its source. A decision."""
        return sv.frameworks.validate(pack_id, actor_id=actor, lawyer=body.lawyer).as_dict()

    @app.post("/v1/frameworks/{pack_id}/withdraw")
    def withdraw(pack_id: str, actor: Actor) -> Any:
        """Stop a package being applied to any matter from the next run."""
        return sv.frameworks.withdraw(pack_id, actor_id=actor).as_dict()

    @app.post("/v1/frameworks/{pack_id}/reinstate")
    def reinstate(pack_id: str, actor: Actor) -> Any:
        """Allow a withdrawn package again. A decision."""
        return sv.frameworks.reinstate(pack_id, actor_id=actor).as_dict()

    @app.delete("/v1/frameworks/{pack_id}", status_code=204)
    def remove(pack_id: str, actor: Actor) -> None:
        """Delete an organisation's package."""
        sv.frameworks.remove(pack_id, actor_id=actor)

    @app.get("/v1/matters/{matter_id}/frameworks")
    def matter_frameworks(matter_id: str, actor: Actor) -> Any:
        """The packages applied to a matter, and exactly what the model is told about them."""
        return {
            "applied": [s.as_dict() for s in sv.frameworks.for_matter(matter_id, actor_id=actor)],
            "model_is_told": sv.frameworks.context_for(matter_id, actor_id=actor),
        }

    @app.put("/v1/matters/{matter_id}/frameworks", status_code=204)
    def set_matter_frameworks(matter_id: str, body: schemas.IdList, actor: Actor) -> None:
        """Choose the packages that apply to a matter, from its next run."""
        sv.frameworks.set_for_matter(matter_id, actor_id=actor, pack_ids=body.ids)
