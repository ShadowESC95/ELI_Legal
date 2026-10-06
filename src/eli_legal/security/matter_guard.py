from __future__ import annotations
from eli_legal.domain.errors import MatterAccessDenied
from eli_legal.domain.models import Matter


def require_matter_access(matter: Matter, user_id: str) -> None:
    if user_id == matter.owner_user_id:
        return
    if user_id not in matter.authorised_user_ids:
        raise MatterAccessDenied(f"user {user_id!r} is not authorised for matter {matter.matter_id}")
