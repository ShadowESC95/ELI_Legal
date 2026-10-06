"""Who is acting, and how that was established.

Authorisation (roles, matter membership) answers "may this person do this?". It is worthless if
anyone can claim to be that person. So every service call is refused unless the identity it
names has been *established* in the current context by a front end that verified a credential:

* the command line, from a signed-in session opened with the user's passphrase;
* the desktop application, from a passphrase sign-in;
* the HTTP API, from a bearer token.

A decision made in a person's name — resolving a hold, recording a verification, approving,
releasing, restarting, closing a matter — additionally needs **step-up**: the passphrase again,
at the moment of the decision.

How identity was established is written into every audit event, so the ledger shows not just who
acted but on what proof. Code that calls the services directly inside the process (tests, the
demonstration) must install a harness that vouches for the caller, and that too is what the
ledger then records.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from eli_legal.domain.errors import AuthenticationFailed

UNAUTHENTICATED = "unauthenticated"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    method: str  # cli-session, gui-passphrase, api-token, eli-host, test-harness, ...
    step_up: bool = False  # the passphrase was given again for this action

    @property
    def label(self) -> str:
        return f"{self.method}+step-up" if self.step_up else self.method


_principal: ContextVar[Principal | None] = ContextVar("eli_legal_principal", default=None)
# A harness answers "who is this?" for any name it is asked about. Only tests and the
# demonstration install one; no front end does.
_harness: ContextVar[Callable[[str], Principal] | None] = ContextVar(
    "eli_legal_auth_harness", default=None
)


def current() -> Principal | None:
    return _principal.get()


def _resolve(actor_id: str) -> Principal | None:
    principal = _principal.get()
    if principal is not None and principal.user_id == actor_id:
        return principal
    harness = _harness.get()
    return harness(actor_id) if harness is not None else None


def method_for(actor_id: str) -> str:
    """How this actor's identity was established, for the audit record."""
    principal = _resolve(actor_id)
    return principal.label if principal is not None else UNAUTHENTICATED


def require(actor_id: str) -> Principal:
    """Refuse unless ``actor_id`` is the identity established for this call."""
    principal = _resolve(actor_id)
    if principal is None:
        established = _principal.get()
        if established is None:
            raise AuthenticationFailed("no identity has been established; sign in first")
        raise AuthenticationFailed(
            f"this session belongs to {established.user_id!r}; it cannot act as {actor_id!r}"
        )
    return principal


def require_step_up(actor_id: str, what: str) -> Principal:
    """Refuse a decision unless the person confirmed their passphrase for it."""
    principal = require(actor_id)
    if not principal.step_up:
        raise AuthenticationFailed(
            f"to {what}, confirm your passphrase: a decision recorded in your name needs it again"
        )
    return principal


@contextmanager
def established(user_id: str, method: str, *, step_up: bool = False) -> Iterator[Principal]:
    """Act as ``user_id`` for the duration of the block. Call only after verifying a credential."""
    principal = Principal(user_id, method, step_up)
    token = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(token)


def establish(user_id: str, method: str, *, step_up: bool = False) -> Principal:
    """Set the identity for the rest of this context (a signed-in desktop session, a request)."""
    principal = Principal(user_id, method, step_up)
    _principal.set(principal)
    return principal


def clear() -> None:
    _principal.set(None)


@contextmanager
def stepped_up(method_suffix: str = "") -> Iterator[Principal]:
    """Mark the current identity as freshly re-confirmed for one decision."""
    principal = _principal.get()
    if principal is None:
        raise AuthenticationFailed("no identity has been established; sign in first")
    with established(principal.user_id, principal.method + method_suffix, step_up=True) as up:
        yield up


@contextmanager
def harness(method: str, *, step_up: bool = True) -> Iterator[None]:
    """Vouch for whatever identity the caller names. For tests and the demonstration only.

    Everything done under a harness is recorded in the audit ledger with this method, so it can
    never be mistaken for a person who proved who they were.
    """
    token = _harness.set(lambda actor_id: Principal(actor_id, method, step_up))
    try:
        yield
    finally:
        _harness.reset(token)


def install_harness(method: str, *, step_up: bool = True) -> None:
    _harness.set(lambda actor_id: Principal(actor_id, method, step_up))


def remove_harness() -> None:
    _harness.set(None)
