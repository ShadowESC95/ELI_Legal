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
from eli_legal.domain.models import utcnow
from eli_legal.legal.authority_status import applicable_on, status_at
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
CITING = _sparql(
    [{"celex": "62022CJ0769", "date": "2026-04-21"}, {"celex": "62025CC0205", "date": "2026-04-16"},
     {"celex": "62022CJ0621", "date": "2024-10-04"}]
)  # fmt: skip
BRUSSELS = _sparql(
    [{"celex": "32012R1215", "date": "2012-12-12", "inforce": "1", "start": "2013-01-09",
      "end": "9999-12-31", "title": "Regulation (EU) No 1215/2012 of the European Parliament and of the Council"},
     {"celex": "32012R1215", "start": "2015-01-10"}]
)  # fmt: skip
CONSOLIDATED = _sparql([{"celex": "02012R1215-20150110"}, {"celex": "02012R1215-20150226"}])
AMENDERS = _sparql([{"amender": "32014R0542"}, {"amender": "32015R0281"}])
# The Directive's consolidated versions: one of 2003, and one dated the day of its repeal, which
# records the repeal rather than a text in force.
DIRECTIVE_CONSOLIDATED = _sparql(
    [{"celex": "01995L0046-20031120"}, {"celex": "01995L0046-20180525"}]
)
JUDGMENT = _sparql(
    [{"celex": "62012CJ0131", "date": "2014-05-13", "ecli": "ECLI:EU:C:2014:317",
      "title": "Judgment of the Court (Grand Chamber), 13 May 2014.#Google Spain SL"}]
)  # fmt: skip
# EUR-Lex prints an act as a run of paragraphs: the citations, "Whereas:", each recital's number
# then its words, the enacting formula, chapter headings, each article's heading and title, its
# numbered paragraphs, each point's letter then its words, the signatures and the footnotes.
EURLEX = """<html><body><p>4.5.2016</p><p>EN</p><p>Official Journal of the European Union</p>
<p>THE EUROPEAN PARLIAMENT AND THE COUNCIL OF THE EUROPEAN UNION,</p>
<p>Having regard to the Treaty on the Functioning of the European Union,</p>
<p>Whereas:</p><p>(65)</p><p>A data subject should have the right to have personal data concerning him or her
rectified and a ‘right to be forgotten’.</p>
<p>HAVE ADOPTED THIS REGULATION:</p><p>CHAPTER III</p><p>Rights of the data subject</p>
<p>Article 4</p><p>Definitions</p><p>For the purposes of this Regulation:</p>
<p>(1)</p><p>‘personal data’ means any information relating to an identified or identifiable natural person;</p>
<p>(2)</p><p>‘processing’ means any operation performed on personal data;</p>
<p>Article 17</p><p>Right to erasure (‘right to be forgotten’)</p>
<p>1. The data subject shall have the right to obtain from the controller the erasure of personal
data concerning him or her without undue delay where one of the following grounds applies:</p>
<p>(a)</p><p>the personal data are no longer necessary in relation to the purposes for which they were collected;</p>
<p>(b)</p><p>the data subject withdraws consent.</p>
<p>2. Where the controller has made the personal data public, it shall take reasonable steps. Article 18</p>
<p>The data subject shall have the right to obtain restriction of processing.</p>
<p>Done at Brussels, 27 April 2016.</p><p>For the European Parliament</p><p>The President</p>
<p>(1) OJ C 229, 31.7.2012, p. 90.</p></body></html>""".encode()
# A judgment: the parties, then "Judgment", each paragraph's number then its words, under the
# headings of the judgment, and the ruling.
CURIA = b"""<html><body><p>JUDGMENT OF THE COURT (Grand Chamber)</p><p>13 May 2014</p>
<p>gives the following</p><p>Judgment</p><p>1</p><p>This request for a preliminary ruling concerns
the interpretation of Directive 95/46.</p><p>Legal context</p><p>European Union law</p><p>3</p>
<p>Directive 95/46 has the object of protecting the fundamental rights of natural persons.</p>
<p>On those grounds, the Court (Grand Chamber) hereby rules:</p><p>1. Article 2(b) of Directive
95/46 is to be interpreted as meaning that the activity of a search engine is processing.</p>
<p>[Signatures]</p></body></html>"""
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


REPEAL_NOTE = "S. 25 repealed (31.3.2003) by The Example (Costs) Act 2002 (c. 1), s. 1"


def _act(valid: str, duty: str, repeal_note: str = REPEAL_NOTE) -> bytes:
    """legislation.gov.uk's CLML: a section under its heading with numbered subsections, a
    schedule paragraph quoting the text it substitutes, and a schedule of plain paragraphs."""
    uri = "http://www.legislation.gov.uk/ukpga/1996/23"
    return f"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dct="http://purl.org/dc/terms/">
<ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata"><dc:title>Arbitration Act 1996</dc:title><dct:valid>{valid}</dct:valid></ukm:Metadata>
<Primary><Body><P1group><Title>General duty of the tribunal.</Title>
<P1 id="section-33" DocumentURI="{uri}/section/33"><Pnumber>33</Pnumber><P1para>
<P2 id="section-33-1"><Pnumber>1</Pnumber><P2para><Text>{duty}</Text></P2para></P2>
<P2 id="section-33-2"><Pnumber>2</Pnumber><P2para><Text>The tribunal shall comply with that duty.</Text></P2para></P2>
</P1para></P1></P1group>
<P1group Status="Repealed" RestrictStartDate="1997-01-31"><Title>Power to award costs.<CommentaryRef Ref="c25"/></Title>
<P1 id="section-25" DocumentURI="{uri}/section/25"><Pnumber>25</Pnumber><P1para><Text>. . . . . . .</Text></P1para></P1></P1group>
<Schedules><Schedule id="schedule-1" DocumentURI="{uri}/schedule/1"><Number>Schedule 1</Number>
<ScheduleBody><Pblock><Title>Section 9: stay of legal proceedings</Title>
<P1 id="schedule-1-paragraph-2" DocumentURI="{uri}/schedule/1/paragraph/2"><Pnumber>2</Pnumber>
<P1para><Text>For section 9 substitute:</Text><BlockAmendment><P1><Pnumber>9</Pnumber>
<P1para><Text>A party may apply for a stay.</Text></P1para></P1></BlockAmendment></P1para></P1>
</Pblock></ScheduleBody></Schedule>
<Schedule id="schedule-2" DocumentURI="{uri}/schedule/2"><Number>Schedule 2</Number>
<TitleBlock><Title>Guidelines</Title></TitleBlock><ScheduleBody><P1group><Title>Matters</Title>
<P><Text>The matters to which regard is to be had are:</Text></P>
<P3><Pnumber>a</Pnumber><P3para><Text>the strength of the parties' bargaining positions;</Text></P3para></P3>
</P1group></ScheduleBody></Schedule></Schedules>
</Body></Primary>
<Commentaries><Commentary id="c25"><Para><Text>{repeal_note}</Text></Para></Commentary></Commentaries>
</Legislation>""".encode()


RESPONSES = {
    "resource/celex/32016R0679": EURLEX,
    "resource/celex/31995L0046": EURLEX,
    "resource/celex/01995L0046-20031120": b"<html><body><p>HAVE ADOPTED THIS DIRECTIVE:</p><p>Article 12</p><p>Right of access</p><p>1. Member States shall guarantee every data subject the right to obtain from the controller confirmation.</p></body></html>",
    "resource/celex/62012CJ0131": CURIA,
    "resource/celex/32012R1215": b"<html><body><p>HAVE ADOPTED THIS REGULATION:</p><p>Article 71</p><p>1. This Regulation shall not affect conventions.</p></body></html>",
    "resource/celex/02012R1215-20150110": "<html><body><p>▼B</p><p>Article 71</p><p>1. This Regulation shall not affect conventions.</p><p>►M1</p><p>Article 71a</p><p>1. A court common to several Member States shall be deemed a court of a Member State.</p></body></html>".encode(),
    "resource/celex/02012R1215-20150226": "<html><body><p>▼B</p><p>Article 71</p><p>1. This Regulation shall not affect conventions.</p><p>►M1</p><p>Article 71a</p><p>1. A court common to several Member States shall be deemed a court of a Member State.</p><p>Article 71b</p><p>1. The jurisdiction of a common court shall be determined as follows.</p></body></html>".encode(),
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
                ("work_cites_work", CITING),
                ("resource_legal_amends", AMENDERS),
                ("02012R1215-", CONSOLIDATED),
                ("01995L0046-", DIRECTIVE_CONSOLIDATED),
                ("32012R1215", BRUSSELS),
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


def test_every_way_of_citing_an_eu_act_finds_its_number():
    for cited, celex in (
        ("regulation (eu) no 1215/2012", "32012R1215"),  # before 2015: number, then year
        ("regulation (eu) 1215/2012", "32012R1215"),
        ("regulation (ec) no 593/2008", "32008R0593"),
        ("council directive 85/374/eec", "31985L0374"),
        ("regulation (eec) no 1408/71", "31971R1408"),
        ("directive (eu) 2019/770", "32019L0770"),
        ("commission implementing regulation (eu) 2021/914", "32021R0914"),
    ):
        assert live.celex_for(cited) == ("celex", celex), cited


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
    where = {p.locator: p for p in eu.passages(authority_id=gdpr.authority_id)}
    assert list(where) == ["Recital 65", "Art. 4", "Art. 4(1)", "Art. 4(2)", "Art. 17(1)",
                           "Art. 17(2)", "Art. 18"], "signatures and footnotes are left out"  # fmt: skip
    erasure = where["Art. 17(1)"]
    assert erasure.heading == "Right to erasure (‘right to be forgotten’)"
    assert erasure.text.splitlines()[1:] == [
        "(a) the personal data are no longer necessary in relation to the purposes for which they "
        "were collected;",
        "(b) the data subject withdraws consent.",
    ], "a point's letter is joined to its words"
    assert where["Art. 4(1)"].text.startswith("(1) ‘personal data’ means")
    assert where["Art. 17(2)"].text.endswith("reasonable steps."), "a heading printed at the end"
    assert where["Art. 18"].text.startswith("The data subject shall have the right to obtain")
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
    assert (
        "cited by 2 later judgment(s) and 1 Advocate General's opinion(s), most recently "
        "C-769/22 (2026-04-21), C-621/22 (2024-10-04); read them to confirm it was not departed"
        in cjeu.status_basis
    ), "where the person confirming its standing looks first"
    assert live.case_number("62012CJ0131") == "C-131/12" and live.case_number("62019TJ0012") == (
        "T-12/19"
    )
    paragraphs = {p.locator: p for p in eu.passages(authority_id=cjeu.authority_id)}
    assert list(paragraphs) == ["¶1", "¶3", "Ruling"]
    assert paragraphs["¶3"].heading == "European Union law"
    assert "search engine is processing" in paragraphs["Ruling"].text
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
    passages = {p.locator: p for p in uk.passages(authority_id=then.authority_id)}
    assert list(passages) == ["s.33", "s.25", "Sch. 1 para. 2", "Sch. 2"], (
        "a quoted provision is no section"
    )
    assert passages["s.33"].heading == "General duty of the tribunal."
    assert passages["s.33"].text.splitlines() == [
        "(1) The tribunal shall act fairly and impartially.",
        "(2) The tribunal shall comply with that duty.",
    ], "the text of 2017, numbered as printed"
    quoting = passages["Sch. 1 para. 2"].text
    assert quoting == "For section 9 substitute:\n9 A party may apply for a stay.", "own line"
    assert passages["Sch. 2"].heading == "Guidelines"
    assert "(a) the strength of the parties' bargaining positions;" in passages["Sch. 2"].text
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


def _relying_on(locator: str, *, party_says: str = ""):
    from eli_legal.domain.enums import ClaimKind
    from eli_legal.domain.models import Claim, EvidenceLink

    if party_says:
        return Claim(matter_id="m", run_id="r", text=party_says, kind=ClaimKind.PARTY_AUTHORITY)
    link = EvidenceLink(target_type="authority", target_id="a", locator=locator)
    return Claim(matter_id="m", run_id="r", text="…", kind=ClaimKind.LEGAL_PROPOSITION,
                 evidence=[link])  # fmt: skip


def test_a_repealed_section_of_an_act_in_force_is_not_treated_as_current(store):
    """legislation.gov.uk marks a repealed section on the group around it, with its date. The
    Act stays in force; the section does not, and a finding resting on it fails."""
    version = _act("2000-01-01", "The tribunal shall act fairly and impartially.")
    uk = _connector(store, "uk_open", fetch=lambda url, accept: version)
    act = uk._legislation("ukpga/1996/23", "arbitration act 1996").authority
    act.status_checked_at = utcnow()
    assert act.status is AuthorityStatus.IN_FORCE, "one section repealed is not the Act repealed"
    [repeal] = [t for t in act.treatments if t.provision]
    assert (repeal.provision, repeal.effective_date) == ("s.25", date(2003, 3, 31)), (
        "the date of the repeal is in its annotation, not the date its text began (1997)"
    )
    assert repeal.by_citation == "The Example (Costs) Act 2002"
    assert "1 of 3 provisions repealed: s.25" in act.status_basis
    assert status_at(act, date(2017, 6, 1)) is AuthorityStatus.IN_FORCE
    citator = CurrentLawCitator({"uk_open": uk})
    pack = PACKS.get("GB-EAW")

    def verdict(claim, when):
        r = citator.verify(claim, act, pack=pack, relevant_date=when)
        return r.status, r.detail

    status, detail = verdict(_relying_on("s.25(1)"), date(2017, 6, 1))
    assert (
        status is V.FAILED and "s.25 of Arbitration Act 1996 was repealed on 2003-03-31" in detail
    )
    status, detail = verdict(_relying_on("s.25"), date(2001, 1, 1))
    assert (
        status is V.VERIFIED
        and "s.25 has since been repealed (2003-03-31 by The Example (Costs) Act 2002)" in detail
    )
    assert verdict(_relying_on("s.33(1)"), date(2017, 6, 1))[0] is V.VERIFIED, "the rest stands"
    party = _relying_on("", party_says="The tribunal may award costs under section 25 of the Act.")
    assert verdict(party, date(2017, 6, 1))[0] is V.FAILED, "a section named by a party too"


def test_a_repeal_without_a_date_is_judged_by_the_version_and_otherwise_goes_to_a_person(store):
    """No annotation dates it: the provision was repealed on or before the date of the version
    that shows it repealed. After that date it fails; before it, a person must say."""
    version = _act("2020-01-01", "Fairly.", repeal_note="")
    uk = _connector(store, "uk_open", fetch=lambda url, accept: version)
    act = uk._legislation("ukpga/1996/23", "arbitration act 1996").authority
    act.status_checked_at = utcnow()
    citator = CurrentLawCitator({"uk_open": uk})
    later = citator.verify(_relying_on("s.25"), act, pack=PACKS.get("GB-EAW"),
                           relevant_date=date(2021, 1, 1))  # fmt: skip
    assert later.status is V.FAILED and "on or before 2020-01-01" in later.detail
    act.effective_from = date(2016, 1, 1)  # the version also applies earlier
    earlier = citator.verify(_relying_on("s.25"), act, pack=PACKS.get("GB-EAW"),
                             relevant_date=date(2017, 6, 1))  # fmt: skip
    assert earlier.status is V.CONFLICT and "a person must confirm" in earlier.detail


def test_a_repeal_for_another_part_of_the_kingdom_leaves_the_provision_in_force_here(store):
    for note, expected in (
        (
            "S. 25 repealed (S.) (25.9.1991) by Age of Legal Capacity (Scotland) Act 1991 (c. 50)",
            None,
        ),
        ("S. 25 repealed (E.) (1.4.2010) by The Example Act 2009 (c. 9)", V.CONFLICT),
        (
            "S. 25 omitted (E.W.) (1.10.2015) by virtue of Consumer Rights Act 2015 (c. 15)",
            V.FAILED,
        ),
    ):
        uk = _connector(
            store, "uk_open", fetch=lambda url, accept, n=note: _act("2000-01-01", "F.", n)
        )
        act = uk._legislation("ukpga/1996/23", "arbitration act 1996").authority
        act.status_checked_at = utcnow()
        repeals = [t for t in act.treatments if t.provision]
        if expected is None:
            assert not repeals, "a repeal for Scotland only does not touch England and Wales"
            continue
        result = CurrentLawCitator({"uk_open": uk}).verify(
            _relying_on("s.25"), act, pack=PACKS.get("GB-EAW"), relevant_date=date(2020, 1, 1)
        )
        assert result.status is expected, (note, result.detail)


def test_a_section_left_as_dots_is_a_repealed_section(store):
    xml = (
        _act("2000-01-01", "F.")
        .replace(
            b'<P1group Status="Repealed" RestrictStartDate="1997-01-31">',
            b"<P1group>",
        )
        .replace(
            b"<P1para><Text>. . . . . . .</Text></P1para>",
            b'<P1para><Text>. . . . . . .<CommentaryRef Ref="c25"/></Text></P1para>',
        )
    )
    uk = _connector(store, "uk_open", fetch=lambda url, accept: xml)
    act = uk._legislation("ukpga/1996/23", "arbitration act 1996").authority
    [repeal] = [t for t in act.treatments if t.provision]
    assert (repeal.provision, repeal.effective_date) == ("s.25", date(2003, 3, 31))


def test_an_act_with_every_provision_repealed_is_repealed_when_the_last_one_was(store):
    xml = b"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dct="http://purl.org/dc/terms/">
<ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata"><dc:title>Old Act 1990</dc:title><dct:valid>2020-01-01</dct:valid></ukm:Metadata>
<Primary><Body>
<P1group Status="Repealed"><Title>One<CommentaryRef Ref="c1"/></Title><P1 id="section-1" DocumentURI="http://www.legislation.gov.uk/ukpga/1990/1/section/1"><Pnumber>1</Pnumber><P1para><Text>. . .</Text></P1para></P1></P1group>
<P1group Status="Repealed"><Title>Two<CommentaryRef Ref="c2"/></Title><P1 id="section-2" DocumentURI="http://www.legislation.gov.uk/ukpga/1990/1/section/2"><Pnumber>2</Pnumber><P1para><Text>. . .</Text></P1para></P1></P1group>
</Body></Primary><Commentaries>
<Commentary id="c1"><Para><Text>S. 1 repealed (1.1.2005) by Newer Act 2004 (c. 4)</Text></Para></Commentary>
<Commentary id="c2"><Para><Text>S. 2 repealed (30.6.2012) by Newest Act 2012 (c. 2)</Text></Para></Commentary>
</Commentaries></Legislation>"""
    uk = _connector(store, "uk_open", fetch=lambda url, accept: xml)
    act = uk._legislation("ukpga/1990/1", "old act 1990").authority
    assert act.status is AuthorityStatus.REPEALED
    [whole] = [t for t in act.treatments if not t.provision]
    assert whole.effective_date == date(2012, 6, 30), "the Act went with its last provision"


def test_an_amended_eu_act_is_judged_on_the_consolidated_version_in_force_on_the_date(store):
    """The act as published is the act until its first consolidated version; each consolidated
    version holds the text in force from its date until the next. The latest is the act today."""
    today_only = _connector(store, "eu_cellar")
    [now] = today_only.resolve(citation_key="regulation (eu) no 1215/2012")
    assert now.effective_from == date(2015, 2, 26) and now.status is AuthorityStatus.IN_FORCE
    assert "consolidated version of 2015-02-26" in now.status_basis
    assert "documentation only" in now.status_basis, "the Official Journal text is authentic"
    passages = {p.locator: p.text for p in today_only.passages(authority_id=now.authority_id)}
    assert "Art. 71b(1)" in passages and not any(
        "\u25ba" in t or "\u25bc" in t for t in passages.values()
    )
    in_2014 = _connector(store, "eu_cellar", as_of=date(2014, 6, 1))
    versions = in_2014.resolve(citation_key="regulation (eu) no 1215/2012")
    [then] = [v for v in versions if applicable_on(v, date(2014, 6, 1))]
    assert then.effective_to == date(2015, 1, 9) and "as published" in then.status_basis
    assert [t.by_citation for t in then.treatments] == ["32014R0542, 32015R0281"]
    held = {p.locator for p in in_2014.passages(authority_id=then.authority_id)}
    assert held == {"Art. 71(1)"}, "the text of 2014: no Article 71a yet"
    verdict, detail = _assess(in_2014, then, date(2014, 6, 1))
    assert verdict is V.VERIFIED and "has since changed (now amended)" in detail
    in_jan_2015 = _connector(store, "eu_cellar", as_of=date(2015, 2, 1))
    [middle] = [v for v in in_jan_2015.resolve(citation_key="regulation (eu) no 1215/2012")
                if applicable_on(v, date(2015, 2, 1))]  # fmt: skip
    assert (middle.effective_from, middle.effective_to) == (date(2015, 1, 10), date(2015, 2, 25))


def test_a_redirect_stays_on_the_host_and_on_https_and_an_empty_answer_is_said_plainly():
    upgraded = live.safe_redirect(
        "publications.europa.eu", "http://publications.europa.eu/resource/cellar/x/DOC_1"
    )
    assert upgraded == "https://publications.europa.eu/resource/cellar/x/DOC_1", "never in clear"
    with pytest.raises(ConnectorError, match="another host"):
        live.safe_redirect("publications.europa.eu", "https://example.com/elsewhere")
    with pytest.raises(ConnectorError, match="did not answer with the document"):
        live.answered("eur-lex.europa.eu", 202, b"")
    assert live.answered("publications.europa.eu", 200, b"<html/>") == b"<html/>"


def test_a_consolidated_eu_text_keeps_its_recitals_and_no_version_outlives_the_act(store):
    """A consolidated text leaves the recitals out; they are cited and never amended, so they
    come from the act as published. A consolidated "version" dated the day the act was repealed
    records the repeal, not a text in force."""
    eu = _connector(store, "eu_cellar", as_of=date(2017, 6, 1))
    versions = eu.resolve(citation_key="directive 95/46/ec")
    assert [(v.effective_from, v.effective_to) for v in versions] == [
        (date(2003, 11, 20), date(2018, 5, 24))
    ]
    [act] = versions
    assert act.status is AuthorityStatus.REPEALED
    held = [p.locator for p in eu.passages(authority_id=act.authority_id)]
    assert "Recital 65" in held and "Art. 12(1)" in held
    then, detail = _assess(eu, act, date(2017, 6, 1))
    assert then is V.VERIFIED and "now repealed" in detail
    assert _assess(eu, act, date(2019, 1, 1))[0] is V.FAILED
