from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class WorkflowPort(Protocol):
    def run(
        self, *, workflow_id: str, context: dict[str, Any], handlers: dict[str, Callable[..., Any]]
    ) -> dict[str, Any]: ...
