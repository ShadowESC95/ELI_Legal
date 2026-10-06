from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class RunContext:
    matter_id: str
    run_id: str
    actor_id: str
    model_versions: dict[str, str] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
