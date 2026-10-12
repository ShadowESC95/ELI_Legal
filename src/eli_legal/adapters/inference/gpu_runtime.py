"""A llama.cpp that can use the graphics card.

The llama.cpp inside ELI Legal runs on the processor, so that it starts on every machine.
Graphics support is a separate, complete copy of llama.cpp for Python built for CUDA or Vulkan
(a "pack"): the packs ELI v2 and v3 use. One is switched on, before llama.cpp is first imported,
only after it has been started in a throwaway process and shown it can place layers on this
machine's card. If none passes, the built-in one runs, on the processor, and says so. On macOS
the built-in one already uses the card (Metal) and there is nothing to switch.

Where a pack is looked for, in order: ELI Legal's own runtime folder (put there by an
administrator from a file, or unpacked from the copy shipped inside the installer); ELI v3's;
ELI v2's. Nothing is downloaded: ELI Legal makes no connection for this.

An installed copy carries llama.cpp's libraries on its library path, so there a pack must be the
same version as the built-in one: two versions' libraries in one process share names and crash.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference import hardware
from eli_legal.domain.errors import InvalidInput
from eli_legal.paths import data_roots, runtime_dir

log = logging.getLogger(__name__)

PROBE_OK = "gpu-runtime-ok"
_PROBE_SECONDS = 180
_WHEEL_NAME = re.compile(r"^(cuda|vulkan)-llama_cpp_python-(\d+(?:\.\d+)+)-.+\.whl$")
_VERSION_LINE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


@dataclass(frozen=True, slots=True)
class Pack:
    path: Path
    backend: str  # cuda | vulkan | unknown
    version: str  # of llama.cpp for Python
    origin: str  # ELI Legal | ELI v3 | ELI v2

    def describe(self) -> str:
        return f"llama.cpp {self.version} for {self.backend} ({self.origin}'s)"


@dataclass(slots=True)
class Runtime:
    """The llama.cpp in use in this process."""

    available: bool = False
    version: str = ""
    backend: str = "cpu"  # cpu | cuda | vulkan | metal
    origin: str = "built in"
    path: str = ""
    offload: bool = False  # it can place layers on a card
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if not self.available:
            return "llama.cpp for Python is not installed here"
        where = "built in" if self.origin == "built in" else f"{self.origin}'s"
        what = "graphics card" if self.offload else "processor only"
        return f"llama.cpp {self.version} ({self.backend}, {where}): {what}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "version": self.version,
            "backend": self.backend,
            "origin": self.origin,
            "offload": self.offload,
            "notes": list(self.notes),
        }


_lock = threading.RLock()
_state: tuple[Runtime, Any] | None = None  # (what was decided, the module it describes)
_failed: dict[str, str] = {}  # pack path -> why it did not pass, for this process
_builtin: str | None = None
_not_loaded: list[str] = []  # pack libraries the system refused, with its reason


# ── finding packs ────────────────────────────────────────────────────────────


def own_dir() -> Path:
    return runtime_dir() / "gpu"


def _version_of(pack: Path) -> str:
    try:
        text = (pack / "llama_cpp" / "__init__.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _VERSION_LINE.search(text)
    return m.group(1) if m else ""


def _backend_of(pack: Path) -> str:
    try:
        manifest = json.loads((pack / ".gpu_pack.json").read_text(encoding="utf-8"))
        named = str(manifest.get("backend") or "").lower()
        if named in ("cuda", "vulkan"):
            return named
    except (OSError, ValueError):
        pass
    lib = pack / "llama_cpp" / "lib"
    names = [p.name.lower() for p in lib.iterdir()] if lib.is_dir() else []
    for backend in ("cuda", "vulkan"):
        if any(f"ggml-{backend}" in n for n in names):
            return backend
    return "unknown"


def _pack_at(path: Path, origin: str) -> Pack | None:
    version = _version_of(path)
    return Pack(path.resolve(), _backend_of(path), version, origin) if version else None


def installed() -> list[Pack]:
    """Packs on this machine: ELI Legal's own first, then ELI v3's and ELI v2's."""
    places: list[tuple[str, Path]] = [("ELI Legal", own_dir())]
    if os.environ.get("ELI_V3_ROOT"):
        places.append(("ELI v3", Path(os.environ["ELI_V3_ROOT"]) / "runtime" / "gpu"))
    for app, origin in (("ELI_v3", "ELI v3"), ("ELI_v2", "ELI v2")):
        places += [(origin, root / "runtime" / "gpu") for root in data_roots(app)]
    found: dict[Path, Pack] = {}
    for origin, path in places:
        pack = _pack_at(path, origin) if path.is_dir() else None
        if pack is not None:
            found.setdefault(pack.path, pack)
    return list(found.values())


def shipped_wheels() -> list[Path]:
    """Pack files shipped inside an installed copy."""
    base = getattr(sys, "_MEIPASS", None)
    folder = Path(base) / "gpu-packs" if base else None
    if folder is None or not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.whl") if _WHEEL_NAME.match(p.name))


def builtin_version() -> str:
    """The version of the llama.cpp for Python that is part of this copy, without importing it.
    Decided once, before any pack is on the path."""
    global _builtin
    if _builtin is None:
        packs = [str(p.path) for p in installed()]
        _builtin = next(
            (
                str(d.version)
                for d in importlib.metadata.distributions(name="llama-cpp-python")
                if not any(str(d.locate_file("")).startswith(p) for p in packs)
            ),
            "",
        )
    return _builtin


def _order(packs: list[Pack], hw: hardware.Hardware) -> list[Pack]:
    """CUDA is for NVIDIA cards and is tried first there; Vulkan runs on any maker's card."""
    wanted = ("cuda", "vulkan") if hw.gpu_vendor == "nvidia" else ("vulkan",)
    return [p for backend in wanted for p in packs if p.backend == backend]


# ── switching a pack on ──────────────────────────────────────────────────────


def _load(path: Path | str, *, share: bool = False) -> bool:
    try:
        ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL if share else ctypes.DEFAULT_MODE)
    except OSError as exc:
        # kept for the probe to report: the system's own words for why a pack cannot run here
        # (most often a C or C++ library older than the one the pack was built with)
        _not_loaded.append(f"{Path(str(path)).name}: {exc}")
        return False
    return True


def _preload(pack: Path) -> None:
    """Load the pack's own libraries by path before llama.cpp is imported, so each later lookup
    by name resolves inside the pack and not in a copy on the library path.

    Order matters, dependencies first. libllama is left for llama.cpp for Python to load itself:
    loading it twice ends in a double free when the program exits."""
    lib = pack / "llama_cpp" / "lib"
    if not lib.is_dir():
        return
    if sys.platform == "win32":
        os.add_dll_directory(str(lib))
        for pattern in ("cudart64*.dll", "cublasLt64*.dll", "cublas64*.dll"):
            for found in sorted(lib.glob(pattern)):
                _load(found)
        return
    for pattern in ("libcudart.so*", "libcublasLt.so*", "libcublas.so*"):
        for found in sorted(lib.glob(pattern)):
            _load(found)
    if any(lib.glob("libggml-vulkan.so*")):
        # The Vulkan loader belongs to the graphics driver and is not in the pack. Inside an
        # installed copy the library path points at the copy's own libraries, so it is loaded
        # by path here; and the drivers' descriptions are named, or none is found.
        if not os.environ.get("VK_ICD_FILENAMES"):
            icds = [
                str(f)
                for d in (
                    "/usr/share/vulkan/icd.d",
                    "/etc/vulkan/icd.d",
                    "/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d",
                )
                if Path(d).is_dir()
                for f in sorted(Path(d).glob("*.json"))
            ]
            if icds:
                os.environ["VK_ICD_FILENAMES"] = ":".join(icds)
        named = ctypes.util.find_library("vulkan")
        for candidate in (
            *([named] if named else []),
            "/usr/lib/x86_64-linux-gnu/libvulkan.so.1",
            "/usr/lib64/libvulkan.so.1",
            "/usr/lib/libvulkan.so.1",
            "libvulkan.so.1",
        ):
            if _load(candidate, share=True):
                break
    for pattern in (
        "libggml-base.so*",
        "libggml-cpu.so*",
        "libggml-vulkan.so*",
        "libggml-cuda.so*",
        "libggml.so*",
    ):
        for found in sorted(lib.glob(pattern)):
            _load(found, share=True)


def _forget_llama() -> None:
    for name in [k for k in sys.modules if k == "llama_cpp" or k.startswith("llama_cpp.")]:
        sys.modules.pop(name, None)


def _switch_on(pack: Path) -> None:
    where = str(pack)
    if where in sys.path:
        sys.path.remove(where)
    sys.path.insert(0, where)
    _preload(pack)
    _forget_llama()


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    """llama.cpp announces the cards it found on the error stream as it starts. That is not an
    error, and on a command line it would sit in front of every answer."""
    try:
        sys.stderr.flush()
        saved, null = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    except (OSError, ValueError, AttributeError):
        yield
        return
    try:
        os.dup2(null, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(null)


def _import_llama() -> tuple[Any, bool]:
    """(llama.cpp for Python, whether it can place layers on a card)."""
    with _quiet():
        module = importlib.import_module("llama_cpp")
        try:
            module.llama_cpp.llama_backend_init()
            return module, bool(module.llama_supports_gpu_offload())
        except (AttributeError, OSError):
            return module, False


def probe(pack_dir: str) -> int:
    """Run in a process of its own (``eli-legal gpu probe DIR``): switch this pack on exactly as
    the application would and report whether it can place layers on a card. A pack that only
    imports is worse than none: it would replace the built-in llama.cpp with a slower one."""
    _switch_on(Path(pack_dir))
    module, offload = _import_llama()
    if not offload:
        refused = next((r for r in _not_loaded if "ggml" in r), "")
        print(
            "it loaded but cannot place layers on a card"
            + (f": the system refused {refused[:300]}" if refused else "")
        )
        return 2
    print(PROBE_OK, getattr(module, "__version__", ""))
    return 0


def _own_command() -> list[str]:
    if getattr(sys, "frozen", False):
        cli = Path(sys.executable).with_name("eli-legal" + (".exe" if os.name == "nt" else ""))
        return [str(cli if cli.exists() else sys.executable)]
    return [sys.executable, "-m", "eli_legal"]


def _verified_file() -> Path:
    return runtime_dir() / "gpu_verified.json"


def _verify_key(pack: Pack) -> str:
    try:
        stamp = int((pack.path / "llama_cpp" / "__init__.py").stat().st_mtime)
    except OSError:
        stamp = 0
    return f"{pack.path}|{pack.version}|{pack.backend}|{stamp}"


def verify(pack: Pack, *, again: bool = False) -> tuple[bool, str]:
    """Whether this pack places layers on this machine's card, shown by starting it in a
    process of its own. A pass is remembered; a failure is tried again the next time the
    program starts, since a driver may have been put right in between."""
    key = _verify_key(pack)
    if not again:
        try:
            if key in json.loads(_verified_file().read_text(encoding="utf-8")):
                return True, "verified before"
        except (OSError, ValueError):
            pass
        if key in _failed:
            return False, _failed[key]
    try:
        out = subprocess.run(  # noqa: S603 - our own program, fixed arguments
            [*_own_command(), "gpu", "probe", str(pack.path)],
            capture_output=True,
            text=True,
            timeout=_PROBE_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        detail = "\n".join(x.strip() for x in (out.stdout, out.stderr) if x and x.strip())
        ok = out.returncode == 0 and PROBE_OK in (out.stdout or "")
        if out.returncode < 0:
            detail = f"it stopped with signal {-out.returncode}\n{detail}"
    except (OSError, subprocess.SubprocessError) as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    if not ok:
        _failed[key] = detail[-600:] or "no output"
        return False, _failed[key]
    try:
        path = _verified_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            known = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        known[key] = {"backend": pack.backend, "version": pack.version, "origin": pack.origin}
        path.write_text(json.dumps(known, indent=2), encoding="utf-8")
    except OSError:
        log.debug("could not remember the verified pack", exc_info=True)
    return True, detail[-300:]


def _fits_this_copy(pack: Pack, builtin: str) -> str:
    """Why this pack cannot be used beside the built-in llama.cpp, or ""."""
    if getattr(sys, "frozen", False) and builtin and pack.version != builtin:
        return (
            f"{pack.describe()} is not the version built into this copy ({builtin}); "
            "the two cannot share a process"
        )
    return ""


def _unpack_shipped(hw: hardware.Hardware) -> Pack | None:
    """Put the pack shipped inside the installer in ELI Legal's own runtime folder."""
    wanted = "cuda" if hw.gpu_vendor == "nvidia" else "vulkan"
    wheels = shipped_wheels()
    for backend in dict.fromkeys((wanted, "vulkan")):
        for wheel in wheels:
            if wheel.name.startswith(backend + "-"):
                try:
                    return install(wheel)
                except (InvalidInput, OSError):
                    log.warning("the shipped pack %s was not unpacked", wheel.name, exc_info=True)
    return None


def _try(pack: Pack, runtime: Runtime) -> bool:
    """Switch this pack on if it fits this copy and passes; say why not otherwise."""
    reason = _fits_this_copy(pack, builtin_version())
    if not reason:
        ok, detail = verify(pack)
        reason = "" if ok else f"{pack.describe()} did not start on this card: {detail}"
    if reason:
        runtime.notes.append(reason)
        return False
    _switch_on(pack.path)
    try:
        module, offload = _import_llama()
    except Exception as exc:  # a pack that cannot be imported must not end the attempt
        runtime.notes.append(f"{pack.describe()} could not be loaded: {type(exc).__name__}")
        sys.path.remove(str(pack.path))
        _forget_llama()
        return False
    runtime.available, runtime.offload = True, offload
    runtime.version = str(getattr(module, "__version__", pack.version))
    runtime.backend, runtime.origin, runtime.path = pack.backend, pack.origin, str(pack.path)
    return True


def _activate() -> Runtime:
    runtime = Runtime()
    choice = os.environ.get("ELI_LEGAL_GPU", "auto").strip().lower()
    if sys.platform != "darwin" and choice not in ("off", "0", "no", "cpu"):
        hw = hardware.detect()
        if hw.has_gpu:
            builtin_version()
            packs = installed()
            if choice == "own":
                packs = [p for p in packs if p.origin == "ELI Legal"]
            if any(_try(pack, runtime) for pack in _order(packs, hw)):
                return runtime
            if not any(p.origin == "ELI Legal" for p in packs):
                shipped = _unpack_shipped(hw)
                if shipped is not None and _try(shipped, runtime):
                    return runtime
            if not runtime.notes:
                runtime.notes.append(
                    f"{hw.gpu_name} is present and no graphics pack for llama.cpp is installed"
                )
    try:
        module, offload = _import_llama()
    except Exception:  # an import that fails for any reason means it cannot be used
        return runtime
    runtime.available, runtime.offload = True, offload
    runtime.version = str(getattr(module, "__version__", ""))
    if offload:
        runtime.backend = "metal" if sys.platform == "darwin" else "graphics"
    return runtime


def llama() -> Any | None:
    """llama.cpp for Python, with graphics support switched on where a pack passes; None when
    it is not installed. Everything in ELI Legal that needs llama.cpp gets it here."""
    global _state
    module = sys.modules.get("llama_cpp")
    if module is not None:
        return module
    with _lock:
        if sys.modules.get("llama_cpp") is None:
            _state = (_activate(), None)
            _state = (_state[0], sys.modules.get("llama_cpp"))
        return sys.modules.get("llama_cpp")


def current() -> Runtime:
    """The llama.cpp in use (deciding it now if nothing has asked yet)."""
    global _state
    with _lock:
        module = llama()
        if _state is None or _state[1] is not module:
            # Something else imported llama.cpp first: describe it as found.
            found = Runtime(available=module is not None)
            if module is not None:
                found.version = str(getattr(module, "__version__", ""))
                supports = getattr(module, "llama_supports_gpu_offload", None)
                try:
                    found.offload = bool(supports()) if callable(supports) else False
                except OSError:
                    found.offload = False
            _state = (found, module)
        return _state[0]


def supports_offload() -> bool:
    return current().offload


# ── installing a pack from a file ────────────────────────────────────────────


def install(wheel: Path) -> Pack:
    """Unpack a graphics pack (a ``cuda-…`` or ``vulkan-llama_cpp_python-….whl`` file, as
    published with ELI) into ELI Legal's own runtime folder, replacing the one there. The file
    is read from this machine; nothing is fetched."""
    wheel = Path(wheel).expanduser()
    named = _WHEEL_NAME.match(wheel.name)
    if not wheel.is_file() or not named:
        raise InvalidInput(
            "a graphics pack is a file named cuda-llama_cpp_python-<version>-….whl or "
            "vulkan-llama_cpp_python-<version>-….whl"
        )
    backend, version = named.group(1), named.group(2)
    dest = own_dir()
    reason = _fits_this_copy(Pack(dest, backend, version, "ELI Legal"), builtin_version())
    if reason:
        raise InvalidInput(reason)
    digest = hashlib.sha256()
    with wheel.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    staging = dest.with_name(dest.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(wheel) as archive:
            root = staging.resolve()
            for member in archive.infolist():
                target = (root / member.filename).resolve()
                if root != target and root not in target.parents:
                    raise InvalidInput(f"the pack holds a path outside itself: {member.filename}")
            archive.extractall(staging)  # noqa: S202 - every member was checked above
        if _version_of(staging) != version:
            raise InvalidInput("the file does not hold the llama.cpp version its name states")
        (staging / ".gpu_pack.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "backend": backend,
                    "source": wheel.name,
                    "sha256": digest.hexdigest(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InvalidInput(f"the pack could not be unpacked: {exc}") from exc
    except InvalidInput:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(dest, ignore_errors=True)
    staging.replace(dest)
    return Pack(dest.resolve(), backend, version, "ELI Legal")


def status() -> dict[str, Any]:
    """What is in use and what else was found, for a screen or ``eli-legal gpu status``."""
    runtime = current()
    return {
        "in_use": runtime.as_dict() | {"summary": runtime.describe()},
        "built_in_version": builtin_version(),
        "packs": [
            {
                "backend": p.backend,
                "version": p.version,
                "origin": p.origin,
                "folder": str(p.path),
                "usable_here": not _fits_this_copy(p, builtin_version()),
            }
            for p in installed()
        ],
        "shipped": [w.name for w in shipped_wheels()],
    }
