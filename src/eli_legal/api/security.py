"""What stands between the network and the application.

One ASGI layer, applied to every request before any route runs, in this order:

1. **Host.** The request must name a host this server answers to. This defeats DNS rebinding,
   where a hostile web page makes a browser talk to a local address under its own name.
2. **Origin.** A request that changes anything must come from this server's own pages. A browser
   says where a request came from; anything else is refused. (Cross-site request forgery is also
   blocked by the SameSite cookie and by the CSRF header, see ``auth``.)
3. **Rate.** Each client address has a budget, and a much smaller one for sign-in and passphrase
   attempts.
4. **Size.** A body must declare its length, and the length must be within the limit for that
   route, before a byte of it is read.
5. **Headers.** Every response tells the browser to load nothing from anywhere else, never to
   frame the page, never to guess content types, to send no referrer, and to keep nothing.

There is no CORS: no other origin is ever allowed to read a response.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

from .config import ServerConfig

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_UPLOAD = re.compile(r"^/v1/matters/[^/]+/documents$")

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
BASE_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), display-capture=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-permitted-cross-domain-policies": "none",
}


def host_of(value: str) -> str:
    """The host part of a Host header, without the port."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if ":" in value else value


class RateLimiter:
    """Sliding one-minute windows per client address. In memory: the server is one process."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, bucket: str, client: str, limit: int, now: float | None = None) -> float:
        """0 if allowed, otherwise the number of seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > 20_000:  # forget idle clients rather than grow without bound
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                    del self._hits[key]
            window = self._hits.setdefault((bucket, client), deque())
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= limit:
                return max(1.0, 60 - (now - window[0]))
            window.append(now)
            return 0.0


class Shield:
    def __init__(self, app: App, config: ServerConfig) -> None:
        self.app = app
        self.config = config
        self.allowed = {h.lower() for h in config.allowed_hosts}
        self.limiter = RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":  # nothing here speaks WebSocket
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method, path = scope["method"], scope["path"]
        refusal = self._refusal(method, path, headers, (scope.get("client") or ("?", 0))[0])
        if refusal is not None:
            status, error, detail, extra = refusal
            await self._reject(send, status, error, detail, extra)
            return

        async def guarded(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = self._with_headers(message.get("headers", []), path)
            await send(message)

        await self.app(scope, receive, guarded)

    def _refusal(
        self, method: str, path: str, headers: dict[str, str], client: str
    ) -> tuple[int, str, str, dict[str, str]] | None:
        cfg = self.config
        host = headers.get("host", "")
        if "*" not in self.allowed and host_of(host) not in self.allowed:
            return 400, "UnknownHost", "this server does not answer to that host name", {}
        if method in UNSAFE:
            origin = headers.get("origin")
            if origin is not None and urlsplit(origin).netloc.lower() != host.lower():
                return 403, "CrossOrigin", "requests from another origin are refused", {}
            if headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
                return 403, "CrossOrigin", "requests from another site are refused", {}
        # Guessing a passphrase at a decision is stopped by the account lock, not by this budget:
        # a reviewer working through a list of holds confirms many times a minute, legitimately.
        sensitive = path == "/v1/auth/login"
        for bucket, limit in (
            ("auth", cfg.login_attempts_per_minute if sensitive else 0),
            ("all", cfg.requests_per_minute),
        ):
            wait = self.limiter.allow(bucket, client, limit) if limit else 0.0
            if wait:
                return (
                    429,
                    "TooManyRequests",
                    "too many requests; wait and try again",
                    {"retry-after": str(int(wait))},
                )
        if method in UNSAFE:
            # Without a declared length the body cannot be bounded before it is read. (A request
            # with neither header has no body at all, which is fine.)
            declared = headers.get("content-length", "0")
            if "transfer-encoding" in headers or not declared.isdigit():
                return 411, "LengthRequired", "a request body must declare its length", {}
            limit = cfg.max_upload_bytes if _UPLOAD.match(path) else cfg.max_json_bytes
            if int(declared) > limit:
                return 413, "TooLarge", f"the body is larger than {limit} bytes", {}
        return None

    def _with_headers(
        self, existing: list[tuple[bytes, bytes]], path: str
    ) -> list[tuple[bytes, bytes]]:
        present = {k.lower() for k, _ in existing}
        out = [(k, v) for k, v in existing if k.lower() != b"server"]
        wanted = dict(BASE_HEADERS)
        # Matter content must never sit in a browser or proxy cache.
        wanted["cache-control"] = "no-cache" if path.startswith("/assets/") else "no-store"
        if self.config.secure:
            wanted["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        out.extend((k.encode(), v.encode()) for k, v in wanted.items() if k.encode() not in present)
        return out

    async def _reject(
        self, send: Send, status: int, error: str, detail: str, extra: dict[str, str]
    ) -> None:
        body = json.dumps({"error": error, "detail": detail}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        headers += [(k.encode(), v.encode()) for k, v in extra.items()]
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": self._with_headers(headers, ""),
            }
        )
        await send({"type": "http.response.body", "body": body})
