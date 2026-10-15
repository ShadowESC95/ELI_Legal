"""Whether this copy of ELI Legal may run.

A licence to ELI Legal is a key of its own or an ELI v3 key that includes it. Keys live in the
folder every ELI product shares, so a key activated in ELI v3 counts here, and one activated here
counts in ELI v3. They are checked offline against ELI's public key.

An installed copy needs one. A source checkout doesn't, and nor does a copy ELI v3 opened in its
own process, since ELI v3 checked the licence before starting it.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from eli_sdk import Entitlement, InvalidKey, KeyStore, License

from eli_legal import __version__

PRODUCT = "legal"
BUY = "https://ko-fi.com/shadowesc95 · jaybridgeman0095@gmail.com"

_YES = {"1", "true", "yes", "on"}
_public_key: Any = None
_hosted = False


def hosted_by_eli() -> None:
    global _hosted
    _hosted = True


def required() -> bool:
    if _hosted:
        return False
    if os.environ.get("ELI_LEGAL_REQUIRE_LICENCE", "").strip().lower() in _YES:
        return True
    return bool(getattr(sys, "frozen", False))


def store() -> KeyStore:
    return KeyStore.shared()


def status() -> Entitlement:
    return store().entitlement(PRODUCT, _public_key, version=__version__)


def allowed() -> bool:
    return not required() or status().granted


def activate(key: str) -> License:
    """Keep a key and confirm it licenses ELI Legal. An ELI v3 key that doesn't include ELI
    Legal is still kept, for ELI v3, and the error says why it isn't enough here."""
    lic = store().add(key, _public_key)
    got = status()
    if not got.granted:
        raise InvalidKey(got.reason)
    return lic


def remove() -> bool:
    return store().remove(PRODUCT)


def explain() -> str:
    got = status()
    return (
        f"ELI Legal needs a licence: {got.reason}.\n"
        "Activate an ELI Legal key, or an ELI v3 key that includes ELI Legal:\n"
        "    eli-legal licence activate YOUR-KEY\n"
        f"Buy one: {BUY}"
    )
