"""What llama.cpp said while it loaded a model: kept, read, and turned into a reason.

llama.cpp writes through its own C log callback, so with ``verbose=False`` the one line that
explains a failed load is thrown away, and what reaches Python is a destructor error that says
nothing. Here the log is collected for the length of a load. From it come the reason for a
failure, whether trying again smaller could ever help, and what the load actually did (layers
placed on the card, the KV cache's real size).

As in ELI (``eli.cognition.model_load_diagnostics``). Nothing here knows a model by name.
"""

from __future__ import annotations

import ctypes
import logging
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

_sink_lock = threading.Lock()
_buffer: list[str] = []
# Created once and kept for ever: a ctypes callback handed to C must not be collected while C
# can still call it. Only the buffer changes between loads.
_capture_cb: Any = None
_null_cb: Any = None
_hardened = False

_OFFLOADED = re.compile(r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers", re.I)
_OUT_OF_MEMORY = ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate", "oom")
_NOT_A_MEMORY_PROBLEM = (
    "missing tensor",
    "unknown model architecture",
    "unsupported model architecture",
    "invalid magic",
    "not a valid gguf",
    "wrong magic",
    "unexpected eof",
    "no such file",
    "failed to open",
)


def harden_destructor(module: Any) -> None:
    """Stop a failed load from raising "'LlamaModel' has no attribute 'sampler'" in place of
    its real reason: the destructor reads an attribute a failed constructor never set."""
    global _hardened
    if _hardened:
        return
    internals = getattr(module, "_internals", None)
    for name in ("LlamaModel", "LlamaContext", "LlamaSampler"):
        cls = getattr(internals, name, None)
        if isinstance(cls, type) and not hasattr(cls, "sampler"):
            cls.sampler = None  # type: ignore[attr-defined]
    _hardened = True


@contextmanager
def capture(module: Any) -> Iterator[list[str]]:
    """llama.cpp's log lines for the length of the block, whatever ``verbose`` is."""
    global _capture_cb, _null_cb
    lines: list[str] = []
    proto = getattr(module, "llama_log_callback", None)
    setter = getattr(module, "llama_log_set", None)
    installed = False
    # Only the real library: handing a ctypes callback to a stand-in for it would crash.
    if isinstance(proto, type) and issubclass(proto, ctypes._CFuncPtr) and callable(setter):  # type: ignore[attr-defined]
        with _sink_lock:
            if _capture_cb is None:

                def _collect(level: int, text: bytes, user_data: Any) -> None:
                    # Inside llama.cpp's callback: no logging from here, it could re-enter.
                    try:
                        _buffer.append(text.decode("utf-8", "replace"))
                    except Exception:  # pragma: no cover - never raise into C
                        pass

                _capture_cb = proto(_collect)
                _null_cb = proto(lambda *_a: None)
            _buffer.clear()
            setter(_capture_cb, ctypes.c_void_p(0))
            installed = True
    try:
        yield lines
    finally:
        if installed and callable(setter):
            with _sink_lock:
                setter(_null_cb, ctypes.c_void_p(0))
                lines.extend(_buffer)
                _buffer.clear()


def _text(lines: list[str]) -> str:
    return "".join(lines)


def retryable(lines: list[str]) -> bool:
    """Whether a smaller request could load where this one failed. Only a shortage of memory
    changes with the settings; a file this llama.cpp cannot read fails the same way every time.
    An unrecognised failure is treated as one worth one more try."""
    low = _text(lines).lower()
    return not any(k in low for k in _NOT_A_MEMORY_PROBLEM)


def out_of_memory(lines: list[str]) -> bool:
    low = _text(lines).lower()
    return any(k in low for k in _OUT_OF_MEMORY)


def layers_on_card(lines: list[str]) -> tuple[int, int] | None:
    """(placed, of) from llama.cpp's own report of the load, counting the output layer as it
    does; None when it did not say (a build without graphics support says nothing)."""
    found = _OFFLOADED.findall(_text(lines))
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def explain(exc: BaseException, lines: list[str], name: str, *, on_card: bool) -> str:
    """One sentence: what went wrong loading this model, and what to do about it. By what
    llama.cpp reported, so it holds for a model released after this was written."""
    text = _text(lines)
    low = text.lower()
    said = next(
        (
            line.strip()
            for line in text.splitlines()
            if "error loading model" in line.lower() or "error:" in line.lower()
        ),
        "",
    )
    tail = f" llama.cpp said: {said}" if said else ""
    if "missing tensor" in low:
        return (
            f"{name} could not be loaded: this llama.cpp knows the model's architecture but "
            f"expects different tensors, so the file is newer than it.{tail}"
        )
    if "unknown model architecture" in low or "unsupported model architecture" in low:
        return (
            f"{name} could not be loaded: this llama.cpp does not support its architecture.{tail}"
        )
    if any(
        k in low for k in ("invalid magic", "not a valid gguf", "wrong magic", "unexpected eof")
    ):
        return (
            f"{name} is not a complete GGUF file: the download is cut short or damaged. "
            f"Fetch it again and compare its size with the source.{tail}"
        )
    if out_of_memory(lines):
        where = "graphics memory" if on_card else "memory"
        return f"{name} ran out of {where} while loading.{tail}"
    return f"{name} could not be loaded ({type(exc).__name__}: {exc}).{tail}"
