from eli_legal.adapters.local.hmac_audit import HmacAuditLedger
from eli_legal.application.release_service import ReleaseService
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.models import Matter, Run
from eli_legal.domain.release import Recipient
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.rbac import ROLE_SUPERVISING_SOLICITOR, RoleBindings


def test_release_preparation_hashes_exact_approved_artifact(tmp_path):
    key = tmp_path / "audit.key"
    key.write_bytes(b"x" * 64)
    key.chmod(0o600)
    ledger = HmacAuditLedger(tmp_path / "audit.db", key)

    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="supervisor")
    run = Run(matter_id=matter.matter_id, initiated_by="supervisor")
    run.status = RunStatus.APPROVED_FOR_RELIANCE
    bindings = RoleBindings()
    bindings.bind("supervisor", ROLE_SUPERVISING_SOLICITOR)
    report = tmp_path / "report.txt"
    report.write_text("approved report version", encoding="utf-8")

    service = ReleaseService(authorizer=MatterAuthorizer(bindings), audit=ledger)
    package = service.prepare(
        matter=matter,
        run=run,
        actor_id="supervisor",
        report_id="rep1",
        report_version="1",
        report_artifact=report,
        approved_review_id="rev1",
        recipients=(Recipient("r1", "Counsel", "x@example.invalid", authorised_for_matter=True),),
    )

    assert len(package.report_hash) == 64
    assert ledger.verify_chain()
