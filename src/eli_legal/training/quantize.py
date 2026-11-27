"""Making a trained model's GGUF smaller, with the quantiser inside ELI Legal's own llama.cpp.

llama.cpp's converter writes 16-bit weights (or 8-bit, q8_0). The smaller forms that suit a
graphics card of 8 GB, Q4_K_M and Q5_K_M (ELI v2 shipped Q4_K_M), are made from the 16-bit
file by llama.cpp's quantiser, which llama-cpp-python carries: nothing more is installed.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

KINDS = {
    "q4_k_m": "LLAMA_FTYPE_MOSTLY_Q4_K_M",
    "q5_k_m": "LLAMA_FTYPE_MOSTLY_Q5_K_M",
    "q8_0": "LLAMA_FTYPE_MOSTLY_Q8_0",
}


def quantize(source: Path, target: Path, kind: str, *, threads: int = 0) -> None:
    """Write ``target`` as ``source`` quantised to ``kind``. Raises RuntimeError on failure."""
    if kind not in KINDS:
        raise ValueError(f"quantize to one of {', '.join(KINDS)}")
    from llama_cpp import llama_cpp as lib

    params = lib.llama_model_quantize_default_params()
    params.ftype = getattr(lib, KINDS[kind])
    params.nthread = int(threads)
    code = lib.llama_model_quantize(
        str(source).encode(), str(target).encode(), ctypes.byref(params)
    )
    if code != 0 or not Path(target).is_file():
        raise RuntimeError(f"llama.cpp could not quantise the model to {kind} (code {code})")
