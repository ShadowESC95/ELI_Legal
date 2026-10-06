from __future__ import annotations

from typing import Protocol

from eli_legal.domain.release import DeliveryReceipt, ReleasePackage


class DeliveryPort(Protocol):
    def send(self, package: ReleasePackage) -> list[DeliveryReceipt]: ...
