from eli_legal.domain.models import Matter
from eli_legal.legal.matter_manager import MatterManager
from eli_legal.security.matter_guard import require_matter_access


class MatterService:
    def __init__(self, manager: MatterManager) -> None:
        self.manager = manager

    def get_for_user(self, matter_id: str, user_id: str) -> Matter:
        matter = self.manager.get(matter_id)
        if matter is None:
            raise KeyError(matter_id)
        require_matter_access(matter, user_id)
        return matter
