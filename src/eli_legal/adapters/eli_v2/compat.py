from __future__ import annotations

import importlib
from typing import Any


class EliV2Unavailable(RuntimeError):
    pass


def import_attr(module_name: str, attr_name: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - depends on optional ELI installation
        raise EliV2Unavailable(
            f"ELI v2 module {module_name!r} is unavailable; install/add ELI v2 to PYTHONPATH"
        ) from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:  # pragma: no cover
        raise EliV2Unavailable(
            f"ELI v2 attribute {module_name}.{attr_name} is unavailable"
        ) from exc
