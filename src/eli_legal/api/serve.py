"""``eli-legal serve``: start the server, refusing any configuration that would expose matter
content carelessly."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from eli_legal.application.services import Services, build_services
from eli_legal.settings import Settings

from . import tls
from .config import ServerConfig, is_loopback


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="address to listen on (default: this machine only)")
    parser.add_argument("--port", type=int, help="port (default 8443)")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="listen on every interface so other machines can connect; requires TLS",
    )
    parser.add_argument("--tls-cert", type=Path, help="certificate file (PEM)")
    parser.add_argument("--tls-key", type=Path, help="private key file (PEM)")
    parser.add_argument(
        "--self-signed",
        action="store_true",
        help="create and use a self-signed certificate if none is given",
    )
    parser.add_argument(
        "--behind-proxy",
        action="store_true",
        help="a reverse proxy terminates TLS; needs --trusted-proxy",
    )
    parser.add_argument("--trusted-proxy", action="append", default=[], metavar="ADDRESS")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="NAME",
        help="a name clients use to reach this server (repeatable)",
    )
    parser.add_argument(
        "--require-second-factor",
        choices=("auto", "yes", "no"),
        default=None,
        help="auto (default) requires it whenever other machines can connect",
    )
    parser.add_argument("--api-docs", action="store_true", help="serve /docs (off by default)")
    parser.add_argument(
        "--dev-data",
        action="store_true",
        help="from a developer checkout, serve its test data even though an installed copy's "
        "data exists (otherwise refused, to keep the browser and the desktop on one set of data)",
    )


def build_config(
    args: argparse.Namespace, settings: Settings
) -> tuple[ServerConfig, Path | None, Path | None]:
    """The configuration to run with, and the certificate pair if this process terminates TLS."""
    host = args.host or ("0.0.0.0" if args.lan else settings.server_host)  # noqa: S104 - explicit --lan
    cert, key = args.tls_cert or settings.server_tls_cert, args.tls_key or settings.server_tls_key
    names = [n.lower() for n in args.allowed_host]
    exposed = not is_loopback(host)
    if exposed:
        names += tls.local_names()
    if args.self_signed and not (cert and key):
        folder = Path(settings.audit_key_file).parent / "tls"
        cert, key = folder / "server.crt", folder / "server.key"
        tls.ensure_self_signed(cert, key, sorted({*tls.local_names(), *names}))
    second = {"yes": True, "no": False}.get(args.require_second_factor or "")
    config = ServerConfig.from_settings(
        settings,
        host=host,
        port=args.port,
        tls=bool(cert and key),
        behind_proxy=args.behind_proxy or None,
        trusted_proxies=tuple(args.trusted_proxy) or None,
        require_second_factor=second,
        api_docs=args.api_docs or None,
    )
    config = replace(config, allowed_hosts=tuple(dict.fromkeys((*config.allowed_hosts, *names))))
    return config, (cert if config.tls else None), (key if config.tls else None)


def uvicorn_options(config: ServerConfig, cert: Path | None, key: Path | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "server_header": False,  # do not advertise what is running
        "proxy_headers": config.behind_proxy,
        "forwarded_allow_ips": ",".join(config.trusted_proxies) if config.behind_proxy else None,
        "timeout_keep_alive": 15,
        "limit_concurrency": 200,
        "h11_max_incomplete_event_size": 64 * 1024,
        "log_level": "info",
        "workers": 1,  # one process: one writer to the databases, one rate limiter
    }
    if cert and key:
        options.update(ssl_certfile=str(cert), ssl_keyfile=str(key))
    return options


def hardened(app: Any, config: ServerConfig, cert: Path | None, key: Path | None) -> Any:
    """The uvicorn configuration, with old TLS versions switched off explicitly rather than
    left to whatever the operating system's defaults happen to be."""
    import ssl

    import uvicorn

    class Hardened(uvicorn.Config):
        def load(self) -> None:
            super().load()
            if self.ssl is not None:
                self.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
                self.ssl.options |= ssl.OP_NO_COMPRESSION

    return Hardened(app, **uvicorn_options(config, cert, key))


def banner(config: ServerConfig, cert: Path | None) -> str:
    scheme = "https" if config.tls else "http"
    shown = (
        "localhost"
        if is_loopback(config.host)
        else next(
            (n for n in config.allowed_hosts if n not in ("localhost", "127.0.0.1", "::1")),
            config.host,
        )
    )
    lines = [f"ELI Legal server: {scheme}://{shown}:{config.port}/"]
    if config.exposed:
        lines.append(
            "  reachable from other machines; answers to: " + ", ".join(config.allowed_hosts)
        )
    else:
        lines.append("  this machine only. Use --lan with TLS to let other machines connect.")
    if cert:
        lines.append(f"  certificate SHA-256 fingerprint: {tls.fingerprint(cert)}")
        lines.append("  compare it with what your browser shows before trusting this server")
    if config.behind_proxy:
        lines.append("  TLS is terminated by the proxy at: " + ", ".join(config.trusted_proxies))
    lines.append(
        "  second factor: required for every web sign-in"
        if config.require_second_factor
        else "  second factor: optional (each user may set one up)"
    )
    lines.append(
        f"  sessions end after {config.idle_minutes:g} idle minutes or {config.session_hours:g} hours"
    )
    return "\n".join(lines)


def run(args: argparse.Namespace, services: Services | None = None) -> int:
    import uvicorn

    from eli_legal.paths import installation, serving_test_data_by_mistake

    from .app import create_app

    mistake = serving_test_data_by_mistake()
    if mistake and not getattr(args, "dev_data", False) and services is None:
        print(f"refused: {mistake}", file=sys.stderr)
        return 2
    settings = Settings()
    config, cert, key = build_config(args, settings)
    problems = config.problems()
    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        return 2
    sv = services or build_services(settings)
    if not sv.ctx.store.list_users():
        print(
            "refused: no users exist yet. Create the first administrator, for example:\n"
            "  eli-legal init --admin jay",
            file=sys.stderr,
        )
        return 2
    from eli_legal.adapters.local.renditions import ensure_typesetter

    typesetter = ensure_typesetter()  # on the main thread, before any request; kept alive below
    print(banner(config, cert), flush=True)
    where = installation()
    print(f"  data: {where['folder']} ({where['kind']})", flush=True)
    server_config = hardened(create_app(sv, config), config, cert, key)
    sockets = None
    if settings.hard_offline:
        # Listen first, then lock down: the server keeps answering on its own port, while the
        # kernel refuses every connection it might try to open.
        sockets = [server_config.bind_socket()]
        state = sv.network.go_offline(actor_id="system")
        print(f"  hard offline: enforced by {state['enforced_by']}", flush=True)
    stop = sv.checks.start_schedule()  # the routine checks, whenever they fall due
    _logged(sv, "server_started", config)
    try:
        uvicorn.Server(server_config).run(sockets=sockets)
    except KeyboardInterrupt:
        pass  # Ctrl+C: uvicorn has already shut down cleanly; no traceback for an intended stop
    finally:
        stop.set()
        _logged(sv, "server_stopped", config)
        del typesetter
    print("ELI Legal server stopped.", flush=True)
    return 0


def _logged(sv: Services, event: str, config: ServerConfig) -> None:
    """Where the server listened and how it was protected, in the audit trail (AI Act Art. 12)."""
    sv.ctx.log(
        event,
        actor_id="system",
        matter_id="-",
        action="server.manage",
        subject_id="server",
        outcome=event.removeprefix("server_"),
        object_type="server",
        payload={
            "port": config.port,
            "exposed": config.exposed,
            "tls": config.tls,
            "second_factor": config.require_second_factor,
        },
    )
