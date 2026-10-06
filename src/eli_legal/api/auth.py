"""Who is calling, established per request.

Two credentials are accepted, and nothing else:

* a **session cookie**, set by signing in with a passphrase (and a code, where a second factor is
  set up). It is HttpOnly, so page scripts cannot read it, and SameSite=Strict, so another site
  cannot make a browser send it. Any request that changes something must also carry the CSRF
  value handed to the page at sign-in.
* a **bearer token** for programs, issued to a named user who confirmed their passphrase.

A decision additionally needs the person's passphrase with the request. The application core
decides which actions those are; if one arrives without it, the answer is ``StepUpRequired`` and
the caller asks for the passphrase and sends the request again.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

from fastapi import HTTPException, Request, Response

from eli_legal.application.services import Services
from eli_legal.security import authn

from .config import ServerConfig

WEB_METHOD = "web-session"
TOKEN_METHOD = "api-token"
CSRF_HEADER = "x-eli-csrf"
SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


def csrf_for(session_token: str) -> str:
    """Derived from the session token, which page scripts cannot read. Only this server's own
    pages are told the value; another site can neither read it nor guess it."""
    return hashlib.sha256(b"eli-legal-csrf:" + session_token.encode("utf-8")).hexdigest()


def passphrase_from(request: Request) -> str | None:
    """The passphrase sent for a decision. The encoded form carries any character safely."""
    encoded = request.headers.get("x-eli-passphrase-b64")
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise HTTPException(400, "X-ELI-Passphrase-B64 is not valid base64 UTF-8") from exc
    return request.headers.get("x-eli-passphrase")


class Access:
    def __init__(self, services: Services, config: ServerConfig) -> None:
        self.sv = services
        self.config = config

    async def user(self, request: Request) -> str:
        """Identify the caller, establish that identity for this request, and (when a passphrase
        accompanies the request) confirm it for a decision."""
        authn.clear()
        sv, cfg = self.sv, self.config
        header = request.headers.get("authorization", "")
        session = ""
        if header.lower().startswith("bearer "):
            user_id = sv.ctx.store.user_for_token(header[7:].strip())
            if user_id is None:
                raise HTTPException(401, "unknown or revoked token", {"WWW-Authenticate": "Bearer"})
            method = TOKEN_METHOD
        else:
            session = request.cookies.get(cfg.cookie_name, "")
            if not session:
                raise HTTPException(401, "sign in first")
            user_id = sv.users.session_user(
                session, method=WEB_METHOD, idle_minutes=cfg.idle_minutes
            ).user_id
            if request.method not in SAFE and not hmac.compare_digest(
                request.headers.get(CSRF_HEADER, ""), csrf_for(session)
            ):
                raise HTTPException(403, "the X-ELI-CSRF header is missing or wrong")
            method = WEB_METHOD
        sv.ctx.user(user_id)  # refuses a deactivated account
        if (
            cfg.require_second_factor
            and method == WEB_METHOD
            and not request.url.path.startswith("/v1/auth/")
            and not sv.users.has_second_factor(user_id)
        ):
            raise HTTPException(403, "set up your second factor before going any further")
        phrase = passphrase_from(request)
        if phrase:
            sv.users.confirm(user_id, phrase)
        authn.establish(user_id, method, step_up=bool(phrase))
        request.state.session = session
        return user_id

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            self.config.cookie_name,
            token,
            max_age=int(self.config.session_hours * 3600),
            httponly=True,
            secure=self.config.secure,
            samesite="strict",
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(
            self.config.cookie_name,
            path="/",
            secure=self.config.secure,
            httponly=True,
            samesite="strict",
        )
