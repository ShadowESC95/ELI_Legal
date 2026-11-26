"""Whether this copy of ELI Legal may run, and what it may do.

A licence to ELI Legal is a key of its own or an ELI v3 key that includes it. Keys live in the
folder every ELI product shares, so a key activated in ELI v3 counts here, and one activated here
counts in ELI v3. They are checked offline against ELI's public key (eli-sdk), with the
revocation lists ELI has published.

Before a key is entered, an installed copy runs a **seven-day trial** from its first use. A
trial covers **practice matters only**: a real matter (real people's papers, a report to be
relied on) needs a paid licence, as it needs a signed deployment authorisation. The trial is
kept by eli_sdk.trial.LocalTrial, so deleting its record, changing environment variables,
editing it or setting the clock back does not restart it, and nor does deleting it once ELI
Legal's own data shows it has been used. A key can be entered at any time: during the trial,
at its end, or later.

An installed copy needs a licence or a trial. A source checkout doesn't, and nor does a copy
ELI v3 opened in its own process, since ELI v3 checked the ELI Legal licence before starting it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_sdk import Entitlement, InvalidKey, KeyStore, License, LocalTrial, TrialStatus
from eli_sdk import store as eli_store

from eli_legal import __version__

PRODUCT = "legal"
OFFERING = "legal-pro"
STORE_URL = eli_store.STORE_URL
BUY = f"{STORE_URL}/?product={PRODUCT}"
TRIAL_SCOPE = "practice matters only"

_YES = {"1", "true", "yes", "on"}
_public_key: Any = None
_hosted = False
_trial_locations: list[Path] | None = None  # tests only: where the trial's record is kept


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
    """What the keys on this machine grant (a trial *key* included), not the local trial."""
    return store().entitlement(PRODUCT, _public_key, version=__version__)


# ── the trial ────────────────────────────────────────────────────────────────
def _default_data_folders() -> list[Path]:
    """Where an installed ELI Legal keeps its data, found from the account itself, so pointing
    ELI_LEGAL_HOME or XDG_DATA_HOME somewhere new does not hide earlier use."""
    from eli_sdk.machine import account_home, windows_folder

    home = account_home()
    if os.name == "nt":
        return [(windows_folder("local") or home / "AppData" / "Local") / "ELI Legal"]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "ELI Legal"]
    return [home / ".local" / "share" / "eli-legal"]


def _used_before() -> bool:
    """ELI Legal's own data from earlier use: its working database, or a case folder."""
    from eli_legal.paths import home_dir

    folders = _default_data_folders()
    explicit = home_dir()
    if explicit is not None:
        folders.append(explicit)
    for folder in folders:
        data = folder / "data"
        if (data / "eli_legal.sqlite3").exists() or (data / "audit.sqlite3").exists():
            return True
        matters = data / "matters"
        if matters.is_dir() and any(matters.iterdir()):
            return True
    return False


def trial() -> LocalTrial:
    return LocalTrial(PRODUCT, used_before=_used_before, locations=_trial_locations)


@dataclass(frozen=True)
class Standing:
    """May this copy run, and on what terms."""

    granted: bool
    reason: str
    on_trial: bool = False
    days_left: int = 0
    licence: License | None = None
    trial: TrialStatus | None = None

    @property
    def real_matters(self) -> bool:
        """Whether real matters are covered: a paid licence, never a trial."""
        return self.granted and not self.on_trial

    def describe(self) -> str:
        if not self.granted:
            return f"ELI Legal is not licensed on this machine: {self.reason}"
        if self.on_trial:
            n = self.days_left
            return (
                f"ELI Legal trial: {n} day{'s' if n != 1 else ''} left, {TRIAL_SCOPE}. "
                "A licence key can be entered at any time."
            )
        lic = self.licence
        if lic is None:
            return "ELI Legal: no licence needed for this copy"
        return f"{self.reason}: {lic.tier}, {lic.seats} seat(s), ELI Legal {lic.major_version}.x"


def _days_left(lic: License) -> int:
    from datetime import datetime, timezone

    if not lic.expires_at:
        return 0
    ends = datetime.fromisoformat(str(lic.expires_at).replace("Z", "+00:00"))
    seconds = int((ends - datetime.now(timezone.utc)).total_seconds())
    return max(0, -(-seconds // 86400))


def standing(*, start: bool = False) -> Standing:
    """Where this copy stands. ``start`` begins the trial on first use (at launch), and also
    records that ELI Legal ran now, so a clock set back is noticed."""
    if not required():
        return Standing(True, "no licence needed for this copy")
    got = status()
    if got.granted and got.license is not None:
        lic = got.license
        return Standing(
            True,
            got.reason,
            on_trial=lic.trial,
            days_left=_days_left(lic) if lic.trial else 0,
            licence=lic,
        )
    held_trial = [
        lic for lic in store().licenses(_public_key) if lic.product == PRODUCT and lic.trial
    ]
    if held_trial:  # a trial key from the store was this machine's trial; no second one
        return Standing(False, got.reason)
    local = trial()
    ts = local.start() if start else local.status()
    if ts.active:
        return Standing(True, "ELI Legal trial", on_trial=True, days_left=ts.days_left, trial=ts)
    reason = ts.why if ts.state == "ended" else got.reason
    return Standing(False, reason, trial=ts)


def allowed() -> bool:
    """Whether this run may go on; begins the trial on first use."""
    return standing(start=True).granted


def covers_real_matters() -> bool:
    """Whether real matters may be worked on here: a paid licence, never a trial."""
    if not required():
        return True
    return standing().real_matters


def real_matter_refusal() -> str:
    return (
        "ELI Legal's trial covers practice matters only: a real matter needs a paid ELI "
        f"Legal licence. Buy one at {BUY}, or enter your key (Help → Licence…, or "
        "eli-legal licence activate YOUR-KEY)."
    )


# ── keys and buying ──────────────────────────────────────────────────────────
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


def buy_link(claim: str | None = None, *, offering: str | None = None) -> str:
    """The store's ELI Legal page (or one offering's), carrying the claim the key is collected by."""
    if offering:
        return eli_store.buy_url(offering, claim, store=STORE_URL)
    return eli_store.shop_url(PRODUCT, claim, store=STORE_URL)


def collect(claim: str) -> list[License]:
    """Activate whatever was bought under this claim; [] while payment is still completing."""
    done = []
    for key in eli_store.collect(claim, store=STORE_URL):
        try:
            done.append(store().add(key, _public_key))
        except InvalidKey:
            continue
    return done


def refresh_revocations() -> int:
    """Bring the store's latest revocation lists (when online). Returns how many changed."""
    changed = 0
    for token in eli_store.fetch_revocations(store=STORE_URL):
        try:
            changed += store().add_revocations(token, _public_key)
        except InvalidKey:
            continue
    return changed


def explain() -> str:
    st = standing()
    return (
        f"ELI Legal needs a licence: {st.reason}.\n"
        "Activate an ELI Legal key, or an ELI v3 key that includes ELI Legal:\n"
        "    eli-legal licence activate YOUR-KEY\n"
        "Or buy one and have it activated here automatically:\n"
        "    eli-legal licence buy\n"
        f"Buy online: {BUY}"
    )
