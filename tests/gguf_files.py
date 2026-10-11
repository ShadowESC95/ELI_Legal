"""Model files for tests: the size and header of a real model, and no disk used.

Nothing reads the weights of these files; the header is what a real model of that shape carries.
Linux and macOS leave a hole when a file's length is set past what was written. Windows writes
out every zero unless the file is marked sparse first, and a few model-sized files fill a disk.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any, BinaryIO

MIB = 1024 * 1024


def _mark_sparse(f: BinaryIO) -> None:
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    handle = wintypes.HANDLE(msvcrt.get_osfhandle(f.fileno()))  # type: ignore[attr-defined]
    returned = wintypes.DWORD()
    ctypes.windll.kernel32.DeviceIoControl(  # type: ignore[attr-defined]
        handle, 0x000900C4, None, 0, None, 0, ctypes.byref(returned), None
    )


def sparse_file(path: Path, size: int, head: bytes = b"") -> Path:
    """``path`` is ``size`` bytes long, starts with ``head``, and the rest takes no space."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(head)
        _mark_sparse(f)
        if size > len(head):
            f.seek(size - 1)
            f.write(b"\0")
    return path


def gguf_file(path: Path, arch: str, meta: dict[str, Any], tensors: dict[str, int]) -> Path:
    """A GGUF file with this metadata and tensors of these byte sizes."""

    def s(text: str) -> bytes:
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    def value(v: Any) -> bytes:
        if isinstance(v, int):
            return struct.pack("<I", 4) + struct.pack("<I", v)
        if isinstance(v, str):
            return struct.pack("<I", 8) + s(v)
        if isinstance(v, list):
            return (
                struct.pack("<II", 9, 4)
                + struct.pack("<Q", len(v))
                + b"".join(struct.pack("<I", x) for x in v)
            )
        raise TypeError(v)

    kv: dict[str, Any] = {"general.architecture": arch, "general.alignment": 32}
    kv.update({f"{arch}.{k}": v for k, v in meta.items()})
    head = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(tensors), len(kv))
    head += b"".join(s(k) + value(v) for k, v in kv.items())
    offset = 0
    for name, size in tensors.items():
        head += s(name) + struct.pack("<I", 1) + struct.pack("<Q", size) + struct.pack("<I", 0)
        head += struct.pack("<Q", offset)
        offset += size + (-size % 32)
    head += b"\0" * (-len(head) % 32)
    return sparse_file(path, len(head) + offset, head)


def dense_model(
    path: Path,
    *,
    blocks: int = 28,
    block_mib: int = 130,
    embedding_mib: int = 300,
    trained_context: int = 32768,
    tied: bool = False,
) -> Path:
    """A model in the shape of a 7-billion-parameter one at four bits: grouped-query attention,
    56 KiB of KV cache a token."""
    tensors = {"token_embd.weight": embedding_mib * MIB}
    for i in range(blocks):
        tensors[f"blk.{i}.attn_q.weight"] = block_mib * MIB // 2
        tensors[f"blk.{i}.ffn_up.weight"] = block_mib * MIB // 2
    if not tied:
        tensors["output.weight"] = embedding_mib * MIB
    meta = {
        "block_count": blocks,
        "context_length": trained_context,
        "embedding_length": 3584,
        "attention.head_count": 28,
        "attention.head_count_kv": 4,
    }
    return gguf_file(path, "qwen2", meta, tensors)


def experts_model(path: Path, *, blocks: int = 40, expert_mib: int = 450) -> Path:
    """A mixture-of-experts model: the experts are most of the file, attention on one layer
    in four."""
    tensors = {"token_embd.weight": 270 * MIB, "output.weight": 400 * MIB}
    for i in range(blocks):
        tensors[f"blk.{i}.attn_q.weight"] = 30 * MIB
        tensors[f"blk.{i}.ffn_gate_exps.weight"] = expert_mib * MIB
    meta = {
        "block_count": blocks,
        "context_length": 262144,
        "embedding_length": 2048,
        "attention.head_count": 16,
        "attention.head_count_kv": 2,
        "attention.key_length": 256,
        "attention.value_length": 256,
        "full_attention_interval": 4,
    }
    return gguf_file(path, "qwen35moe", meta, tensors)
