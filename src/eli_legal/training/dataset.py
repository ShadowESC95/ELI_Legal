"""Turning approved work into training examples.

Only runs a named reviewer approved, of matters whose lead allowed training, give examples.
Each answered model call of such a run becomes one candidate: the system message and prompt as
sent and the answer as given, with people taken out (pseudonymise.py). Its answer is the one to
learn when the reviewer approved what was built from the run without taking anything out
("reviewer_unchanged"); where the reviewer took findings out of reliance, the answer may be what
was wrong, and a person must check it ("reviewer_corrected").

What an example keeps, and which examples are never kept, is pseudonymise.py's: names,
contact details and identifying numbers always go, amounts, dates, references and addresses go
unless the organisation keeps them, and a call that concerns special categories of personal data,
criminal offences or a child is not kept at all (it is counted, by kind, and nothing else).

Which matters teach is the organisation's scope: practice matters only, unless the compliance
officer has allowed real matters, and then only those whose client's consent is on record.

A fixed share of examples, chosen by their content so it never changes, is kept back to test a
trained model and is never trained on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from eli_legal.domain.enums import ClaimStatus, ReviewDecision, RunStatus
from eli_legal.domain.models import Claim, HumanReview, Run, TrainingExample, utcnow
from eli_legal.training.pseudonymise import OPTIONAL, Pseudonymiser, never_kept
from eli_legal.training.records import read_calls

# The steps whose calls teach the model: the analysis itself, not the chat.
TASKS = ("fact_select", "issue_propose", "fact_issue_link", "arguments", "support_check")


@dataclass
class Built:
    matters: int = 0
    runs: int = 0
    added: int = 0
    approved_by_review: int = 0
    already: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def content_hash(system: str, prompt: str, answer: str) -> str:
    return hashlib.sha256("\x1f".join((system, prompt, answer)).encode("utf-8")).hexdigest()


def split_of(digest: str, heldout_percent: int) -> str:
    return "heldout" if int(digest[:8], 16) % 100 < max(0, min(50, heldout_percent)) else "train"


def _approval(ctx: Any, matter_id: str, run: Run) -> HumanReview | None:
    reviews = [
        r
        for r in ctx.store.list(HumanReview, matter_id, run_id=run.run_id)
        if r.decision is ReviewDecision.APPROVE
    ]
    return reviews[-1] if reviews else None


def may_teach(matter: Any, scope: str) -> str | None:
    """Why a matter may not teach under the organisation's scope, or None if it may."""
    if not matter.training_use:
        return "its lead has not allowed it"
    if matter.real and scope != "consented":
        return "a real matter, and the organisation trains on practice matters only"
    if matter.real and not matter.training_consent.strip():
        return "a real matter with no client consent on record"
    return None


def names_of(matter: Any) -> list[str]:
    """Every name the matter itself records: its parties and who represents them."""
    found = [p.name for p in matter.parties]
    found += [p.represented_by for p in matter.parties if p.represented_by]
    return found


def build(
    ctx: Any,
    *,
    heldout_percent: int,
    autonomous: bool,
    scope: str = "practice",
    omit: Any = OPTIONAL,
) -> Built:
    """Add candidates from every approved run of every matter allowed to train. A call already
    taken is not taken again."""
    out = Built()
    for matter in ctx.store.list_matters():
        why = may_teach(matter, scope)
        if why is not None:
            if matter.training_use:
                out.skip(f"matter {matter.matter_id}: {why}")
            continue
        out.matters += 1
        mid = matter.matter_id
        known = {e.content_hash for e in ctx.store.list(TrainingExample, mid)}
        for run in ctx.store.list(Run, mid):
            if run.status is not RunStatus.APPROVED_FOR_RELIANCE:
                continue
            review = _approval(ctx, mid, run)
            if review is None:
                out.skip("approved run with no review on record")
                continue
            out.runs += 1
            corrected = any(
                c.status is ClaimStatus.EXCLUDED
                for c in ctx.store.list(Claim, mid, run_id=run.run_id)
            )
            for call in read_calls(ctx, mid, run.run_id):
                task = str(call.get("task") or "")
                if task not in TASKS:
                    out.skip(f"{task or 'unnamed'}: not a task that is trained")
                    continue
                if not isinstance(call.get("parsed"), dict):
                    out.skip("the answer was not usable")
                    continue
                raw_answer = json.dumps(call["parsed"], ensure_ascii=False, sort_keys=True)
                kind = never_kept(f"{call.get('prompt') or ''}\n{raw_answer}")
                if kind is not None:  # not kept, not even as a candidate: counted only
                    out.skip(f"never kept: {kind}")
                    continue
                hide = Pseudonymiser(names_of(matter), omit)
                system = hide(str(call.get("system") or ""))
                prompt = hide(str(call.get("prompt") or ""))
                answer = hide(raw_answer)
                digest = content_hash(system, prompt, answer)
                if digest in known:
                    out.already += 1
                    continue
                known.add(digest)
                example = TrainingExample(
                    matter_id=mid,
                    run_id=run.run_id,
                    task=task,
                    prompt_version=str(call.get("prompt_version") or task),
                    system=system,
                    prompt=prompt,
                    answer=answer,
                    model_answer=answer,
                    source="reviewer_corrected" if corrected else "reviewer_unchanged",
                    split=split_of(digest, heldout_percent),
                    content_hash=digest,
                    omitted=dict(hide.counts),
                )
                if autonomous and not corrected:
                    example.status = "approved"
                    example.reviewed_by = review.reviewer_user_id
                    example.reviewed_at = utcnow()
                    example.review_note = (
                        f"approved by the review of run {run.run_id}, "
                        "accepted without taking anything out"
                    )
                    out.approved_by_review += 1
                ctx.store.put(example)
                out.added += 1
    return out


def chat_rows(example: TrainingExample) -> dict[str, Any]:
    """An example as the trainer reads it: a conversation in the model's own chat format."""
    return {
        "id": example.example_id,
        "task": example.task,
        "messages": [
            {"role": "system", "content": example.system},
            {"role": "user", "content": example.prompt},
            {"role": "assistant", "content": example.answer},
        ],
    }
