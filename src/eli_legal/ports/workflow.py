from __future__ import annotations
from typing import Protocol, Callable, Any

class WorkflowPort(Protocol):
    def run(self, *, workflow_id: str, context: dict[str, Any], handlers: dict[str, Callable[..., Any]]) -> dict[str, Any]: ...
