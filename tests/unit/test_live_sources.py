"""Live official databases, answered from responses shaped exactly as the services answered on
2026-11-09 (CELLAR SPARQL JSON, EUR-Lex HTML, Find Case Law Akoma Ntoso, legislation.gov.uk CLML
and Atom). No test contacts a live service."""

import json
from dataclasses import replace
from datetime import date

import pytest

from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.adapters.sources import live
from eli_legal.domain.enums import AuthorityKind, AuthorityStatus
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.errors import ConnectorError, NetworkDenied
from eli_legal.legal.authority_status import applicable_on
from eli_legal.legal.current_law_citator import CurrentLawCitator
from eli_legal.legal.jurisdictions import JurisdictionRegistry
from eli_legal.persistence.sqlite import Store
from eli_legal.settings import Settings


def _sparql(rows):
    return json.dumps(
        {"results": {"bindings": [{k: {"value": v} for k, v in r.items()} for r in rows]}}
    ).encode()


GDPR = _sparql(
    [
        {"celex": "32016R0679", "date": "2016-04-27", "inforce": "1", "start": "2016-05-24",
         "end": "9999-12-31", "title": "Regulation (EU) 2016/679 of the European Parliament and of the Council of 27 April 2016 on the protection of natural persons#…"},
        {"celex": "32016R0679", "start": "2018-05-25"},
    ]
)  # fmt: skip
DIRECTIVE = _sparql(
    [{"celex": "31995L0046", "date": "1995-10-24", "inforce": "0", "start": "1995-12-13",
      "end": "2018-05-24", "repealer": "32016R0679",
      "title": "Directive 95/46/EC of the European Parliament and of the Council of 24 October 1995 on the protection of individuals"}]
)  # fmt: skip
JUDGMENT = _sparql(
    [{"celex": "62012CJ0131", "date": "2014-05-13", "ecli": "ECLI:EU:C:2014:317",
      "title": "Judgment of the Court (Grand Chamber), 13 May 2014.#Google Spain SL"}]
)  # fmt: skip
EURLEX = (
    b"<html><body><p id='art_17'>Article 17</p><p>Right to erasure ('right to be forgotten')</p>"
    b"<p>1. The data subject shall have the right to obtain from the controller the erasure of "
    b"personal data concerning him or her without undue delay.</p></body></html>"
)
UKSC = b"""<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"><judgment name="judgment">
<meta><identification source="#tna"><FRBRWork><FRBRthis value="https://caselaw.nationalarchives.gov.uk/id/uksc/2019/41"/>
<FRBRdate date="2019-09-24" name="judgment"/><FRBRname value="R (on the application of Miller) v The Prime Minister"/></FRBRWork>
</identification></meta><judgmentBody><decision>
<paragraph eId="para_1"><num>1.</num><content><p>It is important to emphasise that the issue in these appeals is not when and on what terms the United Kingdom is to leave the European Union.</p></content></paragraph>
<paragraph eId="para_2"><num>2.</num><content><p>The issue is whether the advice given by the Prime Minister to Her Majesty was lawful.</p></content></paragraph>
</decision></judgmentBody></judgment></akomaNtoso>"""
FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://www.legislation.gov.uk/id/ukpga/1996/23</id><title>Arbitration Act 1996</title></entry>
<entry><id>http://www.legislation.gov.uk/id/uksi/1996/3146</id><title>The Arbitration Act 1996 (Commencement No.1) Order 1996</title></entry>
</feed>"""


def _act(valid: str, duty: str) -> bytes:
    return f"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dct="http://purl.org/dc/terms/">
<ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata"><dc:title>Arbitration Act 1996</dc:title><dct:valid>{valid}</dct:valid></ukm:Metadata>
<Primary><Body><P1group><P1 id="section-33"><Pnumber>33</Pnumber><P1para><Text>{duty}</Text></P1para></P1></P1group></Body></Primary>
</Legislation>""".encode()


RESPONSES = {
    "CELEX%3A32016R0679": EURLEX,
    "CELEX:32016R0679": EURLEX,
    "CELEX:31995L0046": EURLEX,
    "CELEX:62012CJ0131": EURLEX,
    "uksc/2019/41/data.xml": UKSC,
    "all/1996/data.feed": FEED,
    "ukpga/1996/23/2017-06-01/data.xml": _act("2016-01-01", "The tribunal shall act fairly and impartially."),
    "ukpga/1996/23/data.xml": _act("2025-08-01", "The tribunal shall act fairly and impartially, as amended."),
}  # fmt: skip


class Recorded:
    """Answers each request from the recorded responses, and counts the requests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, accept: str) -> bytes:
        self.calls.append(url)
        if "sparql" in url:
            from urllib.parse import parse_qs, urlsplit

            query = parse_qs(urlsplit(url).query)["query"][0]
            for marker, body in (
                ("32016R0679", GDPR),
                ("31995L0046", DIRECTIVE),
                ("ECLI:EU:C:2014:317", JUDGMENT),
                ("62012CJ0131", JUDGMENT),
            ):
                if marker in query:
                    return body
            return _sparql([])
        for key in sorted(RESPONSES, key=len, reverse=True):
            if key in url:
                return RESPONSES[key]
        raise ConnectorError(f"404 for {url}")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "s.db")


def _connector(store, kind, as_of=None, fetch=None):
    source = replace(live.preset(kind, kind), terms_reviewed=True, approved=True)
    cls = live.CONNECTORS[kind]
    return cls(store, source, fetch or Recorded(), as_of)


PACKS = JurisdictionRegistry.from_dir(Settings(_env_file=None).jurisdictions_dir)


def _assess(connector, authority, when):
    finding = connector.status(authority=authority, as_of=when)
    return CurrentLawCitator.assess(
        authority, finding, pack=PACKS.get(authority.jurisdiction), relevant_date=when
    )


def test_eu_citations_become_the_identifiers_the_publications_office_uses():
    assert live.celex_for("regulation (eu) 2016/679") == ("celex", "32016R0679")
    assert live.celex_for("directive 95/46/ec") == ("celex", "31995L0046")
    assert live.celex_for("regulation (ec) 44/2001") == ("celex", "32001R0044")
    assert live.celex_for("32016r0679") == ("celex", "32016R0679")
    assert live.celex_for("ecli:eu:c:2014:317") == ("ecli", "ECLI:EU:C:2014:317")
    assert live.celex_for("c-131/12") == ("case", "62012CJ0131")
    assert live.celex_for("[2019] uksc 41") is None


def test_uk_neutral_citations_become_find_case_law_addresses():
    assert live.find_case_law_path("[2019] uksc 41") == "uksc/2019/41"
    assert live.find_case_law_path("[2020] ewca civ 123") == "ewca/civ/2020/123"
    assert live.find_case_law_path("[2020] ewhc 123 (comm)") == "ewhc/comm/2020/123"
    assert live.find_case_law_path("arbitration act 1996") is None


def test_eu_legislation_carries_its_dates_and_who_repealed_it(store):
    eu = _connector(store, "eu_cellar")
    [gdpr] = eu.resolve(citation_key="regulation (eu) 2016/679")
    assert gdpr.citation == "Regulation (EU) 2016/679" and gdpr.kind is AuthorityKind.LEGISLATION
    assert "applies from 2018-05-25" in gdpr.status_basis
    assert gdpr.status_checked_at is not None, "a live status is confirmed when it is fetched"
    assert any(p.locator.startswith("Art. 17") for p in eu.passages(authority_id=gdpr.authority_id))
    [old] = eu.resolve(citation_key="31995l0046")
    assert old.citation == "Directive 95/46/EC" and old.status is AuthorityStatus.REPEALED
    assert old.treatments[0].by_citation == "32016R0679"
    assert old.treatments[0].effective_date == date(2018, 5, 25)
    then, detail = _assess(eu, old, date(2017, 6, 1))
    assert then is V.VERIFIED and "has since changed (now repealed)" in detail
    now, _ = _assess(eu, old, date(2019, 1, 1))
    assert now is V.FAILED


def test_a_judgment_without_treatment_data_goes_to_a_person(store):
    eu, uk = _connector(store, "eu_cellar"), _connector(store, "uk_open")
    [cjeu] = eu.resolve(citation_key="c-131/12")
    assert cjeu.citation == "ECLI:EU:C:2014:317" and cjeu.status is AuthorityStatus.UNKNOWN
    assert _assess(eu, cjeu, date(2020, 1, 1))[0] is V.INCONCLUSIVE
    [miller] = uk.resolve(citation_key="[2019] uksc 41")
    assert miller.citation == "[2019] UKSC 41" and miller.decision_date == date(2019, 9, 24)
    assert [p.locator for p in uk.passages(authority_id=miller.authority_id)] == ["¶1", "¶2"]
    assert _assess(uk, miller, date(2020, 1, 1))[0] is V.INCONCLUSIVE
    assert "licensed citator" in miller.status_basis


def test_uk_legislation_is_judged_on_the_version_in_force_on_the_relevant_date(store):
    when = date(2017, 6, 1)
    uk = _connector(store, "uk_open", as_of=when)
    versions = uk.resolve(citation_key="arbitration act 1996")
    assert len(versions) == 2
    [then] = [v for v in versions if applicable_on(v, when)]
    assert then.effective_from == date(2016, 1, 1) and then.effective_to == date(2025, 7, 31)
    words = [p.text for p in uk.passages(authority_id=then.authority_id)]
    assert words == ["33 The tribunal shall act fairly and impartially."], "the text of 2017"
    verdict, detail = _assess(uk, then, when)
    assert verdict is V.VERIFIED and "has since changed (now amended)" in detail


def test_a_live_authority_is_fetched_once_then_answered_from_the_store(store):
    fetch = Recorded()
    uk = _connector(store, "uk_open", fetch=fetch)
    uk.resolve(citation_key="[2019] uksc 41")
    asked = len(fetch.calls)
    uk.resolve(citation_key="[2019] uksc 41")
    assert len(fetch.calls) == asked
    assert uk.resolve(citation_key="the unknown act 1996") == []


def test_a_live_source_reaches_only_its_own_hosts_and_nothing_under_hard_offline():
    guard = NetworkGuard(["www.legislation.gov.uk"])
    fetch = live.http_fetch(guard, ("www.legislation.gov.uk",))
    with pytest.raises(ConnectorError, match="not one of this source's hosts"):
        fetch("https://example.com/", "text/html")
    with pytest.raises(ConnectorError, match="not one of this source's hosts"):
        fetch("http://www.legislation.gov.uk/ukpga/1996/23", "text/html")  # not https
    from eli_legal.adapters.local import network

    network.set_hard_offline(True)
    try:
        with pytest.raises(NetworkDenied, match="hard offline is on"):
            fetch("https://www.legislation.gov.uk/ukpga/1996/23/data.xml", "application/xml")
    finally:
        network.set_hard_offline(False)


def test_a_live_source_must_be_read_and_approved_before_any_matter_can_use_it(services):
    sv = services
    sv.users.bootstrap_admin("admin")
    sv.sources.register(live.preset("uk_open", "uk_open"), actor_id="admin")
    from eli_legal.domain.errors import PolicyDenied

    with pytest.raises(PolicyDenied, match="terms reviewed"):
        sv.sources.approve("uk_open", actor_id="admin")
    sv.sources.register(
        replace(live.preset("uk_open", "uk_open"), terms_reviewed=True), actor_id="admin"
    )
    sv.sources.approve("uk_open", actor_id="admin")
    assert {
        "www.legislation.gov.uk",
        "caselaw.nationalarchives.gov.uk",
    } <= sv.ctx.guard.approved_hosts()
    assert "Open Justice Licence" in sv.ctx.sources.get("uk_open").licence
