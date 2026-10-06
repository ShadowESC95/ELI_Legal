from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.models import Matter
from eli_legal.security.matter_guard import require_matter_access
from eli_legal.security.rbac import RoleBindings


@dataclass(slots=True)
class MatterAuthorizer:
    """Require both role permission and explicit access to the specific matter."""

    bindings: RoleBindings

    def require_global(self, user_id: str, action: str) -> None:
        self.bindings.require(user_id, action)

    def require_matter(self, matter: Matter, user_id: str, action: str) -> None:
        self.bindings.require(user_id, action)
        require_matter_access(matter, user_id)
