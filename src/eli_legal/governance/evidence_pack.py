"""Evidence pack: everything needed to account for one run, in one hashed bundle.

The pack is what an auditor, a regulator or a challenged party would ask for: what was read, what
was found and from where, which checks ran and what they returned, who decided what, which
versions of model, prompt, tool and policy were in use, and the audit trail that ties it together.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.application.container import AppContext
from eli_legal.domain.models import (
    Claim,
    Document,
    Hold,
    HumanReview,
    Incident,
    Issue,
    Report,
    Run,
    RunStep,
    VerificationResult,
    VerificationTask,
    utcnow,
)
from eli_legal.domain.release import ReleasePackage
from eli_legal.governance.completeness import check_run_completeness
from eli_legal.legal.frameworks import pack_to_dict
from eli_legal.persistence import codec


def _write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _rows(items: Iterable[Any]) -> list[Any]:
    return [codec.to_jsonable(i) for i in items]


def export_evidence_pack(
    ctx: AppContext, matter_id: str, run_id: str, *, actor_id: str, out_dir: str | Path
) -> Path:
    matter = ctx.matter_for(matter_id, actor_id, "evidence.export")
    mid = matter.matter_id
    run = ctx.store.require(Run, mid, run_id)
    target = Path(out_dir) / f"evidence_pack_{run_id}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    documents = ctx.store.list(Document, mid)
    # The pack holds what its exporter may read. Someone who audits a matter without being
    # cleared for its material gets every record, hash and decision, with content withheld.
    seen = ctx.authorizer().visibility(matter, actor_id)
    claims = [seen.claim(c) for c in ctx.store.list(Claim, mid, run_id=run_id)]
    verifications = ctx.store.list(VerificationResult, mid, run_id=run_id)
    steps = ctx.store.list(RunStep, mid, run_id=run_id)
    holds = ctx.holds.all_holds(mid, run_id)
    reviews = ctx.store.list(HumanReview, mid, run_id=run_id)
    events = list(ctx.audit.events(matter_id=mid, run_id=run_id))
    chain = ctx.audit.report()
    completeness = check_run_completeness(
        events=events, steps=steps, holds=holds, reviews=reviews, verifications=verifications
    )

    _write(target / "run.json", codec.to_jsonable(run))
    _write(
        target / "matter.json",
        {
            "matter_id": mid,
            "profile": matter.profile.value,
            "jurisdiction": matter.jurisdiction,
            "governing_law": matter.governing_law,
            "relevant_date": matter.relevant_date.isoformat() if matter.relevant_date else None,
            "reviewers": sorted(matter.reviewer_user_ids),
            "approved_sources": sorted(matter.approved_source_ids),
        },
    )
    # The manifest proves what was read without reproducing it: hashes and sizes, not content.
    _write(
        target / "document_manifest.json",
        [
            {
                "document_id": d.document_id,
                "sha256": d.sha256,
                "size_bytes": d.size_bytes,
                "media_type": d.media_type,
                "doc_type": d.doc_type.value,
                "status": d.status.value,
                "access_scope": d.access_scope.value,
                "ingested_by": d.ingested_by,
                "ingested_at": d.ingested_at.isoformat(),
                "waived_by": d.waived_by,
                "injection_flags": d.injection_flags,
            }
            for d in documents
        ],
    )
    # The law and standards packages the run was prepared under, each in full and with its standing.
    applied = []
    for pack_id, fingerprint in sorted(run.framework_versions.items()):
        pack = ctx.frameworks.get(pack_id)
        current = pack is not None and pack.fingerprint == fingerprint
        applied.append(
            {
                "id": pack_id,
                "fingerprint": fingerprint,
                "unchanged_since_run": current,
                "standing": ctx.frameworks.state(pack).why if pack is not None else "removed",
                "pack": pack_to_dict(pack) if pack is not None and current else None,
            }
        )
    _write(target / "frameworks.json", applied)
    _write(target / "steps.json", _rows(steps))
    _write(target / "issues.json", _rows(ctx.store.list(Issue, mid, run_id=run_id)))
    _write(target / "claims.json", _rows(claims))
    _write(target / "verifications.json", _rows(verifications))
    _write(target / "holds.json", _rows(holds))
    _write(target / "tasks.json", _rows(ctx.store.list(VerificationTask, mid, run_id=run_id)))
    _write(target / "reviews.json", _rows(reviews))
    _write(target / "incidents.json", _rows(ctx.store.list(Incident, mid, run_id=run_id)))
    _write(
        target / "releases.json",
        [
            {k: v for k, v in codec.to_jsonable(r).items() if k != "recipients"}
            | {"recipient_ids": [x.recipient_id for x in r.recipients]}
            for r in ctx.store.list(ReleasePackage, mid, run_id=run_id)
        ],
    )
    (target / "audit_events.jsonl").write_text(
        "\n".join(json.dumps(e, sort_keys=True, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    _write(
        target / "audit_verification.json",
        {
            "chain_ok": chain.ok,
            "chain_error": chain.error,
            "events_in_ledger": chain.count,
            "key_ids": list(chain.key_ids),
            "run_events": len(events),
            "run_record_complete": completeness.ok,
            "gaps": completeness.gaps,
            "checkpoint": json.loads(ctx.audit.checkpoint().to_json()) if chain.ok else None,
        },
    )
    for report in ctx.store.list(Report, mid, run_id=run_id):
        for ref in (report.artifact_ref, report.data_ref):
            source = Path(ref)
            if not source.is_file():
                continue
            if seen.sees_everything:
                shutil.copyfile(source, target / source.name)
            else:
                raw = source.read_bytes()
                _write(
                    target / f"{source.name}.withheld.json",
                    {
                        "file": source.name,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw),
                        "withheld": "the exporter's role on the matter does not include all of "
                        "its material; the hash identifies the file without disclosing it",
                    },
                )
    _write(
        target / "configuration.json",
        {
            "eli_legal_version": __version__,
            "policy_version": ctx.policy.version,
            "workflow": {"id": ctx.workflow.workflow_id, "version": ctx.workflow.version},
            "jurisdiction_packs": [
                {"code": p.code, "status": p.pack_status, "validated_by": p.validated_by}
                for p in ctx.jurisdictions.for_matter(matter)
            ],
            "sources": [
                {
                    "source_id": s.source_id,
                    "approved": s.approved,
                    "approved_by": s.approved_by,
                    "licence": s.licence,
                    "treatment_semantics": s.treatment_semantics,
                }
                for s in ctx.sources.list()
                if s.source_id in matter.approved_source_ids
            ],
        },
    )

    files = sorted(p for p in target.iterdir() if p.is_file())
    manifest = {
        "exported_at": utcnow().isoformat(),
        "exported_by": actor_id,
        "matter_id": mid,
        "run_id": run_id,
        "content": "full" if seen.sees_everything else "withheld where the exporter is not cleared",
        "exporter_role_on_matter": seen.role,
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    _write(target / "MANIFEST.json", manifest)
    ctx.log(
        "evidence_exported",
        actor_id=actor_id,
        matter_id=mid,
        run_id=run_id,
        action="evidence.export",
        subject_id=run_id,
        outcome="exported",
        object_type="evidence_pack",
        output_hash=hashlib.sha256((target / "MANIFEST.json").read_bytes()).hexdigest(),
        payload={"files": len(files), "chain_ok": chain.ok, "record_complete": completeness.ok},
    )
    return target


def list_holds(ctx: AppContext, matter_id: str, run_id: str) -> list[Hold]:
    return ctx.holds.all_holds(matter_id, run_id)
