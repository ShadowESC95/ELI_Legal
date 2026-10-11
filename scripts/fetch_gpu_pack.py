#!/usr/bin/env python3
"""Fetch the graphics pack an installer ships, at build time, and check it is the file expected.

An installed ELI Legal makes no connection for a graphics pack: the one for any maker's card
(Vulkan) is put inside the installer here, when the installer is built. The packs are the ones
published with ELI; ``packaging/gpu_packs.json`` names the llama.cpp version they are built at,
which the llama.cpp built into the installer must equal, and the checksum of each file.

    fetch_gpu_pack.py --version     print that llama.cpp for Python version (for the build's pin)
    fetch_gpu_pack.py               fetch this platform's pack into packaging/gpu-packs
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = json.loads((ROOT / "packaging" / "gpu_packs.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        print(PACKS["llama_cpp_python"])
        return 0
    key = f"{platform.system().lower()}-{platform.machine().lower()}"
    pack = PACKS["shipped"].get(key)
    if pack is None:
        print(f"no graphics pack is shipped for {key} (macOS uses the built-in Metal support)")
        return 0
    dest = ROOT / "packaging" / "gpu-packs" / pack["file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest.is_file() and _sha256(dest) == pack["sha256"]):
        url = f"{PACKS['source']}/{pack['file']}"
        print(f"fetching {url}")
        urllib.request.urlretrieve(url, dest)  # noqa: S310 - a fixed https address
    found = _sha256(dest)
    if found != pack["sha256"]:
        dest.unlink()
        print(f"{pack['file']}: checksum {found} is not the one expected", file=sys.stderr)
        return 1
    print(f"{dest.relative_to(ROOT)}: checksum as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
