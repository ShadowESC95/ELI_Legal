from __future__ import annotations

from contextlib import AbstractContextManager

from eli_legal.adapters.eli_v2.compat import import_attr


class EliV2NetworkAdapter:
    """Reuse ELI v2's fail-closed socket guard and scoped allow_network window."""

    def allow(self, *, reason: str) -> AbstractContextManager[None]:
        allow_network = import_attr("eli.core.netguard", "allow_network")
        return allow_network(reason)
