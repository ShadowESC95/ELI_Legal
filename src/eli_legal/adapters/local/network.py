"""Deny-by-default outbound network control for the legal runtime.

Installing the guard patches Python's socket connect calls for this process. A connection is
allowed only if it is loopback/unix, or its host is inside a window opened with ``allow`` for a
host on the approved list. Windows are per host: opening one for a legal source does not open the
network generally.

Limits, stated plainly: this guards Python sockets in this process. It does not constrain a
subprocess or a native library that opens its own sockets, so it is defence in depth beneath an
operating-system or container egress rule, not a replacement for one.
"""

from __future__ import annotations

import errno
import ipaddress
import socket
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from eli_legal.domain.errors import NetworkDenied

_lock = threading.RLock()
_installed = False
_real_connect: Any = None
_real_connect_ex: Any = None
_approved_hosts: set[str] = set()
_open_hosts: dict[str, int] = {}
_open_ips: dict[str, int] = {}
_attempts: list[dict[str, str]] = []


def _is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _host_of(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None  # unix socket path or other non-IP family


def _permitted(sock: socket.socket, address: Any) -> bool:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return True
    host = _host_of(address)
    if host is None or _is_loopback(host):
        return True
    with _lock:
        allowed = host in _open_ips or host.lower() in _open_hosts
        if not allowed:
            _attempts.append({"host": host, "outcome": "blocked"})
            del _attempts[:-200]
        return allowed


def _guarded_connect(sock: socket.socket, address: Any) -> Any:
    if not _permitted(sock, address):
        raise NetworkDenied(f"outbound connection to {_host_of(address)} is not approved")
    return _real_connect(sock, address)


def _guarded_connect_ex(sock: socket.socket, address: Any) -> Any:
    if not _permitted(sock, address):
        return errno.ENETUNREACH
    return _real_connect_ex(sock, address)


_guarded_connect._eli_legal_guard = True  # type: ignore[attr-defined]


class NetworkGuard:
    def __init__(self, approved_hosts: Iterable[str] = ()) -> None:
        with _lock:
            _approved_hosts.update(h.lower() for h in approved_hosts)

    def install(self) -> bool:
        """Idempotent. Returns True the first time the guard is put in place."""
        global _installed, _real_connect, _real_connect_ex
        with _lock:
            if _installed or getattr(socket.socket.connect, "_eli_legal_guard", False):
                _installed = True
                return False
            _real_connect = socket.socket.connect
            _real_connect_ex = socket.socket.connect_ex
            socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
            socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
            _installed = True
            return True

    def uninstall(self) -> None:
        global _installed
        with _lock:
            if _installed and _real_connect is not None:
                socket.socket.connect = _real_connect  # type: ignore[method-assign]
                socket.socket.connect_ex = _real_connect_ex  # type: ignore[method-assign]
            _installed = False
            _open_hosts.clear()
            _open_ips.clear()

    @property
    def installed(self) -> bool:
        return _installed

    def approve_host(self, host: str) -> None:
        with _lock:
            _approved_hosts.add(host.lower())

    def approved_hosts(self) -> frozenset[str]:
        with _lock:
            return frozenset(_approved_hosts)

    def blocked_attempts(self) -> list[dict[str, str]]:
        with _lock:
            return list(_attempts)

    @contextmanager
    def allow(self, *, host: str, reason: str) -> Iterator[None]:
        """Open egress to one approved host for the duration of the block."""
        host = host.lower()
        if not reason.strip():
            raise NetworkDenied("a reason is required to open a network window")
        with _lock:
            if host not in _approved_hosts:
                raise NetworkDenied(f"host is not on the approved list: {host}")
        ips: list[str] = []
        try:
            ips = sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})
        except OSError:
            ips = []
        with _lock:
            _open_hosts[host] = _open_hosts.get(host, 0) + 1
            for ip in ips:
                _open_ips[ip] = _open_ips.get(ip, 0) + 1
        try:
            yield
        finally:
            with _lock:
                _open_hosts[host] -= 1
                if _open_hosts[host] <= 0:
                    del _open_hosts[host]
                for ip in ips:
                    _open_ips[ip] -= 1
                    if _open_ips[ip] <= 0:
                        del _open_ips[ip]
