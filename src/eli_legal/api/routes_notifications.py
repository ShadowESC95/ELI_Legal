"""Work waiting for the signed-in person: holds to clear, a report to review, a suspension.

Each person sees only their own. A browser polls these while it is open, so when a run stops
for a person, everyone signed in who can act on it is told within seconds. Nothing is sent
outside ELI Legal.
"""

# No "from __future__ import annotations": see routes_auth.
from typing import Annotated, Any

from fastapi import Depends, FastAPI

from eli_legal.application.services import Services

from .auth import Access
from .config import ServerConfig


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]

    @app.get("/v1/notifications")
    def notifications(actor: Actor) -> Any:
        """Your notifications that still need you, unseen first, newest first."""
        rows = sv.notifications.inbox(actor)
        return {"unread": sum(1 for r in rows if r["status"] == "open"), "items": rows}

    @app.post("/v1/matters/{matter_id}/notifications/{notification_id}/read")
    def read(matter_id: str, notification_id: str, actor: Actor) -> Any:
        """Mark one of your notifications as seen. It stays until the work is done."""
        return sv.notifications.mark_read(matter_id, notification_id, actor_id=actor)

    @app.post("/v1/notifications/read")
    def read_all(actor: Actor) -> Any:
        """Mark all your notifications as seen."""
        return {"marked": sv.notifications.mark_all_read(actor)}
