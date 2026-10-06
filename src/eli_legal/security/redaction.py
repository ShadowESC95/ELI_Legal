from __future__ import annotations

import hashlib
import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


def minimise_for_audit(text: str, max_chars: int = 256) -> str:
    """Avoid copying full privileged/personal content into audit events."""
    compact = " ".join((text or "").split())
    return compact[:max_chars]


def content_hash(text: str | bytes) -> str:
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalise_ws(text: str) -> str:
    """Whitespace-insensitive form used when checking that a quotation really appears."""
    return " ".join(text.split())


def quote_hash(quote: str) -> str:
    return content_hash(normalise_ws(quote))


def mask_contact_details(text: str) -> str:
    """Mask e-mail addresses and phone-like numbers for operational logs."""
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))
