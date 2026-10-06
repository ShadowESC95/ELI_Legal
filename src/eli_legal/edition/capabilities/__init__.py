"""Capabilities the edition adds to a hosting ELI.

Two rules shape this list.

*No decisions.* Resolving a hold, recording a verification, approving a report and releasing one
are not here. They are made by a named person through ELI Legal's own authenticated interface. A
conversational assistant routes requests with a language model, and a model can be talked into
things; a decision that can be triggered by a sentence is not a human decision.

*No content.* Handlers return status, counts, identifiers and file paths. They never return the
text of a matter document or a report, because whatever a capability returns passes through the
host's conversation history.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from eli_legal.application.services import Services
from eli_legal.domain.enums import Profile
from eli_legal.domain.errors import EliLegalError

Handler = Callable[[Services, str, Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    category: str
    description: str
    handler: Handler
    example: str = ""


def _ok(content: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "content": content, "response": content, **extra}


def _need(args: Mapping[str, Any], *names: str) -> list[str]:
    values = []
    for name in names:
        value = str(args.get(name) or "").strip()
        if not value:
            raise EliLegalError(f"missing argument: {name}")
        values.append(value)
    return values


def _status(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    chain = sv.ctx.audit.report()
    approved = [s.source_id for s in sv.ctx.sources.list() if s.approved]
    return _ok(
        f"ELI Legal is running. Audit chain {'valid' if chain.ok else 'INVALID'} "
        f"({chain.count} events). {len(approved)} approved legal source(s). "
        f"Model: {sv.ctx.model.model_id}.",
        audit_ok=chain.ok,
        sources=approved,
    )


def _matter_list(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matters = sv.matters.list_for(actor)
    lines = [f"{m.matter_id} — {m.name} ({m.profile.value}, {m.status.value})" for m in matters]
    return _ok(
        "\n".join(lines) or "You have no matters.", matter_ids=[m.matter_id for m in matters]
    )


def _matter_create(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    name, purpose, jurisdiction, profile = _need(args, "name", "purpose", "jurisdiction", "profile")
    matter = sv.matters.create(
        actor_id=actor,
        name=name,
        purpose=purpose,
        jurisdiction=jurisdiction,
        profile=Profile(profile),
        stated_issues=[str(i) for i in args.get("issues") or []],
        parties=[(str(p["name"]), str(p["role"])) for p in args.get("parties") or []],
    )
    return _ok(f"Opened matter {matter.matter_id}.", matter_id=matter.matter_id)


def _ingest(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matter_id, path = _need(args, "matter_id", "path")
    matter = sv.ctx.matter_for(matter_id, actor, "document.ingest")
    documents = sv.ingestion.ingest_path(matter=matter, actor_id=actor, path=path)
    unread = [d for d in documents if d.status.value != "processed"]
    flagged = [d for d in documents if d.injection_flags]
    return _ok(
        f"Took in {len(documents)} document(s); {len(unread)} could not be read; "
        f"{len(flagged)} flagged for a person to look at.",
        document_ids=[d.document_id for d in documents],
    )


def _run_start(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    (matter_id,) = _need(args, "matter_id")
    run = sv.runs.start(matter_id, actor_id=actor)
    return _run_report(sv, actor, matter_id, run.run_id)


def _run_status(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matter_id, run_id = _need(args, "matter_id", "run_id")
    return _run_report(sv, actor, matter_id, run_id)


def _run_report(sv: Services, actor: str, matter_id: str, run_id: str) -> dict[str, Any]:
    summary = sv.runs.summary(matter_id, run_id, actor_id=actor)
    reasons = sorted({h["reason"] for h in summary["open_holds"]})
    text = f"Run {run_id} is {summary['status'].replace('_', ' ')}."
    if reasons:
        text += (
            f" {len(summary['open_holds'])} hold(s) are open ({', '.join(reasons)}); a named "
            "reviewer must deal with them in ELI Legal."
        )
    if summary["status"] == "awaiting_human_review":
        text += " The draft report is ready for the named reviewer."
    return _ok(
        text,
        run_id=run_id,
        status=summary["status"],
        open_holds=len(summary["open_holds"]),
        open_tasks=summary["open_tasks"],
    )


def _holds(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matter_id, run_id = _need(args, "matter_id", "run_id")
    holds = sv.holds.list(matter_id, run_id, actor_id=actor)
    lines = [f"{h.hold_id}: {h.scope.value} — {h.reason_code}" for h in holds]
    return _ok("\n".join(lines) or "No holds are open.", hold_ids=[h.hold_id for h in holds])


def _report_path(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matter_id, run_id = _need(args, "matter_id", "run_id")
    report = sv.runs.summary(matter_id, run_id, actor_id=actor)["report"]
    if not report:
        return {
            "ok": False,
            "content": "No report has been drafted.",
            "response": "No report has been drafted.",
        }
    state = (
        "approved for reliance"
        if report["release_status"] == "APPROVED_FOR_RELIANCE"
        else "a draft, not for reliance"
    )
    return _ok(f"The report is {state}. Open it from: {report['path']}", path=report["path"])


def _audit_verify(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    sv.ctx.authorizer().require_global(actor, "audit.verify")
    chain = sv.ctx.audit.report()
    text = (
        f"Audit chain valid ({chain.count} events)."
        if chain.ok
        else f"AUDIT CHAIN INVALID: {chain.error}"
    )
    return {"ok": chain.ok, "content": text, "response": text, "events": chain.count}


def _evidence_pack(sv: Services, actor: str, args: Mapping[str, Any]) -> dict[str, Any]:
    matter_id, run_id = _need(args, "matter_id", "run_id")
    path = sv.evidence_pack(matter_id, run_id, actor_id=actor)
    return _ok(f"Evidence pack written to {path}", path=str(path))


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "LEGAL_STATUS",
        "legal-audit",
        "Health of the legal runtime: audit chain, sources, model",
        _status,
        "is the legal system healthy?",
    ),
    Capability(
        "LEGAL_MATTER_LIST",
        "legal-matter",
        "List the matters you have access to",
        _matter_list,
        "list my matters",
    ),
    Capability(
        "LEGAL_MATTER_CREATE",
        "legal-matter",
        "Open a matter under a profile and jurisdiction",
        _matter_create,
        "open a new arbitration matter",
    ),
    Capability(
        "LEGAL_INGEST",
        "legal-evidence",
        "Take a file or folder of documents into a matter",
        _ingest,
        "add the bundle folder to the matter",
    ),
    Capability(
        "LEGAL_RUN_START",
        "legal-run",
        "Start a case-preparation run on a matter",
        _run_start,
        "start the analysis",
    ),
    Capability(
        "LEGAL_RUN_STATUS",
        "legal-run",
        "Where a run stands and what is holding it",
        _run_status,
        "how is the run doing?",
    ),
    Capability(
        "LEGAL_HOLDS",
        "legal-verification",
        "List the holds open on a run",
        _holds,
        "what is on hold?",
    ),
    Capability(
        "LEGAL_REPORT_PATH",
        "legal-run",
        "Where the current report file is and whether it is approved",
        _report_path,
        "where is the report?",
    ),
    Capability(
        "LEGAL_AUDIT_VERIFY",
        "legal-audit",
        "Verify the audit chain",
        _audit_verify,
        "verify the audit trail",
    ),
    Capability(
        "LEGAL_EVIDENCE_PACK",
        "legal-audit",
        "Export the evidence pack for a run",
        _evidence_pack,
        "export the evidence pack",
    ),
)

# Named so their absence is checked by a test, not left to chance.
DECISIONS_NOT_EXPOSED = (
    "hold.resolve",
    "verification.record",
    "report.approve",
    "report.send",
    "workflow.restart",
    "matter.close",
)


def dispatch(sv: Services, name: str, actor_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Run one capability for a named user. Refusals come back as data, not exceptions."""
    capability = next((c for c in CAPABILITIES if c.name == name), None)
    if capability is None:
        text = f"{name} is not an ELI Legal capability."
        return {"ok": False, "error": "unknown_capability", "content": text, "response": text}
    try:
        return capability.handler(sv, actor_id, args)
    except EliLegalError as exc:
        text = f"Refused: {exc}"
        return {"ok": False, "error": type(exc).__name__, "content": text, "response": text}
