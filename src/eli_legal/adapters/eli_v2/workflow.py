from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eli_legal.adapters.eli_v2.compat import import_attr


class EliV2WorkflowAdapter:
    """Use ELI v2's generic DAG scheduler, not its personal-assistant agent bus."""

    def __init__(self, *, max_workers: int = 1, fail_fast: bool = True) -> None:
        self.max_workers = max_workers
        self.fail_fast = fail_fast

    def run(
        self,
        *,
        workflow_id: str,
        context: dict[str, Any],
        handlers: dict[str, Callable[..., Any]],
    ) -> dict[str, Any]:
        task_cls = import_attr("eli.core.dag", "Task")
        orchestrator_cls = import_attr("eli.core.dag", "Orchestrator")
        dependencies = context.get("dependencies", {})

        tasks = []
        for step_id, handler in handlers.items():
            deps = set(dependencies.get(step_id, set()))

            def _run(node_context: Any, _handler: Callable[..., Any] = handler) -> Any:
                return _handler(node_context)

            tasks.append(task_cls(id=step_id, run=_run, depends_on=deps, critical=True))

        report = orchestrator_cls(
            max_workers=self.max_workers,
            fail_fast=self.fail_fast,
        ).run(tasks, context={**context, "workflow_id": workflow_id})
        return report.to_dict()
