from __future__ import annotations

import hashlib
import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
# An international bank account number: two letters, two check digits, then 11 to 30 letters
# and digits, often written in groups of four.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b")
# A payment card number: 13 to 19 digits, optionally in groups.
_CARD = re.compile(r"(?<!\w)\d{4}(?:[ -]?\d{3,4}){2,3}(?:[ -]?\d{1,4})?(?!\w)")
# A personal public service or similar national number: seven digits and one or two letters.
_NATIONAL_ID = re.compile(r"\b\d{7}[A-Z]{1,2}\b")
# Dates are not telephone numbers: 2023-04-28, 28.04.2023, 28/04/2023.
_DATE_LIKE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")


def _phone(match: re.Match[str]) -> str:
    return match.group(0) if _DATE_LIKE.match(match.group(0).strip()) else "[phone]"


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
    return _PHONE.sub(_phone, _EMAIL.sub("[email]", text))


def mask_personal_data(text: str) -> str:
    """Contact details, bank and card numbers and national identity numbers masked, for
    people whose role on a matter is to observe or audit it rather than to work it. Names,
    dates and amounts are left: they are what the dispute is about."""
    text = _IBAN.sub("[bank account]", _EMAIL.sub("[email]", text or ""))
    text = _NATIONAL_ID.sub("[id number]", _CARD.sub("[card number]", text))
    return _PHONE.sub(_phone, text)
