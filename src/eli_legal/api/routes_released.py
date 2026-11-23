"""Reports released to me: the list, reading one, and taking a copy as PDF, Word or Markdown.

Each person sees only what was released to them, and only while they are entitled to it; every
reading and every copy is recorded. See ``CollectionService``.
"""

# No "from __future__ import annotations": see routes_auth.
import contextvars
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Response
from starlette.concurrency import run_in_threadpool

from eli_legal.application.services import Services

from .auth import Access
from .config import ServerConfig


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]

    @app.get("/v1/released")
    def released(actor: Actor) -> Any:
        """The reports released to you, newest first, and whether each can be opened now."""
        return sv.released.mine(actor)

    @app.get("/v1/matters/{matter_id}/released/{release_id}")
    async def collect(
        matter_id: str, release_id: str, actor: Actor, format: str = "md"
    ) -> Response:
        """A copy of a report released to you: format md, docx or pdf. Stamped with your name."""
        name, data, media = await run_in_threadpool(
            contextvars.copy_context().run,
            sv.released.collect,
            matter_id,
            release_id,
            actor,
            format,
        )
        return Response(
            content=data,
            media_type=media,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
                "Cache-Control": "no-store",
            },
        )
