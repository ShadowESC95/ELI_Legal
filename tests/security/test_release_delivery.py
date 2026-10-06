import pytest

from eli_legal.adapters.local.hmac_audit import HmacAuditLedger
from eli_legal.adapters.local.outbox import OutboxDeliveryAdapter
from eli_legal.application.delivery_service import DeliveryService
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import Matter, Run
from eli_legal.domain.release import Recipient, ReleaseApproval, ReleasePackage
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.rbac import ROLE_SUPERVISING_SOLICITOR, RoleBindings


def _service(tmp_path):
    key = tmp_path / "audit.key"
    key.write_bytes(b"x" * 64)
    key.chmod(0o600)
    ledger = HmacAuditLedger(tmp_path / "audit.db", key)
    bindings = RoleBindings()
    bindings.bind("supervisor", ROLE_SUPERVISING_SOLICITOR)
    return DeliveryService(
        authorizer=MatterAuthorizer(bindings),
        audit=ledger,
        delivery=OutboxDeliveryAdapter(tmp_path / "outbox"),
    )


def test_report_delivery_requires_human_approved_matching_recipients(tmp_path):
    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="supervisor")
    run = Run(matter_id=matter.matter_id, initiated_by="supervisor")
    run.status = RunStatus.APPROVED_FOR_RELIANCE
    recipient = Recipient("r1", "Counsel", "counsel@example.invalid", authorised_for_matter=True)
    package = ReleasePackage(
        matter_id=matter.matter_id,
        run_id=run.run_id,
        report_id="rep1",
        report_version="1",
        report_hash="abc123",
        artifact_ref="artifacts/runs/rep1.pdf",
        approved_review_id="rev1",
        prepared_by="supervisor",
        recipients=(recipient,),
    )
    approval = ReleaseApproval(
        release_id=package.release_id,
        approver_user_id="supervisor",
        approved_review_id=package.approved_review_id,
        report_hash=package.report_hash,
        recipient_ids=("r1",),
    )

    receipts = _service(tmp_path).distribute(
        matter=matter,
        run=run,
        package=package,
        approval=approval,
        actor_id="supervisor",
    )
    assert receipts[0].status == "staged"


def test_unauthorised_recipient_is_blocked(tmp_path):
    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="supervisor")
    run = Run(matter_id=matter.matter_id, initiated_by="supervisor")
    run.status = RunStatus.APPROVED_FOR_RELIANCE
    recipient = Recipient("r1", "Unknown", "unknown@example.invalid", authorised_for_matter=False)
    package = ReleasePackage(
        matter_id=matter.matter_id,
        run_id=run.run_id,
        report_id="rep1",
        report_version="1",
        report_hash="abc123",
        artifact_ref="artifacts/runs/rep1.pdf",
        approved_review_id="rev1",
        prepared_by="supervisor",
        recipients=(recipient,),
    )
    approval = ReleaseApproval(
        release_id=package.release_id,
        approver_user_id="supervisor",
        approved_review_id=package.approved_review_id,
        report_hash=package.report_hash,
        recipient_ids=("r1",),
    )
    with pytest.raises(VerificationGateFailed):
        _service(tmp_path).distribute(
            matter=matter,
            run=run,
            package=package,
            approval=approval,
            actor_id="supervisor",
        )
