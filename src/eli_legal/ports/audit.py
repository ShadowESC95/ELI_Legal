from __future__ import annotations
from typing import Protocol
from eli_legal.domain.models import AuditEvent

class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> int: ...
    def verify_chain(self) -> bool: ...
