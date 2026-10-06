from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import PolicyDenied


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    allowed_actions: frozenset[str]
    prohibited_actions: frozenset[str]
    human_release_required: bool = True
    audit_fail_closed: bool = True
    matter_isolation_required: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> RuntimePolicy:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        runtime = raw.get("runtime", {})
        return cls(
            allowed_actions=frozenset(raw.get("allowed_actions", [])),
            prohibited_actions=frozenset(raw.get("prohibited_actions", [])),
            human_release_required=bool(runtime.get("human_release_required", True)),
            audit_fail_closed=bool(runtime.get("audit_fail_closed", True)),
            matter_isolation_required=bool(runtime.get("matter_isolation_required", True)),
        )

    def require_action(self, action: str) -> None:
        if action in self.prohibited_actions or action not in self.allowed_actions:
            raise PolicyDenied(f"action not authorised by ELI Legal policy: {action}")
