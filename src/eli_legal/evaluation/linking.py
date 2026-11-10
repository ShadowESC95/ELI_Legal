"""How well facts are tied to the issues they bear on.

Four disputes (``benchmark/linking.json``), each with the issues stated at intake and the facts
as the parties' papers state them; each fact lists the issues it bears on, some none, some two.
The facts are linked by ``IssueMapper.link_facts``, as in a run, without a language model: by
their words, and with an embedding model also by their meaning. Measured over every (fact,
issue) pair: precision (of the links made, the share that are right), recall (of the right
links, the share made) and F1.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.local import NullInference
from eli_legal.domain.enums import ClaimKind
from eli_legal.domain.models import Claim, Issue
from eli_legal.evaluation.metrics import precision_recall_f1
from eli_legal.legal.issue_mapper import IssueMapper
from eli_legal.legal.llm import LegalModel
from eli_legal.legal.semantic import SemanticIndex

CASES = Path(__file__).parent / "benchmark" / "linking.json"


def load(path: Path = CASES) -> list[dict[str, Any]]:
    disputes: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["disputes"]
    return disputes


def link(dispute: dict[str, Any], semantic: SemanticIndex | None) -> tuple[set[Any], set[Any]]:
    """(links made, links wanted), each a set of (dispute, fact number, issue key)."""
    issues = {
        key: Issue(matter_id="benchmark", run_id="benchmark", label=label)
        for key, label in dispute["issues"].items()
    }
    facts = [
        Claim(matter_id="benchmark", run_id="benchmark", text=f["text"], kind=ClaimKind.FACT)
        for f in dispute["facts"]
    ]
    IssueMapper(LegalModel(NullInference()), semantic=semantic).link_facts(
        issues=list(issues.values()), facts=facts
    )
    key_of = {issue.issue_id: key for key, issue in issues.items()}
    made = {(dispute["id"], n, key_of[i]) for n, f in enumerate(facts) for i in f.issue_ids}
    wanted = {(dispute["id"], n, k) for n, f in enumerate(dispute["facts"]) for k in f["issues"]}
    return made, wanted


def evaluate(disputes: Sequence[dict[str, Any]], semantic: SemanticIndex | None) -> dict[str, Any]:
    made: set[Any] = set()
    wanted: set[Any] = set()
    for dispute in disputes:
        m, w = link(dispute, semantic)
        made |= m
        wanted |= w
    precision, recall, f1 = precision_recall_f1(made, wanted)
    facts = sum(len(d["facts"]) for d in disputes)
    linked = {(d, n) for d, n, _ in made}
    return {
        "method": f"words+meaning:{semantic.model_id}" if semantic else "words",
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "facts": facts,
        "facts_linked_to_nothing": facts - len(linked),
        "links_wanted": len(wanted),
    }


def run(semantic: SemanticIndex | None = None) -> dict[str, Any]:
    disputes = load()
    results = [evaluate(disputes, None)]
    if semantic is not None and semantic.available:
        results.append(evaluate(disputes, semantic))
    return {
        "benchmark": "linking",
        "disputes": len(disputes),
        "facts": sum(len(d["facts"]) for d in disputes),
        "results": results,
    }
