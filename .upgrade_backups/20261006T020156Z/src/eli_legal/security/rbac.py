from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RoleBindings:
    user_roles: dict[str, set[str]] = field(default_factory=dict)
    role_actions: dict[str, set[str]] = field(default_factory=dict)

    def can(self, user_id: str, action: str) -> bool:
        return any(
            action in self.role_actions.get(role, set())
            for role in self.user_roles.get(user_id, set())
        )
