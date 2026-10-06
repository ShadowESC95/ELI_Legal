from __future__ import annotations
from eli_legal.domain.models import Matter


class MatterManager:
    def __init__(self) -> None:
        self._matters: dict[str, Matter] = {}

    def create(self, matter: Matter) -> Matter:
        matter.authorised_user_ids.add(matter.owner_user_id)
        self._matters[matter.matter_id] = matter
        return matter

    def get(self, matter_id: str) -> Matter | None:
        return self._matters.get(matter_id)
