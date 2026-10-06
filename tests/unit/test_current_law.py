from datetime import date, datetime, timedelta, timezone

from eli_legal.domain.enums import AuthorityKind, AuthorityStatus
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.models import Authority, Treatment
from eli_legal.legal.authority_status import applicable_on, status_at
from eli_legal.legal.current_law_citator import CurrentLawCitator
from eli_legal.legal.jurisdictions import JurisdictionRegistry
from eli_legal.ports.legal_sources import StatusFinding
from eli_legal.settings import Settings

PACKS = JurisdictionRegistry.from_dir(Settings(_env_file=None).jurisdictions_dir)
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
FRESH = NOW - timedelta(days=2)


def _case(**kw) -> Authority:
    return Authority(
        source_id="s",
        citation="[2011] IESC 1",
        title="A v B",
        jurisdiction="IE",
        status=AuthorityStatus.IN_FORCE,
        **kw,
    )


def _assess(authority: Authority, *, pack="IE", relevant=None, checked=FRESH):
    finding = StatusFinding(
        status_now=status_at(authority, NOW.date()),
        status_at_relevant_date=status_at(authority, relevant) if relevant else None,
        checked_at=checked,
        basis="test",
        events=tuple(authority.treatments),
    )
    return CurrentLawCitator.assess(
        authority, finding, pack=PACKS.get(pack), relevant_date=relevant, now=NOW
    )


def test_overruled_case_fails_and_says_by_what_and_when():
    case = _case(treatments=[Treatment("overruled", date(2022, 6, 10), "[2022] IESC 7")])
    status, detail = _assess(case)
    assert status is V.FAILED
    assert "overruled" in detail and "2022-06-10" in detail and "[2022] IESC 7" in detail


def test_case_law_is_judged_as_it_stands_today_even_if_good_law_when_the_events_happened():
    case = _case(treatments=[Treatment("overruled", date(2022, 6, 10))])
    assert _assess(case, relevant=date(2020, 1, 1))[0] is V.FAILED


def test_followed_or_distinguished_does_not_change_standing():
    case = _case(
        treatments=[
            Treatment("followed", date(2023, 1, 1)),
            Treatment("distinguished", date(2024, 1, 1)),
        ]
    )
    assert _assess(case)[0] is V.VERIFIED


def test_doubted_case_goes_to_a_person():
    assert _assess(_case(treatments=[Treatment("doubted", date(2023, 1, 1))]))[0] is V.CONFLICT


def test_status_never_confirmed_or_gone_stale_is_inconclusive_not_verified():
    assert _assess(_case(), checked=None)[0] is V.INCONCLUSIVE
    status, detail = _assess(_case(), checked=NOW - timedelta(days=200))
    assert status is V.INCONCLUSIVE and "30-day" in detail


def test_staleness_never_rescues_a_negative_status():
    case = _case(treatments=[Treatment("overruled", date(2022, 6, 10))])
    assert _assess(case, checked=NOW - timedelta(days=900))[0] is V.FAILED


def test_unknown_status_is_inconclusive():
    unknown = Authority(source_id="s", citation="x", title="x", jurisdiction="IE")
    assert _assess(unknown)[0] is V.INCONCLUSIVE


def test_civil_law_pack_treats_a_contrary_later_decision_as_a_conflict_not_a_failure():
    case = Authority(
        source_id="s",
        citation="VIII ZR 1/18",
        title="x",
        jurisdiction="DE",
        status=AuthorityStatus.IN_FORCE,
        treatments=[Treatment("overruled", date(2022, 1, 1))],
    )
    assert _assess(case, pack="DE")[0] is V.CONFLICT


def _act(**kw) -> Authority:
    return Authority(
        source_id="s",
        citation="Commercial Contracts Act 2009",
        title="Act",
        jurisdiction="IE",
        kind=AuthorityKind.LEGISLATION,
        status=AuthorityStatus.IN_FORCE,
        **kw,
    )


def test_legislation_is_judged_on_the_relevant_date():
    old = _act(
        effective_from=date(2009, 7, 1),
        effective_to=date(2020, 12, 31),
        treatments=[Treatment("amended", date(2021, 1, 1))],
    )
    new = _act(effective_from=date(2021, 1, 1))
    assert applicable_on(old, date(2019, 5, 1)) and not applicable_on(old, date(2023, 4, 28))
    assert _assess(old, relevant=date(2019, 5, 1))[0] is V.VERIFIED
    status, detail = _assess(old, relevant=date(2023, 4, 28))
    assert status is V.FAILED and "not the one in force" in detail
    assert _assess(new, relevant=date(2023, 4, 28))[0] is V.VERIFIED
    assert _assess(new, relevant=date(2019, 5, 1))[0] is V.FAILED  # not yet in force then


def test_amended_legislation_with_no_relevant_date_goes_to_a_person():
    amended = _act(treatments=[Treatment("amended", date(2021, 1, 1))])
    assert _assess(amended)[0] is V.CONFLICT


def test_repealed_legislation_fails():
    assert _assess(_act(treatments=[Treatment("repealed", date(2022, 1, 1))]))[0] is V.FAILED
