"""A run stopped by a person stops promptly, not only between steps.

The step runner sets, for the step it is running, a check of whether a person has stopped the
run. Anything that can take a while (a model call, each document read, each issue researched)
calls ``check_stop()``, which ends the step at once when the run was stopped. Outside a run it
does nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from eli_legal.domain.errors import RunStopped

_probe: ContextVar[Callable[[], bool] | None] = ContextVar("eli_legal_stop_probe", default=None)


@contextmanager
def watching(stopped: Callable[[], bool]) -> Iterator[None]:
    token = _probe.set(stopped)
    try:
        yield
    finally:
        _probe.reset(token)


def check_stop() -> None:
    probe = _probe.get()
    if probe is not None and probe():
        raise RunStopped("a person stopped the run")
