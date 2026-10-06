from __future__ import annotations

import json
import shutil
from pathlib import Path

from eli_legal.domain.release import DeliveryReceipt, ReleasePackage


class OutboxDeliveryAdapter:
    """Safe default: stage the approved report and its manifest. Nothing is sent anywhere.

    A person, or a separately approved mail integration, takes it from the outbox. The system
    itself never contacts a party.
    """

    def __init__(self, root: str | Path = "./artifacts/outbox") -> None:
        self.root = Path(root)

    def send(self, package: ReleasePackage) -> list[DeliveryReceipt]:
        if package.status != "approved_for_delivery":
            raise RuntimeError("release package has not passed the release gate")

        target = self.root / package.matter_id / package.release_id
        target.mkdir(parents=True, exist_ok=True)
        source = Path(package.artifact_ref)
        if source.is_file():
            shutil.copyfile(source, target / source.name)
        manifest = {
            "release_id": package.release_id,
            "matter_id": package.matter_id,
            "run_id": package.run_id,
            "report_id": package.report_id,
            "report_version": package.report_version,
            "report_hash": package.report_hash,
            "report_file": source.name,
            "classification": package.classification,
            "approved_by": package.approved_by,
            "recipients": [
                {
                    "recipient_id": recipient.recipient_id,
                    "display_name": recipient.display_name,
                    "channel": recipient.channel,
                }
                for recipient in package.recipients
            ],
        }
        (target / "release_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return [
            DeliveryReceipt(
                release_id=package.release_id,
                recipient_id=recipient.recipient_id,
                channel=recipient.channel,
                status="staged",
                detail=str(target / "release_manifest.json"),
            )
            for recipient in package.recipients
        ]
