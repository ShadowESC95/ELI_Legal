"""How an authority's standing is worked out for a given date.

An authority carries a dated history of treatments. Standing is always computed *for a date*, so
the same record answers both "what was the position when the events happened?" and "what is it
now?".
"""

from __future__ import annotations

from datetime import date

from eli_legal.domain.enums import AuthorityStatus
from eli_legal.domain.models import Authority

# Treatments that change whether an authority can be relied on. Anything else (followed,
# applied, distinguished, considered) is history that leaves the status as it was.
_STATUS_CHANGING: dict[str, AuthorityStatus] = {
    "overruled": AuthorityStatus.OVERRULED,
    "reversed": AuthorityStatus.REVERSED,
    "superseded": AuthorityStatus.SUPERSEDED,
    "repealed": AuthorityStatus.REPEALED,
    "amended": AuthorityStatus.AMENDED,
    "doubted": AuthorityStatus.DOUBTED,
    "commenced": AuthorityStatus.IN_FORCE,
    "restored": AuthorityStatus.IN_FORCE,
}


def status_at(authority: Authority, when: date) -> AuthorityStatus:
    if authority.status is AuthorityStatus.UNKNOWN and not authority.treatments:
        return AuthorityStatus.UNKNOWN
    if authority.effective_from and when < authority.effective_from:
        return AuthorityStatus.NOT_YET_IN_FORCE
    status = AuthorityStatus.IN_FORCE
    for t in sorted(authority.treatments, key=lambda t: t.effective_date):
        if t.effective_date <= when and t.treatment.lower() in _STATUS_CHANGING:
            status = _STATUS_CHANGING[t.treatment.lower()]
    if authority.effective_to and when > authority.effective_to:
        # This version has ended. If it was replaced by an amended text it is superseded as a
        # version; otherwise the instrument itself is gone.
        status = (
            AuthorityStatus.AMENDED
            if status is AuthorityStatus.AMENDED
            else AuthorityStatus.REPEALED
        )
    return status


def applicable_on(authority: Authority, when: date) -> bool:
    """Whether this version of an authority is the one in force on ``when``."""
    if authority.effective_from and when < authority.effective_from:
        return False
    return not (authority.effective_to and when > authority.effective_to)
