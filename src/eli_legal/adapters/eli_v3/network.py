from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from eli_legal.adapters.eli_v3.compat import import_attr
from eli_legal.adapters.local.network import NetworkGuard


class EliV3Network:
    """Both gates must open: ELI Legal's per-host window and the host's own network gate.

    ELI Legal's guard decides *whether* a host is approved. The host's gate is opened only for
    the same scope, so being hosted never widens what the legal runtime may reach, and the
    host's toggles alone (including any full-control mode) never open a legal source.
    """

    def __init__(self, guard: NetworkGuard) -> None:
        self.guard = guard

    @contextmanager
    def allow(self, *, host: str, reason: str) -> Iterator[None]:
        allow_network = import_attr("eli.core.netguard", "allow_network")
        with self.guard.allow(host=host, reason=reason):
            with allow_network(f"ELI Legal approved source {host}: {reason}"):
                yield
