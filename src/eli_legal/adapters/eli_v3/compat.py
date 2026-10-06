from __future__ import annotations

import importlib
from typing import Any


class EliV3Unavailable(RuntimeError):
    pass


# The complete list of host modules ELI Legal may import. A test asserts nothing else is used.
ALLOWED_HOST_MODULES = frozenset(
    {
        "eli.cognition.gguf_inference",
        "eli.core.netguard",
        "eli.tools.registry.capability_registry",
    }
)


def import_attr(module_name: str, attr_name: str) -> Any:
    if module_name not in ALLOWED_HOST_MODULES:
        raise EliV3Unavailable(f"ELI Legal may not import host module {module_name!r}")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - depends on an optional ELI installation
        raise EliV3Unavailable(
            f"ELI v3 module {module_name!r} is unavailable; this adapter only works inside ELI v3"
        ) from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:  # pragma: no cover
        raise EliV3Unavailable(f"host attribute {module_name}.{attr_name} is unavailable") from exc
