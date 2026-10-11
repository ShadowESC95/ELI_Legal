"""Keep a mixture-of-experts model's expert tensors in system memory, everything else on the card.

Such a model uses a few of its experts per token, and the experts are most of the file. Placing
whole layers on a small card wastes it: the layers that fit carry mostly idle experts. Placing
every layer's attention and shared weights on the card and leaving the experts in memory keeps
what every token needs on the fast side. ELI measured it (an 8 GB card, a 35-billion-parameter
model): 21.8 tokens a second in place of 8.3, and a load thirteen times faster.

llama.cpp for Python does not expose llama.cpp's tensor placement overrides, so the model's
parameters carry one for the length of the model's construction. As in ELI
(``eli.core.moe_offload``).
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

EXPERT_PATTERN = rb"blk\.\d+\.ffn_(up|down|gate|gate_up)_exps"
_patch_lock = threading.Lock()
_keepalive: list[Any] = []


class _Override(ctypes.Structure):
    _fields_ = [("pattern", ctypes.c_char_p), ("buft", ctypes.c_void_p)]


def _base_library(module: Any) -> Path | None:
    name = {"win32": "ggml-base.dll", "darwin": "libggml-base.dylib"}.get(
        sys.platform, "libggml-base.so"
    )
    path = Path(os.path.dirname(str(getattr(module, "__file__", "")))) / "lib" / name
    return path if path.is_file() else None


def _has_override_field(module: Any) -> bool:
    params = getattr(getattr(module, "llama_cpp", None), "llama_model_params", None)
    return any(f[0] == "tensor_buft_overrides" for f in getattr(params, "_fields_", ()))


def available(module: Any) -> bool:
    """Whether this llama.cpp for Python can be told where expert tensors go."""
    return _base_library(module) is not None and _has_override_field(module)


@contextlib.contextmanager
def experts_in_memory(module: Any) -> Iterator[None]:
    """While a model is constructed inside the block, its expert tensors are placed in system
    memory and read straight from the file mapping: no pinned copy and no repacked copy, each
    of which copies gigabytes (ELI measured a load that never finished with the first, and
    1.6 tokens a second with the second, against 18 with neither)."""
    native = module.llama_cpp
    library = _base_library(module)
    if library is None:
        yield
        return
    base = ctypes.CDLL(str(library))
    base.ggml_backend_cpu_buffer_type.restype = ctypes.c_void_p
    table = (_Override * 2)(
        _Override(EXPERT_PATTERN, base.ggml_backend_cpu_buffer_type()), _Override(None, None)
    )
    _keepalive.append(table)
    with _patch_lock:
        original = native.llama_model_default_params

        def patched() -> Any:
            params = original()
            params.tensor_buft_overrides = ctypes.cast(table, ctypes.c_void_p)
            fields = {f[0] for f in getattr(type(params), "_fields_", ())}
            if "no_host" in fields:
                params.no_host = True
            if "use_extra_bufts" in fields:
                params.use_extra_bufts = False
            return params

        native.llama_model_default_params = patched
        try:
            yield
        finally:
            native.llama_model_default_params = original
