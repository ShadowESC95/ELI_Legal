"""The server, started and stopped from the desktop application.

An administrator or a judge (anyone whose account may ``server.manage``) can start the server
from Settings → System, so that everyone on a case can sign in from their own machine. It is
the same server as ``eli-legal serve``, with the same refusals: other machines reach it only
over TLS (a self-signed certificate is made if there is none) and only with a second factor.

It runs inside the desktop application, on the application's own services: one process, one
writer to the databases and the audit trail, one set of notifications. Its thread starts with
no identity at all, so nothing a browser sends can act as the person at the desktop; each
request proves its own. Starting and stopping need the passphrase again, and each is written
to the audit trail with where the server listened and how it was protected (AI Act Art. 12,
ISO/IEC 42001 A.6.2.8). Closing the application stops it.
"""

from __future__ import annotations

import argparse
import contextvars
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.application.services import Services
from eli_legal.domain.errors import InvalidState
from eli_legal.security import authn, hard_offline

from . import tls
from .config import ServerConfig
from .serve import build_config, hardened

DEFAULT_PORT = 8443


@dataclass(slots=True)
class HostedServer:
    services: Services
    _server: Any = None
    _thread: threading.Thread | None = None
    _config: ServerConfig | None = None
    _cert: Path | None = None
    _by: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server is not None)

    def status(self) -> dict[str, Any]:
        if not self.running or self._config is None:
            return {"running": False}
        config = self._config
        port = self._bound_port() or config.port
        scheme = "https" if config.tls else "http"
        names = [n for n in config.allowed_hosts if n not in ("localhost", "127.0.0.1", "::1")]
        return {
            "running": True,
            "url": f"{scheme}://localhost:{port}/",
            "others": [f"{scheme}://{n}:{port}/" for n in names] if config.exposed else [],
            "exposed": config.exposed,
            "tls": config.tls,
            "second_factor": config.require_second_factor,
            "fingerprint": tls.fingerprint(self._cert) if self._cert else "",
            "started_by": self._by,
            "port": port,
        }

    # ── start and stop ───────────────────────────────────────────────────────
    def start(
        self, *, actor_id: str, lan: bool = False, port: int = DEFAULT_PORT
    ) -> dict[str, Any]:
        """Start the server: on this machine only, or (``lan``) for other machines too, over
        TLS with a second factor. Needs ``server.manage`` and the passphrase again."""
        sv = self.services
        authn.require_step_up(actor_id, "start the server")
        sv.ctx.authorizer().require_global(actor_id, "server.manage")
        with self._lock:
            if self.running:
                raise InvalidState("the server is already running; stop it first")
            if hard_offline.state().active:
                raise InvalidState(
                    "this window is hard offline, so it cannot open the server's port; start the "
                    "server with `eli-legal serve` instead (it listens first, then locks down), "
                    "or restart ELI Legal without hard offline"
                )
            args = argparse.Namespace(
                host=None,
                port=port,
                lan=lan,
                tls_cert=None,
                tls_key=None,
                self_signed=lan,
                behind_proxy=False,
                trusted_proxy=[],
                allowed_host=[],
                require_second_factor=None,
                api_docs=False,
            )
            config, cert, key = build_config(args, sv.ctx.settings)
            problems = config.problems()
            if problems:
                raise InvalidState("; ".join(problems))
            if lan and not config.require_second_factor:
                raise InvalidState("other machines may connect only with a second factor")
            from .app import create_app

            server = __import__("uvicorn").Server(
                hardened(create_app(sv, config), config, cert, key)
            )
            # A thread with an empty context: no identity, no step-up, nothing from the desktop.
            thread = threading.Thread(
                target=contextvars.Context().run,
                args=(server.run,),
                name="eli-legal-server",
                daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + 15
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not server.started:
                server.should_exit = True
                thread.join(timeout=5)
                raise InvalidState(
                    f"the server could not start on port {config.port}: is another server "
                    "(another ELI Legal, or `eli-legal serve`) already using it?"
                )
            self._server, self._thread, self._config, self._cert, self._by = (
                server,
                thread,
                config,
                cert,
                actor_id,
            )
        state = self.status()
        sv.ctx.log(
            "server_started",
            actor_id=actor_id,
            matter_id="-",
            action="server.manage",
            subject_id="server",
            outcome="started",
            object_type="server",
            payload={
                "port": state["port"],
                "exposed": state["exposed"],
                "tls": state["tls"],
                "second_factor": state["second_factor"],
            },
        )
        return state

    def stop(self, *, actor_id: str) -> None:
        """Stop the server. Needs ``server.manage`` and the passphrase again, except when the
        application stops it on closing (``actor_id="system"``)."""
        sv = self.services
        if actor_id != "system":
            authn.require_step_up(actor_id, "stop the server")
            sv.ctx.authorizer().require_global(actor_id, "server.manage")
        with self._lock:
            if not self.running:
                return
            port = self._bound_port()
            self._server.should_exit = True
            assert self._thread is not None
            self._thread.join(timeout=15)
            self._server = self._thread = self._config = self._cert = None
        sv.ctx.log(
            "server_stopped",
            actor_id=actor_id,
            matter_id="-",
            action="server.manage",
            subject_id="server",
            outcome="stopped",
            object_type="server",
            payload={"port": port},
        )

    def _bound_port(self) -> int | None:
        try:
            return int(self._server.servers[0].sockets[0].getsockname()[1])
        except (AttributeError, IndexError, TypeError):
            return None
