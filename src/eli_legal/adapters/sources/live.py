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
from eli_legal.legal.current_law_citator import (
    REPEALED_BY_VERSION,
    REPEALED_IN_PART,
    UNDATED_REPEAL,
)
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
    passages: list[Located]
    keys: list[str]


Located = tuple[str, str, str]  # (locator, text, heading)


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to the same host, and only over https: a plain http address
    given in a redirect (as CELLAR gives) is asked for over https instead, never in clear."""

    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return super().redirect_request(
            req, fp, code, msg, headers, safe_redirect(self.host, newurl)
        )


def safe_redirect(host: str, newurl: str) -> str:
    parts = urllib.parse.urlsplit(newurl)
    target = (parts.hostname or "").lower()
    if target != host:
        raise ConnectorError(f"refused: {host} redirected to {target or newurl}, another host")
    if parts.scheme not in ("http", "https"):
        raise ConnectorError(f"refused: {host} redirected to a {parts.scheme} address")
    return urllib.parse.urlunsplit(("https", target, parts.path, parts.query, parts.fragment))


def answered(host: str, status: int, body: bytes) -> bytes:
    """The body of an answer that holds a document; anything else is said plainly."""
    if status == 202 or not body:
        raise ConnectorError(
            f"{host} did not answer with the document (HTTP {status}, {len(body)} bytes): it may "
            "be limiting automated requests; try again later"
        )
    if len(body) > MAX_BYTES:
        raise ConnectorError(f"{host} answered with more than {MAX_BYTES} bytes")
    return body


def http_fetch(guard: NetworkGuard, hosts: Sequence[str]) -> Fetch:
    """Fetch a URL through the network guard, from one of the connector's own hosts only, over
    https only, redirects included."""

    def fetch(url: str, accept: str) -> bytes:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if urllib.parse.urlsplit(url).scheme != "https" or host not in hosts:
            raise ConnectorError(f"refused: {host or url} is not one of this source's hosts")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "eng, en"},
        )
        opener = urllib.request.build_opener(_SameHostRedirect(host))
        try:
            with guard.allow(host=host, reason="look up a legal authority"):
                with opener.open(request, timeout=60) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    body = response.read(MAX_BYTES + 1)
        except EliLegalError:
            raise
        except OSError as exc:
            raise ConnectorError(f"{host} could not be reached: {exc}") from exc
        return bytes(answered(host, status, bytes(body)))

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
                AuthorityPassage(a.authority_id, i, loc, text, content_hash(text), heading=head)
                for i, (loc, text, head) in enumerate(f.passages)
            ]
            keys = {normalise_citation(k) for k in [citation_key, a.citation, *f.keys] if k}
            self.store.put_authority(a, passages, sorted(keys))
            stored.append(a)
        return stored

    def lookup(self, citation_key: str) -> list[Found]:  # pragma: no cover - per connector
        raise NotImplementedError


# ── the European Union ───────────────────────────────────────────────────────
_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
_ACT = re.compile(
    r"^(?:(?:council|commission)\s+)?(?:(?:implementing|delegated)\s+)?"
    r"(regulation|directive|decision)\s*(?:\((eu|ec|eec|euratom)\))?\s*(?:no\.?\s*)?(\d+)/(\d+)"
)
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
        kind, _series, a, b = m.groups()
        year, number = _year_and_number(kind, a, b)
        if len(year) == 2:
            year = ("20" if int(year) < 50 else "19") + year
        return "celex", f"3{year}{_TYPE[kind]}{int(number):04d}"
    return None


def _year_and_number(kind: str, a: str, b: str) -> tuple[str, str]:
    """Which half of "2016/679", "1215/2012", "44/2001" or "95/46" is the year. Since 2015 every
    act puts the year first; before, a regulation put it second and a directive or decision
    first."""

    def year_like(x: str) -> bool:
        return len(x) == 4 and 1950 <= int(x) <= 2100

    if year_like(a) != year_like(b):
        return (a, b) if year_like(a) else (b, a)
    if year_like(a):
        return (a, b) if int(a) >= 2015 else (b, a)
    return (b, a) if kind == "regulation" else (a, b)


def case_number(celex: str) -> str:
    """'62022CJ0769' -> 'C-769/22'; 'T' for the General Court."""
    m = re.match(r"^6(\d{4})(CJ|TJ|CC|CO|TO)(\d{4})", celex)
    if not m:
        return celex
    year, court, number = m.groups()
    return f"{'T' if court.startswith('T') else 'C'}-{int(number)}/{year[2:]}"


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

    def _cited_by(self, celex: str) -> str:
        """The later judgments and opinions of the Court that cite this one, as CELLAR records
        them: where a person confirming its standing looks first. Whether each followed it or
        departed from it is not recorded; nothing here changes the status."""
        query = (
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
            "SELECT DISTINCT ?celex ?date WHERE {\n"
            f'  ?work cdm:resource_legal_id_celex "{celex}"^^'
            "<http://www.w3.org/2001/XMLSchema#string> .\n"
            "  ?citing cdm:work_cites_work ?work .\n"
            "  ?citing cdm:resource_legal_id_celex ?celex .\n"
            "  OPTIONAL { ?citing cdm:work_date_document ?date }\n"
            '  FILTER(STRSTARTS(STR(?celex), "6"))\n'
            "} ORDER BY DESC(?date) LIMIT 200"
        )
        try:
            body = self.fetch(
                f"{_SPARQL}?{urllib.parse.urlencode({'query': query})}",
                "application/sparql-results+json",
            )
            rows = [
                {k: v["value"] for k, v in b.items()}
                for b in json.loads(body)["results"]["bindings"]
            ]
        except (ConnectorError, ValueError, KeyError):
            return "; whether later judgments cite it could not be looked up"
        judgments = [r for r in rows if r["celex"][5:7] in ("CJ", "TJ") and r["celex"] != celex]
        opinions = [r for r in rows if r["celex"][5:7] == "CC"]
        if not judgments and not opinions:
            return "; CELLAR records no later judgment citing it"
        out = f"; cited by {len(judgments)} later judgment(s)"
        if opinions:
            out += f" and {len(opinions)} Advocate General's opinion(s)"
        latest = [f"{case_number(r['celex'])} ({r.get('date', '')[:10]})" for r in judgments[:3]]
        return (
            out
            + (f", most recently {', '.join(latest)}" if latest else "")
            + ("; read them to confirm it was not departed from")
        )

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
        title = " ".join(
            next((r["title"] for r in rows if r.get("title")), celex).split("#")[0].split()
        )
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
        ecli = next((r["ecli"] for r in rows if r.get("ecli")), "")
        citation = ecli or _short_title(title) or _act_citation(celex) or celex
        keys = [celex, ecli, citation_key]
        basis = (
            "EUR-Lex records no later treatment of judgments; a person must confirm it"
            + self._cited_by(celex)
            if is_case
            else f"CELLAR: in force {'yes' if in_force == '1' else 'no'}"
            + (f"; applies from {starts[-1]}" if len(starts) > 1 else "")
            + (f"; end of validity {end}" if end and not end.startswith("9999") else "")
            + (f"; repealed by CELEX {repealer}" if repealer else "")
        )

        published: dict[str, list[Located]] = {}

        def recitals() -> list[Located]:
            """The recitals, from the act as published: a consolidated text leaves them out,
            and they are cited and never amended."""
            if "r" not in published:
                published["r"] = [
                    p for p in _eurlex_act(self._text(celex)) if p[0].startswith("Recital ")
                ]
            return published["r"]

        def version(
            text_celex: str,
            valid_from: date | None,
            valid_to: date | None,
            standing: AuthorityStatus,
            history: list[Treatment],
            which: str,
        ) -> Found:
            text = self._text(text_celex)
            authority = Authority(
                source_id=self.source_id,
                citation=citation,
                title=title,
                jurisdiction="EU",
                kind=AuthorityKind.CASE if is_case else AuthorityKind.LEGISLATION,
                uri=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{text_celex}",
                content_hash=content_hash(text),
                court="Court of Justice of the European Union" if is_case else "",
                decision_date=_day(first.get("date", "")),
                effective_from=valid_from,
                effective_to=valid_to,
                status=standing,
                status_basis=basis
                + (f"; text: {which}" if which else "")
                + (CONSOLIDATED_NOTE if which.startswith("consolidated") else ""),
                treatments=history,
                aliases=sorted({celex, text_celex, *([ecli] if ecli else [])}),
            )
            passages = _eurlex_judgment(text) if is_case else _eurlex_act(text)
            if text_celex != celex and not any(p[0].startswith("Recital ") for p in passages):
                passages = [*recitals(), *passages]
            return Found(authority, passages, keys)

        entered = _day(starts[0]) if starts and not is_case else None
        versions = [] if is_case else self._consolidations(celex)
        # A "version" dated once the act had ceased to apply records its repeal, not a text in
        # force; and none applies before the act entered into force.
        versions = [
            (c, max(d, entered) if entered else d)
            for c, d in versions
            if effective_to is None or d <= effective_to
        ]
        # Two versions dated before the act entered into force both start on that day: the
        # later one is the text then.
        latest_by_date = {d: c for c, d in versions}
        versions = [(c, d) for d, c in sorted(latest_by_date.items())]
        if not versions:
            return [version(celex, entered, effective_to, status, treatments, "")]
        # Amended since it was published: each consolidated version holds the text in force from
        # its date until the next. The latest is the act today; the one in force on the matter's
        # relevant date is fetched too, or the act as published if that date comes first.
        amenders = self._amenders(celex)
        by = ", ".join(amenders[:6]) + ("…" if len(amenders) > 6 else "")
        dates = [d for _, d in versions]

        def superseded(at: date) -> list[Treatment]:
            return [Treatment("amended", at, by_citation=by, note="a later version applies")]

        found = []
        latest_celex, latest_from = versions[-1]
        found.append(version(latest_celex, latest_from, effective_to, status, treatments,
                             f"consolidated version of {latest_from.isoformat()}"))  # fmt: skip
        if self.as_of is not None and self.as_of < latest_from:
            earlier = [(c, d) for c, d in versions if d <= self.as_of]
            if earlier:
                text_celex, valid_from = earlier[-1]
                following = dates[dates.index(valid_from) + 1]
                found.append(version(text_celex, valid_from, following - timedelta(days=1),
                                     AuthorityStatus.AMENDED, superseded(following),
                                     f"consolidated version of {valid_from.isoformat()}"))  # fmt: skip
            else:
                found.append(version(celex, entered, dates[0] - timedelta(days=1),
                                     AuthorityStatus.AMENDED, superseded(dates[0]),
                                     "as published in the Official Journal"))  # fmt: skip
        return found

    def _text(self, celex: str) -> bytes:
        """The text, from CELLAR by its identifier: the Publications Office's own service for
        machines, which EUR-Lex's website (for people) may refuse to automated requests."""
        return self.fetch(
            f"https://publications.europa.eu/resource/celex/{celex}",
            "application/xhtml+xml, text/html;q=0.9",
        )

    def _consolidations(self, celex: str) -> list[tuple[str, date]]:
        """Each consolidated version of an act and the date it applies from, oldest first."""
        stem = f"0{celex[1:]}-"
        rows = self._select(
            "SELECT DISTINCT ?celex WHERE {\n  ?w cdm:resource_legal_id_celex ?celex .\n"
            f'  FILTER(STRSTARTS(STR(?celex), "{stem}"))\n}}'
        )
        out = []
        for r in rows:
            m = re.match(rf"^{re.escape(stem)}(\d{{4}})(\d{{2}})(\d{{2}})$", r.get("celex", ""))
            if m:
                out.append((r["celex"], date(*map(int, m.groups()))))
        return sorted(out, key=lambda x: x[1])

    def _amenders(self, celex: str) -> list[str]:
        rows = self._select(
            "SELECT DISTINCT ?amender WHERE {\n"
            f'  ?work cdm:resource_legal_id_celex "{celex}"^^<http://www.w3.org/2001/XMLSchema#string> .\n'
            "  ?a cdm:resource_legal_amends_resource_legal ?work .\n"
            "  ?a cdm:resource_legal_id_celex ?amender .\n}"
        )
        return sorted(r["amender"] for r in rows if r.get("amender"))

    def _select(self, body: str) -> list[dict[str, str]]:
        query = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n" + body
        data = json.loads(
            self.fetch(
                f"{_SPARQL}?{urllib.parse.urlencode({'query': query})}",
                "application/sparql-results+json",
            )
        )
        return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]


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


_ARTICLE = re.compile(r"^Article\s+(\d+[a-z]*)$")
_DIVISION = re.compile(
    r"^(?:CHAPTER|TITLE|PART|SECTION|Chapter|Title|Part|Section)\s+[IVXLCDM\d]+[A-Z]?$"
)
_PARAGRAPH = re.compile(r"^(\d+[a-z]?)\.\s+\S")
_POINT = re.compile(r"^‘?\((\d+[a-z]?|[a-z]{1,2}|[ivxlc]+)\)$")
_ENACTING = re.compile(r"^HA(?:VE|S) ADOPTED (?:THIS|THE FOLLOWING)\b", re.I)
_ANNEX = re.compile(r"^ANNEX(?:\s+([IVXLC]+|\d+))?$")
_FOOTNOTE = re.compile(
    r"^\(\d+\)\s+(?:OJ|Regulation|Directive|Decision|Council|Commission|Position|Opinion)\b"
)
_ANNEX_CHARS = 3000


_TRAILING_ARTICLE = re.compile(r"^(.*[.;:])\s+(Article\s+\d+[a-z]*)$")
CONSOLIDATED_NOTE = (
    "; a consolidated text is documentation only: the act as published in the Official Journal "
    "and the acts amending it are the authentic texts, so quote those where it matters"
)
# A consolidated text marks where each amendment begins and ends: ▼B, ►M1, ◄, ►C1.
_CONSOLIDATION_MARK = re.compile(r"[►▼]\s*[A-Z]{1,2}\d*|◄")


def _segments(html: bytes) -> list[str]:
    parsed = LocalDocumentParser().parse("document.html", html)
    out: list[str] = []
    for segment in parsed.segments:
        text = " ".join(_CONSOLIDATION_MARK.sub(" ", segment.text).split())
        # Some older acts print an article's heading at the end of the paragraph before it
        # ("… shall not be affected by this Directive. Article 11").
        glued = _TRAILING_ARTICLE.match(text)
        out.extend(glued.groups() if glued else [text] if text else [])
    return out


class _Passages:
    """Builds located passages from a run of segments: each passage is a list of pieces, and a
    point's marker, "(a)", is joined to the words that follow it."""

    def __init__(self) -> None:
        self.out: list[Located] = []
        self.locator = ""
        self.heading = ""
        self.pieces: list[str] = []
        self.marker = ""

    def start(self, locator: str, heading: str = "") -> None:
        self.flush()
        self.locator, self.heading = locator, heading

    def add(self, text: str) -> None:
        if self.marker:
            text, self.marker = f"{self.marker} {text}", ""
        if self.locator:
            self.pieces.append(text)

    def flush(self) -> None:
        if self.marker:
            self.pieces.append(self.marker)
            self.marker = ""
        if self.locator and self.pieces:
            self.out.append((self.locator, "\n".join(self.pieces), self.heading))
        self.locator, self.pieces = "", []


def _eurlex_act(html: bytes) -> list[Located]:
    """A Union act as located passages: each recital; each numbered paragraph of an article,
    with its points, under the article's title ("Art. 17(1)", "Right to erasure"); each
    definition of a definitions article ("Art. 4(1)"); and each annex. The signatures and the
    footnotes are left out."""
    segments = _segments(html)
    if not any(_ARTICLE.match(t) for t in segments):
        return _eurlex_plain(segments)
    b = _Passages()
    stage = "front"  # front, recitals, articles, closing, annex
    enacted = any(_ENACTING.match(t) for t in segments)
    article = title = ""
    expect_title = skip_next = False
    recital = 0
    for n, text in enumerate(segments):
        if _FOOTNOTE.match(text):
            continue
        if skip_next:  # the title of a chapter or section
            skip_next = False
            continue
        if _ENACTING.match(text):
            b.flush()
            stage = "articles"
            continue
        annex = _ANNEX.match(text)
        if annex and stage in ("articles", "closing", "annex"):
            name = f"Annex {annex.group(1)}" if annex.group(1) else "Annex"
            following = segments[n + 1] if n + 1 < len(segments) else ""
            b.start(name, following if len(following) < 150 else "")
            stage = "annex"
            continue
        if stage in ("front", "recitals") and not enacted and _ARTICLE.match(text):
            b.flush()
            stage = "articles"  # no enacting formula printed: the articles begin here
        if stage == "front":
            if text.startswith("Whereas"):
                stage = "recitals"
                if text.rstrip(":").strip() == "Whereas":
                    continue
            else:
                continue
        if stage == "recitals":
            point = _POINT.match(text)
            if point and point.group(1).isdigit():
                b.start(f"Recital {point.group(1)}")
            elif text.startswith(("Whereas", "whereas")):
                recital += 1
                b.start(f"Recital {recital}")
                b.add(text)
            else:
                b.add(text)
            continue
        if stage == "closing":
            continue
        if stage == "annex":
            if sum(len(p) for p in b.pieces) > _ANNEX_CHARS:
                b.start(f"{b.locator.split(' ¶')[0]} ¶{n}", b.heading)
            if text != b.heading or b.pieces:
                b.add(text)
            continue
        # The enacting terms.
        if text.startswith("Done at "):
            b.flush()
            stage = "closing"
            continue
        if _DIVISION.match(text):
            b.flush()
            skip_next = True
            continue
        heading = _ARTICLE.match(text)
        if heading:
            article, title, expect_title = heading.group(1), "", True
            b.start(f"Art. {article}")
            continue
        if expect_title:
            expect_title = False
            if (
                len(text) < 200
                and not _PARAGRAPH.match(text)
                and not _POINT.match(text)
                and not text.endswith((".", ":", ";"))
            ):
                title = b.heading = text
                continue
        paragraph = _PARAGRAPH.match(text)
        if paragraph:
            b.start(f"Art. {article}({paragraph.group(1)})", title)
            b.add(text)
            continue
        point = _POINT.match(text)
        if point:
            numbered = point.group(1)[0].isdigit()
            if numbered and (b.locator == f"Art. {article}" or b.locator.count("(") == 1
                             and b.locator.startswith(f"Art. {article}(")
                             and b.pieces and b.pieces[0].startswith("(")):  # fmt: skip
                # Numbered points directly under the article: definitions, each its own.
                b.start(f"Art. {article}({point.group(1)})", title)
            b.marker = f"({point.group(1)})"
            continue
        if not b.locator:
            b.start(f"Art. {article}", title)
        b.add(text)
    b.flush()
    return b.out[:3000]


def _bare_number(text: str) -> bool:
    return text.isdigit() and len(text) < 5


def _eurlex_judgment(html: bytes) -> list[Located]:
    """A judgment as located passages: each numbered paragraph ("¶42"), under the heading of
    the part of the judgment it is in, and the ruling."""
    segments = _segments(html)
    if "Judgment" not in segments:
        return _eurlex_plain(segments)
    b = _Passages()
    begun = False
    heading = ""

    def heading_like(i: int) -> bool:
        if i >= len(segments):
            return False
        t = segments[i]
        return (
            len(t) < 150
            and not _bare_number(t)
            and not t.endswith((".", ";", ":", ","))
            and not t.startswith(("‘", "(", "—", "–"))
        )

    for i, text in enumerate(segments):
        if not begun:
            begun = text == "Judgment"
            continue
        if text.startswith("On those grounds"):
            b.start("Ruling", "Ruling")
            b.add(text)
            continue
        if b.locator == "Ruling":
            if text.startswith("[Signatures]") or text.startswith("*"):
                break
            b.add(text)
            continue
        if _bare_number(text):
            b.start(f"¶{text}", heading)
            continue
        nxt = segments[i + 1] if i + 1 < len(segments) else ""
        if heading_like(i) and (_bare_number(nxt) or (heading_like(i + 1) and i + 2 < len(segments)
                                and _bare_number(segments[i + 2]))):  # fmt: skip
            b.flush()
            heading = text
            continue
        b.add(text)
    b.flush()
    return b.out[:3000]


def _eurlex_plain(segments: list[str]) -> list[Located]:
    return [(f"¶{n}", t, "") for n, t in enumerate(segments[:3000], 1)]


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
            # What happened since, as the current version records it: each provision repealed
            # since, and the Act itself repealed or amended.
            later = [t for t in current.authority.treatments if t.provision]
            if current.authority.status is AuthorityStatus.REPEALED:
                a.treatments = list(current.authority.treatments)
            else:
                a.treatments = [
                    *later,
                    Treatment("amended", start, note="a later version is in force"),
                ]
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
        passages: list[Located] = []
        for para in root.iter(f"{_AKN}paragraph"):
            text = " ".join(" ".join(para.itertext()).split())
            if text:
                number = para.get("eId", "").removeprefix("para_") or str(len(passages) + 1)
                passages.append((f"¶{number}", text, ""))
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
        parent = {child: el for el in root.iter() for child in el}
        sections = [p for p in root.iter(f"{_LEG_NS}P1") if not _quoted(p, parent)]
        # legislation.gov.uk marks a repealed section on the group around it (or a Part or
        # Schedule around that), with the date the repeal took effect.
        # Or, in older entries, the section keeps only its number and a row of dots, with the
        # repeal in its own annotation ("S. 156 repealed (1.10.2006) by …").
        marks: dict[int, ET.Element | None] = {}
        for p in sections:
            mark = _repeal_mark(p, parent)  # an element with no children is falsy: compare to None
            marks[id(p)] = mark if mark is not None else (p if _dotted(p) else None)
        repealed = [p for p in sections if marks[id(p)] is not None]
        passages: list[Located] = []
        for p in sections:
            text = _provision_text(p)
            if text:
                passages.append((_provision_locator(p, ident), text, _provision_heading(p, parent)))
        # A schedule written as plain paragraphs, without numbered provisions (the guidelines
        # for the reasonableness test, say), is one passage.
        for schedule in root.iter(f"{_LEG_NS}Schedule"):
            body = schedule.find(f"{_LEG_NS}ScheduleBody")
            if (
                body is None
                or _quoted(schedule, parent)
                or body.find(f".//{_LEG_NS}P1") is not None
            ):
                continue
            text = _provision_text(body)
            if text:
                named = schedule.find(f"{_LEG_NS}TitleBlock/{_LEG_NS}Title")
                heading = " ".join("".join(named.itertext()).split()) if named is not None else ""
                passages.append((_provision_locator(schedule, ident), text, heading))
        whole_repeal = bool(sections) and len(repealed) == len(sections)
        version_from = _day(valid_el.text or "") if valid_el is not None else None
        # The date, author and reach of each repeal are in the annotation the mark points to
        # ("Pt. 5A omitted (1.10.2015) by virtue of Consumer Rights Act 2015 …"); the mark's own
        # date is when that version of the text began, not when it was repealed.
        notes = {
            c.get("id"): " ".join("".join(c.itertext()).split())
            for c in root.iter(f"{_LEG_NS}Commentary")
        }
        provision_repeals: list[Treatment] = []
        for p in repealed:
            mark = marks[id(p)]
            found = _repeal_annotation(mark, notes) if mark is not None else None
            locator = _provision_locator(p, ident)
            if found is None:
                if version_from is None:
                    provision_repeals.append(
                        Treatment("repealed", date.today(), provision=locator, note=UNDATED_REPEAL)
                    )
                else:
                    provision_repeals.append(
                        Treatment(
                            "repealed", version_from, provision=locator, note=REPEALED_BY_VERSION
                        )  # fmt: skip
                    )
                continue
            when, by, reach = found
            if reach == "elsewhere":
                continue  # repealed for Scotland or Northern Ireland only: in force here
            provision_repeals.append(
                Treatment(
                    "repealed",
                    when,
                    by_citation=by,
                    provision=locator,
                    note=REPEALED_IN_PART if reach == "part" else "",
                )  # fmt: skip
            )
        repealed = [p for p in repealed
                    if any(t.provision == _provision_locator(p, ident) for t in provision_repeals)]  # fmt: skip
        whole_repeal = bool(sections) and len(repealed) == len(sections)
        dates = [t.effective_date for t in provision_repeals if not t.note]
        # The Act as a whole is gone only once its last provision is.
        repeal_date = max(dates) if dates and len(dates) == len(provision_repeals) else None
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
            + (
                f"; {len(repealed)} of {len(sections)} provisions repealed: "
                + ", ".join(t.provision for t in provision_repeals[:12])
                + ("…" if len(provision_repeals) > 12 else "")
                if repealed
                else ""
            ),
            treatments=[
                *provision_repeals,
                *([Treatment("repealed", repeal_date)] if whole_repeal and repeal_date else []),
            ],
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


_UNITS = {"section": "s.", "regulation": "reg.", "article": "art.", "rule": "r.",
          "schedule": "Sch.", "paragraph": "para.", "part": "Pt."}  # fmt: skip


def _quoted(p: ET.Element, parent: dict[ET.Element, ET.Element]) -> bool:
    """A provision quoted inside another (an amendment's text, or a nested provision), which
    belongs to the provision it is quoted in."""
    a = parent.get(p)
    while a is not None:
        if a.tag in (f"{_LEG_NS}BlockAmendment", f"{_LEG_NS}P1"):
            return True
        a = parent.get(a)
    return False


_REPEAL_NOTE = re.compile(
    r"\b(?:repealed|omitted|revoked|ceases? to have effect)\b\s*"
    r"(?:\((?P<reach>(?:E|W|S|N\.?\s?I)[.\s]*(?:(?:E|W|S|N\.?\s?I)[.\s]*)*)\)\s*)?"
    r"\((?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\)"
    r"(?:\s*by(?:\s+virtue\s+of)?\s+(?P<by>.+?)(?=\s*\((?:c\.|S\.I\.|SIF)|[,;]|$))?",
    re.I,
)


def _repeal_annotation(
    mark: ET.Element, notes: dict[str | None, str]
) -> tuple[date, str, str] | None:
    """(date, what repealed it, reach) from the annotation of a repealed provision. Reach is
    "all" (England and Wales, or everywhere), "part" (only England or only Wales) or
    "elsewhere" (only Scotland or Northern Ireland)."""
    for ref in mark.iter(f"{_LEG_NS}CommentaryRef"):
        m = _REPEAL_NOTE.search(notes.get(ref.get("Ref"), ""))
        if not m:
            continue
        try:
            when = date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        reach = "all"
        if m["reach"]:
            letters = re.sub(r"N\.?\s?I", "N", m["reach"].upper().replace(".", "").replace(" ", ""))
            has_e, has_w = "E" in letters, "W" in letters
            reach = "all" if has_e and has_w else "part" if has_e or has_w else "elsewhere"
        return when, " ".join((m["by"] or "").split()), reach
    return None


def _dotted(p: ET.Element) -> bool:
    """A provision whose words are gone: only its number and dots remain."""
    words = " ".join(" ".join(p.itertext()).split())
    words = re.sub(r"^\S+\s*", "", words)  # its number
    return bool(words) and set(words) <= {".", " ", "…"}


def _repeal_mark(p: ET.Element, parent: dict[ET.Element, ET.Element]) -> ET.Element | None:
    """The element that marks this provision repealed: itself, or what encloses it."""
    el: ET.Element | None = p
    while el is not None:
        if el.get("Status") == "Repealed":
            return el
        el = parent.get(el)
    return None


def _provision_locator(p: ET.Element, ident: str) -> str:
    """'…/ukpga/1979/54/section/10' -> 's.10'; '…/schedule/1/paragraph/5' -> 'Sch. 1 para. 5'."""
    uri = p.get("DocumentURI") or p.get("IdURI") or ""
    parts = (
        [x for x in uri.split(f"/{ident}/", 1)[-1].split("/") if x] if f"/{ident}/" in uri else []
    )
    out: list[str] = []
    i = 0
    while i < len(parts):
        unit = _UNITS.get(parts[i])
        if unit is None:
            i += 1
            continue
        number = parts[i + 1] if i + 1 < len(parts) and parts[i + 1] not in _UNITS else ""
        out.append(f"s.{number}" if parts[i] == "section" else f"{unit} {number}".strip())
        i += 2 if number else 1
    if out:
        return " ".join(out)
    number = p.findtext(f"{_LEG_NS}Pnumber") or p.get("id", "").removeprefix("section-")
    return f"s.{number}"


def _provision_text(p: ET.Element) -> str:
    """The provision's words, each subsection and paragraph on its own line with its number
    as printed: "(1) Unless …", "(a) …". The provision's own number is its locator."""
    lines: list[list[str]] = [[]]

    def walk(el: ET.Element, depth: int, quoted: bool) -> None:
        tag = el.tag.removeprefix(_LEG_NS)
        if tag == "Pnumber":
            number = "".join(el.itertext()).strip()
            if depth > 1:
                lines.append([f"({number})"])
            elif quoted:  # the number of a section an amendment quotes: "9 A party may …"
                lines.append([number])
            return
        if tag in ("CommentaryRef", "Commentary", "Title"):
            return
        if tag == "BlockAmendment":  # quoted text starts on a line of its own
            lines.append([])
            quoted = True
        if el.text and el.text.strip():
            lines[-1].append(el.text)
        level = int(tag[1]) if re.fullmatch(r"P[1-9]", tag) else depth
        for child in el:
            walk(child, level, quoted)
            if child.tail and child.tail.strip():
                lines[-1].append(child.tail)

    walk(p, 1, False)
    return "\n".join(t for line in lines if (t := " ".join(" ".join(line).split())))


def _provision_heading(p: ET.Element, parent: dict[ET.Element, ET.Element]) -> str:
    """The heading printed above a section ("Stipulations about time."), or the cross-heading
    of the part of a schedule it is in."""
    up = parent.get(p)
    while up is not None and up.tag in (f"{_LEG_NS}P1group", f"{_LEG_NS}Pblock"):
        title = up.find(f"{_LEG_NS}Title")
        if title is not None:
            return " ".join("".join(title.itertext()).split())
        up = parent.get(up)
    return ""


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
