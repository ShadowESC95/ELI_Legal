from __future__ import annotations

import json
import shutil
from pathlib import Path

from eli_legal.domain.release import DeliveryReceipt, ReleasePackage
from eli_legal.security.sealed import SealedFiles


class OutboxDeliveryAdapter:
    """Safe default: stage the approved report and its manifest. Nothing is sent anywhere.

    A person, or a separately approved mail integration, takes it from the outbox. The system
    itself never contacts a party.
    """

    def __init__(
        self, root: str | Path = "./artifacts/outbox", files: SealedFiles | None = None
    ) -> None:
        self.root = Path(root)
        self.files = files  # staged copies are sealed like every case file

    def _copy(self, matter_id: str, source: Path, target: Path) -> None:
        if self.files is None:
            shutil.copyfile(source, target)
        else:
            self.files.write(matter_id, target, self.files.read(matter_id, source))

    def _put(self, matter_id: str, target: Path, data: bytes) -> None:
        if self.files is None:
            target.write_bytes(data)
        else:
            self.files.write(matter_id, target, data)

    def send(self, package: ReleasePackage) -> list[DeliveryReceipt]:
        if package.status != "approved_for_delivery":
            raise RuntimeError("release package has not passed the release gate")

        target = self.root / package.matter_id / package.release_id
        target.mkdir(parents=True, exist_ok=True)
        source = Path(package.artifact_ref)
        if source.is_file():
            self._copy(package.matter_id, source, target / source.name)
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
        self._put(
            package.matter_id,
            target / "release_manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
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
