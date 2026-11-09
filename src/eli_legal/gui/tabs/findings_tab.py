from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QSplitter

from eli_legal.domain import plain
from eli_legal.domain.enums import ClaimKind, ClaimStatus, VerificationStatus
from eli_legal.domain.models import Claim
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import (
    ReasonDialog,
    button,
    card,
    fill,
    fit,
    label,
    row,
    selected_id,
    table,
)
from eli_legal.security import access


class FindingsTab(Tab):
    title = "🔎 Findings"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.kind = QComboBox()
        self.kind.addItem("Every kind", "")
        for kind in ClaimKind:
            self.kind.addItem(plain.kind(kind), kind.value)
        self.status = QComboBox()
        self.status.addItem("Any status", "")
        for status in ClaimStatus:
            self.status.addItem(plain.state(status), status.value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by words in the finding or its authority")
        for widget in (self.kind, self.status):
            widget.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter)
        self.count = label("", "muted")
        self.list = table(
            ["Kind", "Status", "Stated by", "Date", "Authority", "Finding (verbatim)"]
        )
        self.list.itemSelectionChanged.connect(self._show)
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.checks = table(["Check", "Result", "Decided by", "Detail"])
        self.why = label("", wrap=True, selectable=True)
        self._claims: dict[str, Claim] = {}
        self.root.addWidget(
            row(self.kind, self.status, self.search, self.count, stretch_last=False)
        )
        lower = QSplitter()
        lower.addWidget(card("Where it comes from", self.source))
        lower.addWidget(
            card(
                "Checks on this finding",
                self.checks,
                self.why,
                row(
                    button(
                        "Record a check by hand…",
                        self._verify,
                        tip="You checked it yourself; say what you checked and where.",
                    ),
                    button("Take out of reliance…", self._exclude, kind="danger"),
                    None,
                ),
            )
        )
        lower.setSizes([520, 640])
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(card("Findings of this run", self.list))
        split.addWidget(lower)
        split.setSizes([360, 300])
        self.root.addWidget(split, 1)

    def refresh(self) -> None:
        claims: list[Claim] = []
        if self.mid and self.rid:
            claims = (
                self.session.attempt(
                    self,
                    lambda: self.sv.verification.claims(self.mid, self.rid, actor_id=self.actor),
                    quiet=True,
                )
                or []
            )
        self._claims = {c.claim_id: c for c in claims}
        self._filter()

    def _filter(self) -> None:
        matter = self.session.matter
        names = {p.party_id: p.name for p in matter.parties} if matter else {}
        kind, status, words = (
            self.kind.currentData(),
            self.status.currentData(),
            self.search.text().lower().split(),
        )
        shown = [
            c
            for c in self._claims.values()
            if (not kind or c.kind.value == kind)
            and (not status or c.status.value == status)
            and all(w in f"{c.text} {c.citation or ''}".lower() for w in words)
        ]
        fill(
            self.list,
            [
                [
                    plain.kind(c.kind),
                    plain.state(c.status),
                    names.get(c.party_id or "", "—"),
                    c.event_date.isoformat() if c.event_date else "",
                    c.citation or "",
                    c.text,
                ]
                for c in shown
            ],
            ids=[c.claim_id for c in shown],
            state_columns=[1],
        )
        fit(self.list, [190, 90, 170, 90, 190, 0])
        self.count.setText(f"{len(shown)} of {len(self._claims)} shown")
        self._show()

    def _show(self) -> None:
        claim = self._claims.get(selected_id(self.list))
        if claim is None:
            self.source.clear()
            self.why.setText("")
            fill(self.checks, [])
            return
        if access.is_withheld(claim.text):
            self.source.setPlainText(
                f"{claim.text}.\n\nYour role on this matter does not include the material this "
                "finding rests on, so its words and source are withheld from you."
            )
            self.why.setText(f"<b>Status:</b> {plain.state(claim.status)}")
            fill(self.checks, [])
            return
        documents = {
            d.document_id: d
            for d in self.session.attempt(
                self, lambda: self.sv.matters.documents(self.mid, self.actor), quiet=True
            )
            or []
        }
        parts = [f"“{claim.text}”", ""]
        for link in claim.evidence:
            if link.target_type == "document":
                document = documents.get(link.target_id)
                name = (document.title or document.filename) if document else link.target_id
                parts.append(f"Document: {name} — {link.locator}")
            else:
                authority = self.sv.ctx.store.get_authority(link.target_id)
                parts.append(
                    f"Authority: {authority.citation if authority else link.target_id} — {link.locator}"
                )
            parts.append(f"   “{link.quote}”")
        if claim.depends_on:
            parts.append("")
            parts.append("Rests on:")
            for dependency in claim.depends_on:
                other = self._claims.get(dependency)
                parts.append(
                    f"   [{plain.state(other.status) if other else 'missing'}] "
                    f"{other.text if other else dependency}"
                )
        parts.append("")
        parts.append(f"Produced by: {claim.origin}")
        self.source.setPlainText("\n".join(parts))
        results = (
            self.session.attempt(
                self,
                lambda: self.sv.verification.results_for(
                    self.mid, claim.claim_id, actor_id=self.actor
                ),
                quiet=True,
            )
            or []
        )
        fill(
            self.checks,
            [
                [
                    plain.check_name(r.verification_type),
                    plain.state(r.status),
                    r.verifier + (" (overrides the system)" if r.override else ""),
                    plain.check_result(r.verification_type, r.status, r.detail)
                    + (f" Reason given: {r.reason}" if r.reason else ""),
                ]
                for r in sorted(results, key=lambda r: r.created_at)
            ],
            state_columns=[1],
            keep_selection=False,
        )
        fit(self.checks, [190, 90, 170, 0])
        self.why.setText(
            f"<b>Status:</b> {plain.state(claim.status)}"
            + (f" — {claim.status_reason}" if claim.status_reason else "")
        )

    def _verify(self) -> None:
        claim = self._claims.get(selected_id(self.list))
        if claim is None:
            return
        check = QComboBox()
        for key in ("citation", "current_law", "proposition", "evidence_support", "provenance"):
            check.addItem(plain.check_name(key), key)
        result = QComboBox()
        result.addItem("Verified — I checked and it holds", VerificationStatus.VERIFIED.value)
        result.addItem("Failed — I checked and it does not hold", VerificationStatus.FAILED.value)
        reason = ReasonDialog.ask(
            self,
            "Record a check by hand",
            "Say what you checked and where. If the system found this check failed, recording it as verified is an override: it needs that permission and is shown in the report.",
            extra=[("Check", check), ("Result", result)],
        )
        if reason:
            self.session.decide(
                self,
                "record this check in your name",
                lambda: self.sv.verification.record_human_result(
                    self.mid,
                    claim.claim_id,
                    actor_id=self.actor,
                    verification_type=check.currentData(),
                    status=VerificationStatus(result.currentData()),
                    reason=reason,
                ),
            )

    def _exclude(self) -> None:
        claim = self._claims.get(selected_id(self.list))
        if claim is None:
            return
        hold = next(
            (
                h
                for h in self.sv.ctx.holds.open_holds(self.mid, self.rid)
                if h.subject_id == claim.claim_id
            ),
            None,
        )
        if hold is None:
            self.session.attempt(
                self,
                lambda: (_ for _ in ()).throw(
                    ValueError(
                        "This finding is not on hold. Only a held finding can be taken out of reliance here."
                    )
                ),
            )
            return
        reason = ReasonDialog.ask(
            self,
            "Take out of reliance",
            "The finding stays visible in the report under “Findings not to be relied on”, with your reason.",
        )
        if reason:
            self.session.decide(
                self,
                "exclude this finding",
                lambda: self.sv.holds.resolve(
                    self.mid, hold.hold_id, actor_id=self.actor, action="exclude", reason=reason
                ),
            )
