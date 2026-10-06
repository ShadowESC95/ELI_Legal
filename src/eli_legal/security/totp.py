"""Time-based one-time codes (RFC 6238, the kind every authenticator app produces).

A passphrase proves that someone knows a secret. A second factor proves that they also hold a
particular device. Six digits, thirty-second steps, HMAC-SHA-1: the parameters authenticator apps
assume. A code is accepted one step either side of now to allow for clock drift, and never twice.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def step_at(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def verify(
    secret: str, code: str, *, at: float | None = None, last_step: int = 0, window: int = 1
) -> int | None:
    """The time step the code belongs to, or None. A step at or before ``last_step`` is refused,
    so a code that has been used once cannot be replayed."""
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != DIGITS:
        return None
    now = step_at(at)
    matched: int | None = None
    for step in range(now - window, now + window + 1):
        # compare every candidate, so timing does not reveal which one matched
        if hmac.compare_digest(code_at(secret, step), digits) and step > last_step:
            matched = step
    return matched


def provisioning_uri(secret: str, account: str, issuer: str = "ELI Legal") -> str:
    """What an authenticator app reads, typed in or scanned."""
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"
