from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import PolicyDenied


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    allowed_actions: frozenset[str]
    prohibited_actions: frozenset[str]
    human_release_required: bool = True
    audit_fail_closed: bool = True
    matter_isolation_required: bool = True
    version: str = "0"
    require_validated_jurisdiction_packs: bool = False
    require_reviewer_distinct_from_operator: bool = False
    model_proposition_verification_validated: bool = False
    max_model_chunks: int = 200
    research_passages_per_issue: int = 4
    monitoring: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> RuntimePolicy:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        runtime = raw.get("runtime", {})
        policy = cls(
            allowed_actions=frozenset(raw.get("allowed_actions", [])),
            prohibited_actions=frozenset(raw.get("prohibited_actions", [])),
            human_release_required=bool(runtime.get("human_release_required", True)),
            audit_fail_closed=bool(runtime.get("audit_fail_closed", True)),
            matter_isolation_required=bool(runtime.get("matter_isolation_required", True)),
            version=str(raw.get("policy_version", "0")),
            require_validated_jurisdiction_packs=bool(
                runtime.get("require_validated_jurisdiction_packs", False)
            ),
            require_reviewer_distinct_from_operator=bool(
                runtime.get("require_reviewer_distinct_from_operator", False)
            ),
            model_proposition_verification_validated=bool(
                runtime.get("model_proposition_verification_validated", False)
            ),
            max_model_chunks=int(runtime.get("max_model_chunks", 200)),
            research_passages_per_issue=int(runtime.get("research_passages_per_issue", 4)),
            monitoring=dict(raw.get("monitoring", {})),
        )
        # These three are what make the system governable at all. A policy file may tighten
        # behaviour; it may not switch them off.
        for name in ("human_release_required", "audit_fail_closed", "matter_isolation_required"):
            if not getattr(policy, name):
                raise PolicyDenied(f"policy may not disable {name}")
        overlap = policy.allowed_actions & policy.prohibited_actions
        if overlap:
            raise PolicyDenied(f"actions both allowed and prohibited: {sorted(overlap)}")
        return policy

    def require_action(self, action: str) -> None:
        if action in self.prohibited_actions or action not in self.allowed_actions:
            raise PolicyDenied(f"action not authorised by ELI Legal policy: {action}")

    def permits(self, action: str) -> bool:
        return action in self.allowed_actions and action not in self.prohibited_actions
