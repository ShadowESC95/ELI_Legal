"""The ELI Legal server: the whole system over HTTPS, and nothing else.

It is a shell over the application services, the same ones the desktop application and the
command line call, so roles, matter membership, gates, holds and the audit ledger apply
unchanged. It serves a JSON API under ``/v1`` and the browser application at ``/``.

It has no general assistant, no shell, no device, media or home control, no plug-ins and no route
that reaches the internet. Start it with ``eli-legal serve``; see ``serve.py`` for what it insists
on before it will listen beyond this machine.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from eli_legal import __version__
from eli_legal.application.services import Services, build_services
from eli_legal.domain.errors import (
    AccountLocked,
    AuditIntegrityError,
    AuthenticationFailed,
    EliLegalError,
    InvalidInput,
    InvalidState,
    MatterAccessDenied,
    NotFound,
    PolicyDenied,
    VerificationGateFailed,
)

from . import (
    routes_auth,
    routes_frameworks,
    routes_guidance,
    routes_matters,
    routes_notifications,
    routes_oversight,
    routes_runs,
)
from .auth import Access
from .config import ServerConfig
from .security import Shield

log = logging.getLogger("eli_legal.server")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_STATUS: tuple[tuple[type[EliLegalError], int], ...] = (
    (AccountLocked, 423),
    (AuthenticationFailed, 401),
    (PolicyDenied, 403),
    (MatterAccessDenied, 403),
    (NotFound, 404),
    (InvalidInput, 422),
    (VerificationGateFailed, 409),
    (InvalidState, 409),
    (AuditIntegrityError, 500),
)


class Jobs:
    """Work that outlives its request: a run executes on its own thread, as the person who
    started it, so the server stays responsive and the browser can watch it progress."""

    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []

    def start(self, work: Callable[[], Any]) -> None:
        context = contextvars.copy_context()  # carries who is acting into the thread

        def run() -> None:
            try:
                context.run(work)
            except Exception:  # the run records its own failures; this is the last resort
                log.exception("background work failed")

        self._threads = [t for t in self._threads if t.is_alive()]
        thread = threading.Thread(target=run, name="eli-legal-run", daemon=True)
        self._threads.append(thread)
        thread.start()

    def wait(self, timeout: float = 120.0) -> bool:
        for thread in list(self._threads):
            thread.join(timeout)
        return not any(t.is_alive() for t in self._threads)


def create_app(services: Services | None = None, config: ServerConfig | None = None) -> FastAPI:
    sv = services or build_services()
    cfg = config or ServerConfig.from_settings(sv.ctx.settings)
    docs = {} if cfg.api_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="ELI Legal", version=__version__, **docs)  # type: ignore[arg-type]
    app.state.services, app.state.config, app.state.jobs = sv, cfg, Jobs()
    access = Access(sv, cfg)

    @app.exception_handler(EliLegalError)
    async def _refused(request: Request, exc: EliLegalError) -> JSONResponse:
        code = next((status for kind, status in _STATUS if isinstance(exc, kind)), 400)
        return JSONResponse({"error": type(exc).__name__, "detail": str(exc)}, status_code=code)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        names = {400: "BadRequest", 401: "AuthenticationFailed", 403: "Forbidden", 404: "NotFound"}
        return JSONResponse(
            {"error": names.get(exc.status_code, "Error"), "detail": str(exc.detail)},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Say which field and why, and never echo what was sent: it may be a passphrase.
        problems = [
            f"{'.'.join(str(p) for p in e.get('loc', ()) if p != 'body')}: {e.get('msg', 'invalid')}"
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": "InvalidInput", "detail": "; ".join(problems)}, status_code=422
        )

    @app.exception_handler(Exception)
    async def _failed(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": "ServerError", "detail": "the server could not complete this request"},
            status_code=500,
        )

    for module in (
        routes_auth,
        routes_matters,
        routes_runs,
        routes_oversight,
        routes_frameworks,
        routes_guidance,
        routes_notifications,
    ):
        module.register(app, sv, cfg, access)

    # ── the browser application ──────────────────────────────────────────────
    if WEB_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    app.add_middleware(Shield, config=cfg)
    return app
