"""Small building blocks shared by every tab."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eli_legal.gui import theme

ID_ROLE = Qt.ItemDataRole.UserRole


def label(
    text: str = "", role: str = "", *, wrap: bool = False, selectable: bool = False
) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
        from eli_legal.gui import zoom

        control = zoom.current()
        if control is not None:
            control.size_role(widget)  # a title or sidebar label, at the current zoom
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, on_click: Any = None, *, kind: str = "", tip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setProperty("kind", kind)
    if tip:
        widget.setToolTip(tip)
    if on_click is not None:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def card(title: str, *widgets: QWidget, layout: str = "v") -> QGroupBox:
    box = QGroupBox(title.upper())
    inner: QVBoxLayout | QHBoxLayout = QVBoxLayout(box) if layout == "v" else QHBoxLayout(box)
    for widget in widgets:
        inner.addWidget(widget)
    return box


class FlowLayout(QLayout):
    """Widgets side by side that wrap onto the next line when the window is too narrow, so a
    row of buttons never forces the window wider than the screen."""

    def __init__(
        self, parent: QWidget | None = None, spacing: int = 6, *, align_right: bool = False
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._gap = spacing
        self._right = align_right
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt's name
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = sum(i.sizeHint().width() for i in self._items if not i.isEmpty())
        width += self._gap * max(0, len(self._items) - 1)
        height = max((i.sizeHint().height() for i in self._items), default=0)
        return QSize(width, height)

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins: QMargins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect: QRect, *, move: bool) -> int:
        lines: list[list[QLayoutItem]] = [[]]
        x = rect.x()
        for item in self._items:
            if item.isEmpty():
                continue
            width = item.sizeHint().width()
            if x + width > rect.right() + 1 and lines[-1]:
                lines.append([])
                x = rect.x()
            lines[-1].append(item)
            x += width + self._gap
        y = rect.y()
        for items in lines:
            if not items:
                continue
            used = sum(i.sizeHint().width() for i in items) + self._gap * (len(items) - 1)
            x = rect.right() + 1 - used if self._right else rect.x()
            height = max(i.sizeHint().height() for i in items)
            for item in items:
                hint = item.sizeHint()
                if move:
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                x += hint.width() + self._gap
            y += height + self._gap
        return max(0, y - self._gap - rect.y())


def row(*widgets: QWidget | None, stretch_last: bool = False) -> QWidget:
    """Widgets side by side; ``None`` is elastic space. A row with a field that stretches stays
    on one line; any other row (buttons, mostly) wraps when the window is narrow."""
    holder = QWidget()
    grows = (QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
    if not stretch_last and not any(
        w is not None and w.sizePolicy().horizontalPolicy() in grows for w in widgets
    ):
        flow = FlowLayout(holder)
        for widget in widgets:
            if widget is not None:
                flow.addWidget(widget)
        policy = holder.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        holder.setSizePolicy(policy)
        return holder
    inner = QHBoxLayout(holder)
    inner.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        if widget is None:
            inner.addStretch(1)
        else:
            inner.addWidget(widget, 1 if stretch_last and index == len(widgets) - 1 else 0)
    return holder


def table(headers: Sequence[str], *, stretch: int = -1) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(list(headers))
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(False)
    widget.verticalHeader().setVisible(False)
    from eli_legal.gui import zoom

    widget.verticalHeader().setDefaultSectionSize(round(zoom.ROW_HEIGHT * zoom.level()))
    # Every heading that names a term explains it when the pointer rests on it.
    from eli_legal.domain import glossary

    for column, heading in enumerate(headers):
        tip = glossary.tooltip(heading)
        if tip:
            header_item = widget.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(tip)
    header = widget.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(stretch < 0)
    if stretch >= 0:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return widget


def fill(
    widget: QTableWidget,
    rows: Sequence[Sequence[Any]],
    *,
    ids: Sequence[str] | None = None,
    state_columns: Sequence[int] = (),
    keep_selection: bool = True,
) -> None:
    """Replace a table's rows. Cells in ``state_columns`` are coloured by their state word."""
    selected = selected_id(widget) if keep_selection else ""
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            text = "" if value is None else str(value)
            item = QTableWidgetItem(text)
            item.setToolTip(text if len(text) > 40 else "")
            if c in state_columns:
                item.setForeground(
                    QBrush(QColor(theme.colour_for(text.split(":")[0].split(" ")[0])))
                )
            if c == 0 and ids is not None:
                item.setData(ID_ROLE, ids[r])
            widget.setItem(r, c, item)
    if selected and ids:
        for r, record_id in enumerate(ids):
            if record_id == selected:
                widget.selectRow(r)
                break


def selected_id(widget: QTableWidget) -> str:
    items = widget.selectedItems()
    if not items:
        return ""
    first = widget.item(items[0].row(), 0)
    return str(first.data(ID_ROLE) or "") if first is not None else ""


def fit(widget: QTableWidget, widths: Sequence[int]) -> None:
    """Column widths at normal size; they grow and shrink with the zoom."""
    from eli_legal.gui import zoom

    widget.setProperty("fitWidths", list(widths))
    for column, width in enumerate(widths):
        if width:
            widget.setColumnWidth(column, round(width * zoom.level()))


class ReasonDialog(QDialog):
    """Every decision carries its reasons. This asks for them and will not accept a shrug."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        prompt: str,
        *,
        minimum: int = 10,
        extra: Sequence[tuple[str, QWidget]] = (),
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.minimum = minimum
        layout = QVBoxLayout(self)
        layout.addWidget(label(prompt, wrap=True))
        if extra:
            form = QFormLayout()
            for caption, widget in extra:
                form.addRow(caption, widget)
            layout.addLayout(form)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            placeholder or "Your reasons (they are recorded with your name)"
        )
        self.text.setMinimumHeight(110)
        layout.addWidget(self.text)
        self.hint = label("", "muted")
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.text.textChanged.connect(self._check)
        self._check()

    def _check(self) -> None:
        missing = self.minimum - len(self.reason())
        self._ok.setEnabled(missing <= 0)
        self.hint.setText(f"{missing} more character(s) needed" if missing > 0 else "")

    def reason(self) -> str:
        return " ".join(self.text.toPlainText().split())

    @classmethod
    def ask(cls, parent: QWidget, title: str, prompt: str, **kwargs: Any) -> str | None:
        dialog = cls(parent, title, prompt, **kwargs)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        reason = dialog.reason()
        # The caller reads its own fields (a tick box, a choice, a date) once this returns, and
        # by then the dialog may be gone, taking its children with it. They are taken out of it
        # first, so they live as long as the caller holds them.
        for _caption, widget in kwargs.get("extra", ()):
            widget.hide()
            widget.setParent(None)
        dialog.deleteLater()
        return reason if accepted else None


def chip(text: str, colour: str = theme.TEXT) -> QLabel:
    widget = label(text, "chip")
    widget.setStyleSheet(f"color: {colour};")
    return widget


def set_chip(widget: QLabel, text: str, colour: str) -> None:
    widget.setText(text)
    widget.setStyleSheet(f"color: {colour};")
