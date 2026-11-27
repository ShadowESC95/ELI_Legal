"""The model calls a run made, kept with the run so its approved work can teach a model later.

Each call is one line in ``model_calls.jsonl`` in the run's folder: the task, the prompt
version, the system message and prompt sent, the answer and what was read from it, the model.
The file is sealed with the matter's key like every other case file, and goes when the matter's
content is erased. Recording never stops a run: a call that cannot be written is noted and the
run goes on.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from eli_legal.domain.models import utcnow

log = logging.getLogger(__name__)

FILE = "model_calls.jsonl"


def calls_path(ctx: Any, matter_id: str, run_id: str) -> Path:
    return Path(ctx.run_dir(matter_id, run_id)) / FILE


class CallRecorder:
    """Appends each model call of one step of one run to the run's sealed record."""

    def __init__(self, ctx: Any, matter_id: str, run_id: str, step: str) -> None:
        self.ctx = ctx
        self.matter_id = matter_id
        self.run_id = run_id
        self.step = step

    def __call__(self, call: dict[str, Any]) -> None:
        line = json.dumps(
            {**call, "step": self.step, "at": utcnow().isoformat()},
            ensure_ascii=False,
            sort_keys=True,
        )
        path = calls_path(self.ctx, self.matter_id, self.run_id)
        try:
            files = self.ctx.files
            earlier = files.read(self.matter_id, path) if path.is_file() else b""
            files.write(self.matter_id, path, earlier + line.encode("utf-8") + b"\n")
        except Exception:  # the analysis matters more than its record for training
            log.warning("could not record a model call of run %s", self.run_id, exc_info=True)


def read_calls(ctx: Any, matter_id: str, run_id: str) -> list[dict[str, Any]]:
    """The model calls a run made, in order ([] where none were recorded)."""
    path = calls_path(ctx, matter_id, run_id)
    if not path.is_file():
        return []
    out = []
    for raw in ctx.files.read(matter_id, path).decode("utf-8").splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
