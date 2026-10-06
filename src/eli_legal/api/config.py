"""How the server is exposed. Everything here defaults to the careful choice."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, replace
from typing import Any

LOCAL_NAMES = ("localhost", "127.0.0.1", "::1")


def is_loopback(host: str) -> bool:
    """True only for a bind address that other machines cannot reach."""
    name = (host or "").strip().lower().strip("[]")
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8443
    tls: bool = False  # this process terminates TLS itself
    behind_proxy: bool = False  # a reverse proxy on a trusted address terminates TLS
    trusted_proxies: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = LOCAL_NAMES  # the names this server answers to
    session_hours: float = 8.0
    idle_minutes: float = 30.0
    require_second_factor: bool = False
    max_upload_bytes: int = 250 * 1024 * 1024
    max_json_bytes: int = 1024 * 1024
    login_attempts_per_minute: int = 10
    requests_per_minute: int = 600
    api_docs: bool = False

    @property
    def secure(self) -> bool:
        """Browsers reach this server over HTTPS."""
        return self.tls or self.behind_proxy

    @property
    def exposed(self) -> bool:
        return not is_loopback(self.host)

    @property
    def cookie_name(self) -> str:
        # The __Host- prefix makes a browser refuse the cookie unless it is Secure, host-only
        # and for the whole site, so a sibling host cannot set or overwrite it.
        return "__Host-eli_legal_session" if self.secure else "eli_legal_session"

    def problems(self) -> list[str]:
        """Why this configuration must not be started, as plain sentences."""
        found = []
        if self.exposed and not self.secure:
            found.append(
                "refusing to listen beyond this machine without TLS: give --tls-cert and "
                "--tls-key, or --self-signed, or --behind-proxy if a reverse proxy terminates TLS"
            )
        if self.behind_proxy and not self.trusted_proxies:
            found.append("--behind-proxy needs at least one --trusted-proxy address")
        if self.tls and self.behind_proxy:
            found.append("choose one: this server terminates TLS, or the proxy does")
        return found

    @classmethod
    def from_settings(cls, settings: Any, **overrides: Any) -> ServerConfig:
        extra = tuple(
            h.strip().lower() for h in settings.server_allowed_hosts.split(",") if h.strip()
        )
        base = cls(
            host=settings.server_host,
            port=settings.server_port,
            tls=bool(settings.server_tls_cert and settings.server_tls_key),
            allowed_hosts=tuple(dict.fromkeys((*LOCAL_NAMES, *extra))),
            session_hours=settings.server_session_hours,
            idle_minutes=settings.server_idle_minutes,
            max_upload_bytes=settings.server_max_upload_mb * 1024 * 1024,
        )
        config = replace(base, **{k: v for k, v in overrides.items() if v is not None})
        wanted = str(settings.server_require_second_factor).strip().lower()
        if "require_second_factor" not in overrides or overrides["require_second_factor"] is None:
            required = config.exposed if wanted == "auto" else wanted in ("1", "true", "yes", "on")
            config = replace(config, require_second_factor=required)
        return config
