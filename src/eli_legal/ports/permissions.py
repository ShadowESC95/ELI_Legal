from __future__ import annotations
from typing import Protocol

class PermissionPort(Protocol):
    def can(self, *, user_id: str, matter_id: str, action: str) -> bool: ...
