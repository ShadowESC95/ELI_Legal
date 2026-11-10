"""How well legal research finds the provisions that govern an issue.

The benchmark is 70 issues stated as a tribunal states them, each with the provisions a lawyer
would cite, over a corpus of fifteen EU and UK instruments as their official databases publish
them (``benchmark/research.json``, ``benchmark/legislation.jsonl.gz``). Each issue is searched
across its whole legal system, so every other provision is a distractor.

Measured for each way of ranking (by words, by meaning, both):

* **recall at 5 and 10**: the share of the provisions in point that are among the first 5 or
  10 provisions found;
* **MRR**: how high the first provision in point comes (1 when first, 0.5 when second, …);
* **nDCG at 10**: the ranking judged as a whole, the governing provisions counting most;
* **offered**: what research actually puts in front of the reviewer for the issue (a few
  quoted passages), and how many of those are in point;
* **closest passage**: in each instrument that governs the issue, whether the passage shown as
  closest (as beside what a party says of an authority) is in point.

A provision is a section, a Schedule paragraph, an article (any of its paragraphs) or a recital.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.sources.local_corpus import LocalCorpusConnector, import_records
from eli_legal.domain.models import Issue
from eli_legal.evaluation.metrics import mean, ndcg_at, recall_at, reciprocal_rank
from eli_legal.legal.case_law_retriever import CaseLawRetriever
from eli_legal.legal.citations import normalise_citation as _key
from eli_legal.legal.report_builder import closest_in_wording
from eli_legal.legal.semantic import SemanticIndex
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.persistence.sqlite import Store

HERE = Path(__file__).parent / "benchmark"
CASES = HERE / "research.json"
CORPUS = HERE / "legislation.jsonl.gz"
SOURCE_ID = "benchmark_legislation"
DEPTH = 50  # passages read from each ranking
METHODS = ("keyword", "meaning", "hybrid")


@dataclass(frozen=True, slots=True)
class ResearchCase:
    case_id: str
    jurisdiction: str
    issue: str
    relevant: dict[str, int]  # "citation|provision" -> 2 governs, 1 also in point


@dataclass(slots=True)
class IssueOutcome:
    case_id: str
    found: list[str]
    recall_5: float
    recall_10: float
    reciprocal_rank: float
    ndcg_10: float
    offered: list[str]
    offered_in_point: int
    governing_offered: int
    governing: int
    # In each instrument that governs the issue: is the passage closest to the issue in point?
    closest_in_point: int = 0
    closest_asked: int = 0


@dataclass(slots=True)
class ResearchResult:
    method: str
    model: str
    issues: list[IssueOutcome] = field(default_factory=list)
    seconds: float = 0.0

    def measures(self) -> dict[str, float]:
        offered = sum(len(i.offered) for i in self.issues)
        return {
            "recall_5": round(mean([i.recall_5 for i in self.issues]), 3),
            "recall_10": round(mean([i.recall_10 for i in self.issues]), 3),
            "mrr": round(mean([i.reciprocal_rank for i in self.issues]), 3),
            "ndcg_10": round(mean([i.ndcg_10 for i in self.issues]), 3),
            "offered_in_point": round(
                sum(i.offered_in_point for i in self.issues) / offered if offered else 0.0, 3
            ),
            "governing_offered": round(
                sum(i.governing_offered for i in self.issues)
                / max(1, sum(i.governing for i in self.issues)),
                3,
            ),
            "issues_with_nothing_in_top_10": sum(1 for i in self.issues if i.recall_10 == 0),
            "closest_passage_in_point": round(
                sum(i.closest_in_point for i in self.issues)
                / max(1, sum(i.closest_asked for i in self.issues)),
                3,
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "model": self.model,
            "issues": len(self.issues),
            "seconds": round(self.seconds, 1),
            **self.measures(),
            "missed": [i.case_id for i in self.issues if i.recall_10 == 0],
        }


def load_cases(path: Path = CASES) -> list[ResearchCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        ResearchCase(c["id"], c["jurisdiction"], c["issue"], dict(c["relevant"]))
        for c in data["issues"]
    ]


def corpus_records(path: Path = CORPUS) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def corpus_digest(path: Path = CORPUS) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source() -> RegisteredSource:
    return RegisteredSource(
        source_id=SOURCE_ID,
        name="Benchmark: EU and UK legislation",
        approved=True,
        jurisdictions=frozenset({"EU", "GB-EAW"}),
        terms_reviewed=True,
        licence="EUR-Lex: reuse authorised (Commission Decision 2011/833/EU); legislation.gov.uk: "
        "Open Government Licence v3.0",
    )


def benchmark_store(folder: Path) -> Store:
    """The benchmark corpus in a store of its own, kept between runs with its vectors, so a
    model's passages are embedded once. A changed corpus gets a new store."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"research-{corpus_digest()[:12]}.db"
    fresh = not path.exists()
    store = Store(path)
    if fresh or not store.count_passages([SOURCE_ID]):
        records = [(f"{n:02d}.json", r) for n, r in enumerate(corpus_records())]
        import_records(store, source(), records)
    return store


def _flat(text: str) -> str:
    return " ".join(text.split())


def provision(citation: str, locator: str) -> str:
    """'Regulation (EU) 2016/679', 'Art. 17(1)' -> 'Regulation (EU) 2016/679|Art. 17'."""
    return f"{_flat(citation)}|{re.sub(r'[(].*$', '', locator).strip()}"


def _in_point(found: str, relevant: dict[str, int]) -> str:
    """The provision in point that ``found`` is, or is part of ('…|Sch. 2 para. 1' is part of
    '…|Sch. 2'); otherwise ``found`` itself."""
    for wanted in relevant:
        if found == wanted or found.startswith(f"{wanted} "):
            return wanted
    return found


def evaluate(
    store: Store,
    cases: Sequence[ResearchCase],
    *,
    method: str,
    semantic: SemanticIndex | None = None,
    per_issue: int = 4,
) -> ResearchResult:
    connector = LocalCorpusConnector(store, source())
    retriever = CaseLawRetriever({SOURCE_ID: connector}, semantic=semantic, mode=method)
    result = ResearchResult(method=method, model=retriever.method)
    began = time.monotonic()
    for case in cases:
        hits = retriever.search(jurisdictions=[case.jurisdiction], query=case.issue, limit=DEPTH)
        found: list[str] = []
        for hit in hits:
            key = _in_point(provision(hit.authority.citation, hit.passage.locator), case.relevant)
            if key not in found:
                found.append(key)
        issue = Issue(matter_id="benchmark", run_id="benchmark", label=case.issue, kind="legal")
        offered = []
        for claim in retriever.propositions_for_issue(
            matter_id="benchmark",
            run_id="benchmark",
            issue=issue,
            jurisdictions=[case.jurisdiction],
            per_issue=per_issue,
        ):
            locator = claim.evidence[0].locator if claim.evidence else ""
            offered.append(_in_point(provision(claim.citation or "", locator), case.relevant))
        governing = {k for k, g in case.relevant.items() if g >= 2}
        # The pointer shown beside what a party says of an authority: in meaning when this
        # method searches by meaning, otherwise in wording.
        asked = in_point = 0
        for citation in sorted({k.split("|")[0] for k in governing}):
            authority = next(iter(store.authorities_by_citation(_key(citation), [SOURCE_ID])), None)
            passages = store.passages_for(authority.authority_id) if authority else []
            if not passages:
                continue
            asked += 1
            if method != "keyword" and semantic is not None and semantic.available:
                nearest = semantic.closest(case.issue, passages)
                chosen = next((p for p in passages if nearest and p.passage_id == nearest[0]), None)
            else:
                chosen = closest_in_wording(case.issue, passages)
            if chosen is not None:
                key = _in_point(provision(citation, chosen.locator), case.relevant)
                in_point += key in case.relevant
        result.issues.append(
            IssueOutcome(
                case_id=case.case_id,
                found=found[:20],
                recall_5=recall_at(found, case.relevant, 5),
                recall_10=recall_at(found, case.relevant, 10),
                reciprocal_rank=reciprocal_rank(found, case.relevant),
                ndcg_10=ndcg_at(found, case.relevant, 10),
                offered=offered,
                offered_in_point=sum(1 for o in offered if o in case.relevant),
                governing_offered=len(governing & set(offered)),
                governing=len(governing),
                closest_in_point=in_point,
                closest_asked=asked,
            )
        )
    result.seconds = time.monotonic() - began
    return result


def run(
    folder: Path,
    *,
    methods: Sequence[str] = METHODS,
    semantic_for: Any = None,
    cases: Sequence[ResearchCase] | None = None,
) -> dict[str, Any]:
    """Every method on the benchmark. ``semantic_for(store)`` gives the meaning index for the
    benchmark's store, or None when no embedding model is set up (then only keyword runs)."""
    store = benchmark_store(folder)
    chosen = list(cases or load_cases())
    semantic = semantic_for(store) if semantic_for else None
    indexing: dict[str, Any] = {}
    if semantic is not None and semantic.available:
        began = time.monotonic()
        coverage = semantic.ensure([SOURCE_ID], budget=10**9)
        indexing = {
            "model": semantic.model_id,
            "passages": coverage.total,
            "embedded_now": coverage.indexed_now,
            "seconds": round(time.monotonic() - began, 1),
        }
    results = []
    for method in methods:
        if method != "keyword" and (semantic is None or not semantic.available):
            continue
        results.append(evaluate(store, chosen, method=method, semantic=semantic).as_dict())
    return {
        "benchmark": "research",
        "issues": len(chosen),
        "corpus": {
            "instruments": len({r["citation"] for r in corpus_records()}),
            "passages": store.count_passages([SOURCE_ID]),
            "sha256": corpus_digest(),
        },
        "indexing": indexing,
        "results": results,
    }
