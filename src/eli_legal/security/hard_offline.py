"""Hard offline: the operating system's kernel, not Python, refuses network access.

The network guard (``adapters/local/network.py``) intercepts Python's own ``socket.connect``.
That stops Python code, but not native code (llama.cpp, a compiled extension, anything using
``ctypes``), not Linux's io_uring interface, and not a process started from this one. Hard
offline closes all of those:

**Linux.** A seccomp filter is installed on every thread of the process. From then on the
kernel refuses to create any socket except local ones (Unix domain sockets, which the window
system needs, and netlink), refuses io_uring (which can create sockets without the ``socket``
system call), and refuses system calls made through another architecture's interface (x32, or
32-bit ``int 0x80``), which are the known ways around such a filter. The kernel offers no way to
remove a filter: it stays until the program exits, and every process this one starts inherits
it. Turning hard offline off therefore takes effect only at the next start.

**macOS.** The program is started again inside the kernel's sandbox with a profile that denies
every network connection except local ones. This can only happen at start.

**Windows.** An outbound block rule for this program is added to Windows Defender Firewall. This
needs an administrator once; without one, the program says that it is not kernel-enforced.

Whatever the system, the network guard is also told, so every connector refuses at once and in
plain words rather than failing deep inside a library.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass

from eli_legal.adapters.local import network

# ── what is in force ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OfflineState:
    active: bool  # in force for this process now
    enforced_by: str  # what refuses the network: the kernel, a firewall, or only this program
    detail: str
    verified: bool = False  # a native-code connection attempt was refused after applying


_state = OfflineState(False, "", "Hard offline is not switched on.")


def state() -> OfflineState:
    return _state


def go_offline() -> OfflineState:
    """Switch hard offline on for this process now. It cannot be switched off again until the
    program is restarted. Idempotent."""
    global _state
    if _state.active:
        return _state
    network.set_hard_offline(True)  # connectors refuse at once, whatever happens below
    system = platform.system()
    try:
        if system == "Linux":
            _apply_seccomp()
            _state = OfflineState(
                True,
                "the Linux kernel (a seccomp filter on every thread)",
                "No socket other than a local one can be created by any code in this program or "
                "any process it starts, until the program exits.",
                verified=_verify_native_refused(),
            )
        elif system == "Windows":
            _state = _windows_firewall()
        elif system == "Darwin" and os.environ.get(_SANDBOXED) == "1":
            _state = OfflineState(
                True,
                "the macOS kernel sandbox",
                "The program was started inside a sandbox that denies network connections.",
                verified=_verify_native_refused(),
            )
        else:
            _state = OfflineState(
                True,
                "this program only",
                "This system offers no kernel enforcement that can be applied while the program "
                "is running; the network guard refuses every connection. "
                + ("Restart the program to start it inside the kernel sandbox."
                   if system == "Darwin" else ""),
            )  # fmt: skip
    except OSError as exc:
        _state = OfflineState(
            True,
            "this program only",
            f"The kernel refused to apply the filter ({exc}); the network guard refuses every "
            "connection instead.",
        )
    return _state


# ── Linux: seccomp ───────────────────────────────────────────────────────────
_ARCH = {
    # machine: (audit arch, socket, io_uring_setup, seccomp, x32 bit)
    "x86_64": (0xC000003E, 41, 425, 317, 0x40000000),
    "amd64": (0xC000003E, 41, 425, 317, 0x40000000),
    "aarch64": (0xC00000B7, 198, 425, 277, None),
    "arm64": (0xC00000B7, 198, 425, 277, None),
}
_LOCAL_FAMILIES = (socket.AF_UNIX, 16)  # Unix domain sockets; netlink (16) carries no traffic out
_PR_SET_NO_NEW_PRIVS = 38
_SECCOMP_SET_MODE_FILTER = 1
_SECCOMP_FILTER_FLAG_TSYNC = 1
_RET_ALLOW = 0x7FFF0000
_RET_EACCES = 0x00050000 | 13  # SECCOMP_RET_ERRNO with EACCES: the caller gets an error


def _ins(code: int, jt: int, jf: int, k: int) -> bytes:
    return struct.pack("=HBBI", code, jt, jf, k)


def _filter(machine: str) -> list[bytes]:
    """The BPF program. Allows everything except creating a non-local socket, io_uring, and
    any system call made through another architecture's interface."""
    arch, sys_socket, sys_uring, _seccomp, x32 = _ARCH[machine]
    LD_W_ABS, JEQ, JGE, RET = 0x20, 0x15, 0x35, 0x06  # noqa: N806
    # Laid out with the two returns last; jumps are counted from the next instruction.
    body: list[tuple[str, int, int | str, int | str]] = [
        ("ld", 4, 0, 0),  # seccomp_data.arch
        ("jeq", arch, 0, "deny"),
        ("ld", 0, 0, 0),  # seccomp_data.nr
    ]
    if x32 is not None:
        body.append(("jge", x32, "deny", 0))
    body += [
        ("jeq", sys_uring, "deny", 0),
        ("jeq", sys_socket, 0, "allow"),
        ("ld", 16, 0, 0),  # seccomp_data.args[0]: the address family
    ]
    for n, family in enumerate(_LOCAL_FAMILIES):
        last = n == len(_LOCAL_FAMILIES) - 1
        body.append(("jeq", int(family), "allow", "deny" if last else 0))
    labels = {"allow": len(body), "deny": len(body) + 1}
    out = []
    for i, (op, k, jt, jf) in enumerate(body):
        if op == "ld":
            out.append(_ins(LD_W_ABS, 0, 0, k))
            continue
        out.append(_ins(JEQ if op == "jeq" else JGE, _jump(jt, i, labels), _jump(jf, i, labels), k))
    out += [_ins(RET, 0, 0, _RET_ALLOW), _ins(RET, 0, 0, _RET_EACCES)]
    return out


def _jump(to: int | str, at: int, labels: dict[str, int]) -> int:
    """A jump offset: to a label, counted from the instruction after ``at``; or as given."""
    return labels[to] - at - 1 if isinstance(to, str) else to


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _apply_seccomp() -> None:
    machine = platform.machine().lower()
    if machine not in _ARCH:
        raise OSError(f"no seccomp filter is defined for the {machine} processor")
    program = b"".join(_filter(machine))
    buffer = ctypes.create_string_buffer(program, len(program))
    prog = _SockFprog(len(program) // 8, ctypes.cast(buffer, ctypes.c_void_p))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong]  # fmt: skip
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "could not set no_new_privs")
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(
        ctypes.c_long(_ARCH[machine][3]),
        ctypes.c_long(_SECCOMP_SET_MODE_FILTER),
        ctypes.c_long(_SECCOMP_FILTER_FLAG_TSYNC),
        ctypes.byref(prog),
    )
    if result != 0:
        # With TSYNC, a positive result names a thread that could not take the filter.
        raise OSError(ctypes.get_errno() or 1, f"seccomp refused the filter ({result})")


def _verify_native_refused() -> bool:
    """Prove it the hard way: ask the C library directly for an internet socket, as native code
    would, and expect the kernel to refuse."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    except OSError:
        return False
    if fd >= 0:
        os.close(fd)
        return False
    return True


# ── Windows: a firewall rule ─────────────────────────────────────────────────
RULE_NAME = "ELI Legal hard offline"


def windows_rule_command(program: str, *, remove: bool = False) -> list[str]:
    if remove:
        return ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"]
    return ["netsh", "advfirewall", "firewall", "add", "rule", f"name={RULE_NAME}",
            "dir=out", "action=block", f"program={program}", "enable=yes"]  # fmt: skip


def _windows_firewall() -> OfflineState:
    done = subprocess.run(  # noqa: S603 - fixed command, no shell
        windows_rule_command(sys.executable), capture_output=True, text=True, check=False
    )
    if done.returncode == 0:
        return OfflineState(
            True,
            "Windows Defender Firewall (an outbound block rule for this program)",
            "The firewall blocks every outbound connection this program makes, until the rule "
            "is removed when hard offline is switched off.",
        )
    return OfflineState(
        True,
        "this program only",
        "Adding the firewall rule needs an administrator: start ELI Legal once as an "
        "administrator with hard offline on. Until then the network guard refuses every "
        "connection.",
    )


def remove_windows_rule() -> None:
    if platform.system() == "Windows":
        subprocess.run(windows_rule_command("", remove=True), capture_output=True, check=False)  # noqa: S603


# ── macOS: start inside the kernel sandbox ───────────────────────────────────
_SANDBOXED = "ELI_LEGAL_SANDBOXED"
MACOS_PROFILE = (
    "(version 1)(allow default)"
    '(deny network-outbound (remote ip "*:*"))'
    '(deny network-inbound (local ip "*:*"))'
)


def relaunch_sandboxed_if_needed() -> None:
    """On macOS, with hard offline on, start this program again inside the kernel sandbox. The
    profile is tried on a harmless command first, so a refusal never stops the program from
    starting; it then runs with the network guard alone and says so."""
    if platform.system() != "Darwin" or os.environ.get(_SANDBOXED) == "1":
        return
    tool = shutil.which("sandbox-exec")
    if tool is None:
        return
    probe = subprocess.run([tool, "-p", MACOS_PROFILE, "/usr/bin/true"], check=False)  # noqa: S603
    if probe.returncode != 0:
        return
    os.environ[_SANDBOXED] = "1"
    os.execv(tool, [tool, "-p", MACOS_PROFILE, sys.executable, *sys.argv])  # noqa: S606
