"""Live connectors to official, openly licensed legal databases.

They follow the legal source standard (``docs/3_architecture/04_source_connector_standard.md``):
each is registered with who publishes it, its licence (to be read before approval), the only
hosts it may contact and what its status answers mean, and it is used only once a named person
approves it and only on matters that list it. Every request goes through the network guard,
which opens one approved host for one request; under hard offline none is made.

An authority is fetched the first time it is needed and stored as a dated source version (its
text, the hash of what was retrieved, when, and its legal status with the date of any repeal),
then answered from the store, exactly like the local corpus, until it is older than the
connector's refresh period. So the current-law check judges a live authority with the same rules
as any other, and a status fetched today is confirmed today.

What each database can and cannot tell, stated as each connector's ``treatment_semantics``:

* **EU (Publications Office CELLAR and EUR-Lex)**: Union legislation and Court of Justice case
  law by CELEX number, ECLI, case number or "Regulation (EU) 2016/679"; whether an act is in
  force, from when, until when, and which act repealed it. It records nothing about a judgment
  being departed from later, so a judgment's status is "unknown" and goes to a person.
* **United Kingdom (legislation.gov.uk and the National Archives' Find Case Law)**: Acts and
  statutory instruments with their sections and whether they are repealed; judgments by neutral
  citation. Find Case Law publishes judgments, not their later treatment, so a judgment's status
  is "unknown" and goes to a person. Case-law treatment needs a licensed citator.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from eli_legal import __version__
from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.adapters.local.parsers import LocalDocumentParser
from eli_legal.adapters.sources.local_corpus import LocalCorpusConnector
from eli_legal.domain.enums import AuthorityKind, AuthorityStatus
from eli_legal.domain.errors import ConnectorError, EliLegalError
from eli_legal.domain.models import Authority, AuthorityPassage, Treatment, utcnow
from eli_legal.legal.authority_status import applicable_on
from eli_legal.legal.citations import normalise_citation
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.legal_sources import ConnectorDeclaration
from eli_legal.security.redaction import content_hash

MAX_BYTES = 12 * 1024 * 1024
REFRESH = timedelta(hours=24)
USER_AGENT = f"ELI-Legal/{__version__} (legal source connector)"
Fetch = Callable[[str, str], bytes]  # (url, accept) -> body


@dataclass(frozen=True, slots=True)
class Found:
    authority: Authority
    passages: list[tuple[str, str]]  # (locator, text)
    keys: list[str]


def http_fetch(guard: NetworkGuard, hosts: Sequence[str]) -> Fetch:
    """Fetch a URL through the network guard, from one of the connector's own hosts only."""

    def fetch(url: str, accept: str) -> bytes:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if urllib.parse.urlsplit(url).scheme != "https" or host not in hosts:
            raise ConnectorError(f"refused: {host or url} is not one of this source's hosts")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with guard.allow(host=host, reason="look up a legal authority"):
                with urllib.request.urlopen(request, timeout=40) as response:  # noqa: S310
                    body = response.read(MAX_BYTES + 1)
        except EliLegalError:
            raise
        except OSError as exc:
            raise ConnectorError(f"{host} could not be reached: {exc}") from exc
        if len(body) > MAX_BYTES:
            raise ConnectorError(f"{host} answered with more than {MAX_BYTES} bytes")
        return bytes(body)

    return fetch


class LiveConnector(LocalCorpusConnector):
    """Answers from the store, fetching from the database what it does not hold or holds too
    old. Searching covers what has been retrieved: these databases offer no open search that a
    deployment could rely on, so research beyond the authorities in play needs a corpus."""

    hosts: tuple[str, ...] = ()

    def __init__(
        self, store: Store, source: RegisteredSource, fetch: Fetch, as_of: date | None = None
    ) -> None:
        super().__init__(store, source)
        self.fetch = fetch
        # The matter's relevant date: a versioned source also fetches the version in force then.
        self.as_of = as_of

    def describe(self) -> ConnectorDeclaration:
        d = super().describe()
        return ConnectorDeclaration(
            **{
                **{f: getattr(d, f) for f in d.__dataclass_fields__},
                "network_required": True,
                "hosts": self.source.hosts or self.hosts,
            }  # fmt: skip
        )

    def resolve(self, *, citation_key: str) -> Sequence[Authority]:
        held = self.store.authorities_by_citation(citation_key, [self.source_id])
        fresh = [a for a in held if utcnow() - a.retrieved_at < REFRESH]
        if fresh and (self.as_of is None or any(applicable_on(a, self.as_of) for a in fresh)):
            return fresh
        found = self.lookup(citation_key)
        if not found:
            return held  # nothing new: what is held, however old, is judged on its own date
        stored = []
        for f in found:
            a = f.authority
            a.source_id, a.retrieved_at, a.status_checked_at = self.source_id, utcnow(), utcnow()
            same = [h for h in held if h.effective_from == a.effective_from]
            if same:
                a.authority_id = same[0].authority_id
            passages = [
                AuthorityPassage(a.authority_id, i, loc, text, content_hash(text))
                for i, (loc, text) in enumerate(f.passages)
            ]
            keys = {normalise_citation(k) for k in [citation_key, a.citation, *f.keys] if k}
            self.store.put_authority(a, passages, sorted(keys))
            stored.append(a)
        return stored

    def lookup(self, citation_key: str) -> list[Found]:  # pragma: no cover - per connector
        raise NotImplementedError


# ── the European Union ───────────────────────────────────────────────────────
_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
_ACT = re.compile(r"^(regulation|directive|decision)\s*(?:\((eu|ec|eec|euratom)\))?\s*(\d+)/(\d+)")
_CASE = re.compile(r"^([ctf])-(\d+)/(\d{2})$")
_CELEX = re.compile(r"^[0-9][0-9]{4}[a-z]{1,2}[0-9]{4}(?:\(\d+\))?$")
_TYPE = {"regulation": "R", "directive": "L", "decision": "D"}


def celex_for(key: str) -> tuple[str, str] | None:
    """('celex', '32016R0679'), ('ecli', 'ECLI:EU:C:2014:317'), ('case', '62012CJ0131')."""
    k = key.strip().lower()
    if k.startswith("ecli:eu:"):
        return "ecli", k.upper()
    if _CELEX.match(k):
        return "celex", k.upper()
    m = _CASE.match(k)
    if m:
        court, number, yy = m.groups()
        full_year = (2000 if int(yy) < 50 else 1900) + int(yy)
        return "case", f"6{full_year}{'CJ' if court == 'c' else 'TJ'}{int(number):04d}"
    m = _ACT.match(k)
    if m:
        kind, series, a, b = m.groups()
        # "(EU) 2016/679" and "Directive 2011/83" put the year first; "(EC) No 44/2001" second.
        year, number = (a, b) if series == "eu" or kind != "regulation" or len(a) == 4 else (b, a)
        if len(year) == 2:
            year = ("20" if int(year) < 50 else "19") + year
        return "celex", f"3{year}{_TYPE[kind]}{int(number):04d}"
    return None


class EuConnector(LiveConnector):
    hosts = ("publications.europa.eu", "eur-lex.europa.eu")

    def _query(self, where: str) -> list[dict[str, str]]:
        query = (
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
            "SELECT ?celex ?date ?inforce ?start ?end ?title ?ecli ?repealer WHERE {\n"
            f"{where}\n"
            "  ?work cdm:resource_legal_id_celex ?celex .\n"
            "  OPTIONAL { ?work cdm:work_date_document ?date }\n"
            "  OPTIONAL { ?work cdm:resource_legal_in-force ?inforce }\n"
            "  OPTIONAL { ?work cdm:resource_legal_date_entry-into-force ?start }\n"
            "  OPTIONAL { ?work cdm:resource_legal_date_end-of-validity ?end }\n"
            "  OPTIONAL { ?work cdm:case-law_ecli ?ecli }\n"
            "  OPTIONAL { ?r cdm:resource_legal_repeals_resource_legal ?work . "
            "?r cdm:resource_legal_id_celex ?repealer }\n"
            "  OPTIONAL { ?e cdm:expression_belongs_to_work ?work ; cdm:expression_uses_language "
            "<http://publications.europa.eu/resource/authority/language/ENG> ; "
            "cdm:expression_title ?title }\n"
            "} LIMIT 20"
        )
        url = f"{_SPARQL}?{urllib.parse.urlencode({'query': query})}"
        data = json.loads(self.fetch(url, "application/sparql-results+json"))
        return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]

    def lookup(self, citation_key: str) -> list[Found]:
        target = celex_for(citation_key)
        if target is None:
            return []
        kind, value = target
        xsd = "<http://www.w3.org/2001/XMLSchema#string>"
        where = (
            f'  ?work cdm:case-law_ecli "{value}"^^{xsd} .'
            if kind == "ecli"
            else f'  ?work cdm:resource_legal_id_celex "{value}"^^{xsd} .'
        )
        rows = self._query(where)
        if not rows:
            return []
        first = rows[0]
        celex = first["celex"]
        is_case = celex[:1] == "6"
        starts = sorted({r["start"] for r in rows if r.get("start")})
        end = next((r["end"] for r in rows if r.get("end")), "")
        repealer = next((r["repealer"] for r in rows if r.get("repealer")), "")
        in_force = next((r["inforce"] for r in rows if r.get("inforce")), "")
        title = next((r["title"] for r in rows if r.get("title")), celex).split("#")[0].strip()
        effective_to = _day(end) if end and not end.startswith("9999") else None
        treatments: list[Treatment] = []
        if is_case:
            status = AuthorityStatus.UNKNOWN
        elif in_force == "1":
            status = AuthorityStatus.IN_FORCE
        else:
            status = AuthorityStatus.REPEALED
            if effective_to:
                treatments.append(
                    Treatment("repealed", effective_to + timedelta(days=1), by_citation=repealer)
                )
        html = self.fetch(
            f"https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}", "text/html"
        )
        ecli = next((r["ecli"] for r in rows if r.get("ecli")), "")
        authority = Authority(
            source_id=self.source_id,
            citation=ecli or _short_title(title) or _act_citation(celex) or celex,
            title=title,
            jurisdiction="EU",
            kind=AuthorityKind.CASE if is_case else AuthorityKind.LEGISLATION,
            uri=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
            content_hash=content_hash(html),
            court="Court of Justice of the European Union" if is_case else "",
            decision_date=_day(first.get("date", "")),
            effective_from=_day(starts[0]) if starts and not is_case else None,
            effective_to=effective_to,
            status=status,
            status_basis=(
                "EUR-Lex records no later treatment of judgments; a person must confirm it"
                if is_case
                else f"CELLAR: in force {'yes' if in_force == '1' else 'no'}"
                + (f"; applies from {starts[-1]}" if len(starts) > 1 else "")
                + (f"; end of validity {end}" if end and not end.startswith("9999") else "")
                + (f"; repealed by CELEX {repealer}" if repealer else "")
            ),
            treatments=treatments,
            aliases=[celex, *([ecli] if ecli else [])],
        )
        return [Found(authority, _eurlex_passages(html), [celex, ecli, citation_key])]


_SHORT = re.compile(
    r"^((?:Council |Commission )?(?:Regulation|Directive|Decision)\s+"
    r"(?:\((?:EU|EC|EEC|Euratom)\)\s+)?(?:No\s+)?\d+/\d+(?:/(?:EU|EC|EEC|Euratom))?)\b"
)


def _short_title(title: str) -> str:
    """'Directive 95/46/EC of the European Parliament …' -> 'Directive 95/46/EC'."""
    m = _SHORT.match(title.strip())
    return m.group(1) if m else ""


def _act_citation(celex: str) -> str:
    m = re.match(r"^3(\d{4})([RLD])(\d{4})$", celex)
    if not m:
        return ""
    year, kind, number = m.groups()
    name = {"R": "Regulation", "L": "Directive", "D": "Decision"}[kind]
    return (
        f"{name} (EU) {year}/{int(number)}" if int(year) >= 2015 else f"{name} {year}/{int(number)}"
    )


def _eurlex_passages(html: bytes) -> list[tuple[str, str]]:
    """EUR-Lex HTML as located passages: each paragraph, located by the article it is in."""
    parsed = LocalDocumentParser().parse("document.html", html)
    out: list[tuple[str, str]] = []
    article = ""
    for segment in parsed.segments:
        heading = re.match(r"^(Article|Art\.)\s+(\d+[a-z]*)\b", segment.text.strip())
        if heading:
            article = f"Art. {heading.group(2)}"
        out.append((f"{article} {segment.locator}".strip() if article else segment.locator,
                    segment.text))  # fmt: skip
    return out[:2000]


# ── the United Kingdom ───────────────────────────────────────────────────────
_NEUTRAL = re.compile(
    r"^\[(\d{4})\]\s+(uksc|ukpc|ukhl|ewca civ|ewca crim|ewhc|ewfc|ukut|ukftt|ewcop)\s+(\d+)"
    r"(?:\s*\((\w+)\))?"
)
_COURT_PATH = {"ewca civ": "ewca/civ", "ewca crim": "ewca/crim"}
_AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
_LEG_NS = "{http://www.legislation.gov.uk/namespaces/legislation}"


def find_case_law_path(key: str) -> str | None:
    """'[2019] uksc 41' -> 'uksc/2019/41'; '[2020] ewhc 123 (comm)' -> 'ewhc/comm/2020/123'."""
    m = _NEUTRAL.match(key.strip().lower())
    if not m:
        return None
    year, court, number, division = m.groups()
    base = _COURT_PATH.get(court, court)
    if division and court in ("ewhc", "ukut", "ukftt"):
        base = f"{base}/{division}"
    return f"{base}/{year}/{number}"


class UkConnector(LiveConnector):
    hosts = ("www.legislation.gov.uk", "caselaw.nationalarchives.gov.uk")

    def lookup(self, citation_key: str) -> list[Found]:
        path = find_case_law_path(citation_key)
        if path is not None:
            judgment = self._judgment(path, citation_key)
            return [judgment] if judgment else []
        ident = self._legislation_id(citation_key)
        if ident is None:
            return []
        current = self._legislation(ident, citation_key)
        found = [current]
        start = current.authority.effective_from
        if self.as_of is not None and start is not None and self.as_of < start:
            # The text in force on the relevant date, as its own dated version, so both the
            # status and the words checked are the ones that applied then.
            then = self._legislation(ident, citation_key, as_of=self.as_of)
            a = then.authority
            a.effective_to = start - timedelta(days=1)
            if current.authority.status is AuthorityStatus.REPEALED:
                a.treatments = list(current.authority.treatments)
            else:
                a.treatments = [Treatment("amended", start, note="a later version is in force")]
            a.status = AuthorityStatus.AMENDED
            a.status_basis += f"; superseded by the version valid from {start.isoformat()}"
            found.append(then)
        return found

    def _judgment(self, path: str, key: str) -> Found | None:
        try:
            raw = self.fetch(
                f"https://caselaw.nationalarchives.gov.uk/{path}/data.xml", "application/xml"
            )
        except ConnectorError:
            return None
        root = ET.fromstring(raw)
        name = root.find(f".//{_AKN}FRBRWork/{_AKN}FRBRname")
        when = root.find(f".//{_AKN}FRBRWork/{_AKN}FRBRdate")
        passages: list[tuple[str, str]] = []
        for para in root.iter(f"{_AKN}paragraph"):
            text = " ".join(" ".join(para.itertext()).split())
            if text:
                passages.append(
                    (f"¶{para.get('eId', '').removeprefix('para_') or len(passages) + 1}", text)
                )
        authority = Authority(
            source_id=self.source_id,
            citation=_neutral_display(key),
            title=name.get("value", "") if name is not None else key,
            jurisdiction="GB-EAW",
            kind=AuthorityKind.CASE,
            uri=f"https://caselaw.nationalarchives.gov.uk/{path}",
            content_hash=content_hash(raw),
            decision_date=_day(when.get("date", "")) if when is not None else None,
            status=AuthorityStatus.UNKNOWN,
            status_basis="Find Case Law publishes judgments, not their later treatment; a "
            "person (or a licensed citator) must confirm it is still good law",
        )
        return Found(authority, passages[:2000], [key])

    def _legislation(self, ident: str, key: str, as_of: date | None = None) -> Found:
        point = f"/{as_of.isoformat()}" if as_of else ""
        raw = self.fetch(
            f"https://www.legislation.gov.uk/{ident}{point}/data.xml", "application/xml"
        )
        root = ET.fromstring(raw)
        title_el = root.find(".//{http://purl.org/dc/elements/1.1/}title")
        valid_el = root.find(".//{http://purl.org/dc/terms/}valid")
        sections = list(root.iter(f"{_LEG_NS}P1"))
        repealed = [p for p in sections if p.get("Status") == "Repealed"]
        passages = []
        for p in sections:
            number = p.findtext(f"{_LEG_NS}Pnumber") or p.get("id", "").removeprefix("section-")
            text = " ".join(" ".join(p.itertext()).split())
            if text:
                passages.append((f"s.{number}", text))
        whole_repeal = bool(sections) and len(repealed) == len(sections)
        dates = [d for p in repealed if (d := _day(p.get("RestrictStartDate", ""))) is not None]
        repeal_date = min(dates) if dates else None
        title = title_el.text if title_el is not None and title_el.text else key
        authority = Authority(
            source_id=self.source_id,
            citation=title,
            title=title,
            jurisdiction="GB-EAW",
            kind=AuthorityKind.LEGISLATION,
            uri=f"https://www.legislation.gov.uk/{ident}{point}",
            content_hash=content_hash(raw),
            effective_from=_day(valid_el.text or "") if valid_el is not None else None,
            status=AuthorityStatus.REPEALED if whole_repeal else AuthorityStatus.IN_FORCE,
            status_basis=f"legislation.gov.uk: the version valid from "
            f"{valid_el.text if valid_el is not None else 'an unstated date'}"
            + (f"; {len(repealed)} of {len(sections)} sections repealed" if repealed else ""),
            treatments=[Treatment("repealed", repeal_date)] if whole_repeal and repeal_date else [],
            aliases=[ident],
        )
        return Found(authority, passages[:3000], [key, title])

    def _legislation_id(self, key: str) -> str | None:
        k = key.strip().lower()
        si = re.match(r"^(?:si|s\.i\.)\s*(\d{4})/(\d+)$", k)
        if si:
            return f"uksi/{si.group(1)}/{si.group(2)}"
        act = re.match(r"^(.+?\bact)\s+(\d{4})$", k)
        if not act:
            return None
        title, year = act.groups()
        feed = self.fetch(
            f"https://www.legislation.gov.uk/all/{year}/data.feed?"
            + urllib.parse.urlencode({"title": title}),
            "application/atom+xml",
        )
        atom = "{http://www.w3.org/2005/Atom}"
        wanted = f"{title} {year}".lower()
        for entry in ET.fromstring(feed).iter(f"{atom}entry"):
            if (entry.findtext(f"{atom}title") or "").strip().lower() == wanted:
                ident = (entry.findtext(f"{atom}id") or "").split("/id/", 1)[-1]
                return ident or None
        return None


def _neutral_display(key: str) -> str:
    m = _NEUTRAL.match(key.strip().lower())
    if not m:
        return key
    year, court, number, division = m.groups()
    return f"[{year}] {court.upper().replace('CIV', 'Civ').replace('CRIM', 'Crim')} {number}" + (
        f" ({division.capitalize()})" if division else ""
    )


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


# ── registration ─────────────────────────────────────────────────────────────
CONNECTORS: dict[str, type[LiveConnector]] = {"eu_cellar": EuConnector, "uk_open": UkConnector}

PRESETS: dict[str, dict[str, Any]] = {
    "eu_cellar": {
        "name": "EU law (Publications Office CELLAR and EUR-Lex)",
        "jurisdictions": frozenset({"EU"}),
        "source_types": ("legislation", "case"),
        "authority_owner": "Publications Office of the European Union",
        "licence": "EUR-Lex content may be reused under Commission Decision 2011/833/EU, "
        "acknowledging the source; check the legal notice before approval",
        "hosts": ("publications.europa.eu", "eur-lex.europa.eu"),
        "freshness": "Live: fetched when first needed and again after 24 hours",
        "treatment_semantics": "Legislation: in force, entry into force, end of validity and the "
        "repealing act, as CELLAR records them. Judgments: no later treatment is recorded, so "
        "their status is unknown and goes to a person.",
        "authoritative_for": ("celex", "eu_act_new", "eu_act_old", "ecli"),
        "inspection": "Each authority links to its EUR-Lex page",
    },
    "uk_open": {
        "name": "UK law (legislation.gov.uk and Find Case Law)",
        "jurisdictions": frozenset({"GB-EAW"}),
        "source_types": ("legislation", "case"),
        "authority_owner": "The National Archives (UK)",
        "licence": "Legislation: Open Government Licence v3.0. Judgments: Open Justice Licence, "
        "under which computational analysis needs a transactional licence from the National "
        "Archives; obtain one before approving this source for that use",
        "hosts": ("www.legislation.gov.uk", "caselaw.nationalarchives.gov.uk"),
        "freshness": "Live: fetched when first needed and again after 24 hours",
        "treatment_semantics": "Legislation: the current version, its date, and whether its "
        "sections are repealed. Judgments: published text only, no later treatment, so their "
        "status is unknown and goes to a person.",
        # Not complete for anything a UK matter may cite (an Act of another legal system shares
        # the citation form), so "not found" goes to a person rather than failing.
        "authoritative_for": (),
        "inspection": "Each authority links to its page on legislation.gov.uk or Find Case Law",
    },
}


def preset(kind: str, source_id: str) -> RegisteredSource:
    """A live source ready to register. Its terms are not marked as read: a person must read
    them and say so before it can be approved."""
    if kind not in PRESETS:
        raise ConnectorError(f"no live connector {kind!r}; one of {', '.join(PRESETS)}")
    return RegisteredSource(
        source_id=source_id, connector=kind, network_required=True, **PRESETS[kind]
    )


def connector_for(
    store: Store, source: RegisteredSource, guard: NetworkGuard, as_of: date | None = None
) -> LiveConnector:
    cls = CONNECTORS[source.connector]
    return cls(store, source, http_fetch(guard, source.hosts or cls.hosts), as_of)
