"""Make everything in the application larger or smaller, for anyone who finds it hard to read.

Ctrl and + (or =) zooms in, Ctrl and - zooms out, Ctrl and 0 returns to normal size, and Ctrl
with the mouse wheel does the same anywhere: in every page, table, form and dialog. The level is
remembered for the next time.

The wheel is listened for on ELI Legal's own widgets, picked up as they appear, never on the
whole application: a listener on the whole application crashes Qt's browser engine (PySide6
6.12), which ELI v3, hosting ELI Legal in its own process, may be using.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsView, QLabel, QTableWidget, QToolTip, QWidget

from eli_legal.gui import theme

ROW_HEIGHT = 26  # a table row at normal size
_KEY = "view/zoom"


class Zoom(QObject):
    changed = Signal(float)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        try:
            saved = float(QSettings("ELI", "ELI Legal").value(_KEY, 1.0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            saved = 1.0
        self.level = self._clamp(saved)
        self.apply()
        self.sweep = QTimer(self)
        self.sweep.timeout.connect(self.watch_new)
        self.sweep.start(1000)
        self.watch_new()

    @staticmethod
    def _clamp(level: float) -> float:
        return round(min(theme.ZOOM_MAX, max(theme.ZOOM_MIN, level)), 2)

    def set(self, level: float) -> None:
        level = self._clamp(level)
        if level == self.level:
            return
        self.level = level
        QSettings("ELI", "ELI Legal").setValue(_KEY, level)
        self.apply()

    def zoom_in(self) -> None:
        self.set(self.level + theme.ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set(self.level - theme.ZOOM_STEP)

    def reset(self) -> None:
        self.set(1.0)

    def apply(self) -> None:
        font = QFont(self.app.font())
        font.setPointSizeF(theme.BASE_POINTS * self.level)
        self.app.setFont(font)  # for windows opened from now on
        QToolTip.setFont(font)
        # Open windows pass it on to every widget in them (gui/app.py lets fonts propagate under
        # the stylesheet). In an application someone else created, such as ELI v3's, that
        # cannot be switched on, so each widget is given the font itself.
        propagates = self.app.testAttribute(
            Qt.ApplicationAttribute.AA_UseStyleSheetPropagationInWidgetStyles
        )
        for window in self.app.topLevelWidgets():
            window.setFont(font)
        for widget in self.app.allWidgets():
            if not propagates and not widget.property("role"):
                widget.setFont(font)
            self.fit(widget)
        self.changed.emit(self.level)

    def size_role(self, widget: QWidget) -> None:
        """A label larger or smaller than the text around it: titles, the sidebar."""
        points = theme.ROLE_POINTS.get(str(widget.property("role") or ""))
        if points:
            font = QFont(widget.font())
            font.setPointSizeF(points * self.level)
            widget.setFont(font)

    def fit(self, widget: QWidget) -> None:
        """Size what a stylesheet does not reach: table rows, set column widths, drawings."""
        if isinstance(widget, QLabel):
            self.size_role(widget)
        elif isinstance(widget, QTableWidget):
            widget.verticalHeader().setDefaultSectionSize(round(ROW_HEIGHT * self.level))
            widths = widget.property("fitWidths")
            if widths:
                for column, width in enumerate(widths):
                    if width:
                        widget.setColumnWidth(column, round(int(width) * self.level))
        elif isinstance(widget, QGraphicsView) and widget.property("zooms"):
            widget.setTransform(QTransform.fromScale(self.level, self.level))

    def watch_new(self) -> None:
        """Listen for Ctrl and the wheel on every widget that has appeared since last time."""
        for widget in self.app.allWidgets():
            if widget.property("zoomWatched"):
                continue
            kind = widget.metaObject().className()
            if "WebEngine" in kind or "Quick" in kind:
                continue  # the browser engine's own widgets are never touched
            widget.setProperty("zoomWatched", True)
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Type.Wheel:
            modifiers = event.modifiers()  # type: ignore[attr-defined]
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()  # type: ignore[attr-defined]
                if delta > 0:
                    self.zoom_in()
                elif delta < 0:
                    self.zoom_out()
                return True
        return False

    def keys(self, window: QWidget) -> None:
        """The keyboard shortcuts, working wherever the focus is in this window."""
        for sequence, slot in (
            (QKeySequence.StandardKey.ZoomIn, self.zoom_in),
            (QKeySequence("Ctrl+="), self.zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self.zoom_out),
            (QKeySequence("Ctrl+0"), self.reset),
        ):
            shortcut = QShortcut(QKeySequence(sequence), window)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)
        self.watch_new()


_zoom: Zoom | None = None


def install(app: QApplication) -> Zoom:
    global _zoom
    if _zoom is None or _zoom.app is not app:
        _zoom = Zoom(app)
    return _zoom


def current() -> Zoom | None:
    return _zoom


def level() -> float:
    return _zoom.level if _zoom is not None else 1.0
