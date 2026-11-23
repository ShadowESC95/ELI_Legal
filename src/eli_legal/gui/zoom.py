"""Make everything in the application larger or smaller, for anyone who finds it hard to read.

Ctrl and + (or =) zooms in, Ctrl and - zooms out, Ctrl and 0 returns to normal size, and Ctrl
with the mouse wheel does the same anywhere: in every page, table, form and dialog. The level is
remembered for the next time.

The wheel is listened for only where it arrives: in each window, and on the scrolling areas,
lists and number boxes that take the wheel for themselves (the rest pass it up to their window).
Not on the whole application, whose every event would then pass through Python (and which
crashes Qt's browser engine in PySide6 6.12, which ELI v3, hosting ELI Legal, may use), and not
on every widget, which in 0.8.1 slowed the window down while a run was under way.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTransform
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QGraphicsView,
    QLabel,
    QTableWidget,
    QToolTip,
    QWidget,
)

from eli_legal.gui import theme

ROW_HEIGHT = 26  # a table row at normal size


def _prop(widget: QObject, name: str) -> object:
    """A widget's property, or None if it has none, without asking Qt for a missing one.

    PySide6 6.12 returns a missing property as None without counting the reference; on
    Python 3.10 and 3.11, where None can be freed, enough of those calls end the program
    ("Fatal Python error: none_dealloc"). Python 3.12 and later are not affected."""
    key = name.encode()
    if any(bytes(n.data()) == key for n in widget.dynamicPropertyNames()):
        return widget.property(name)
    return None


_KEY = "view/zoom"


def remembered() -> QSettings:
    """The person's own settings for the window: its size, and where they put its dividers."""
    return _remembered()


def _remembered() -> QSettings:
    """Where the size a person chose is kept: their own settings, or the file named in
    ELI_LEGAL_GUI_SETTINGS, which the tests use so that they never change a real person's."""
    path = os.environ.get("ELI_LEGAL_GUI_SETTINGS", "")
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings("ELI", "ELI Legal")


class Zoom(QObject):
    changed = Signal(float)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        try:
            saved = float(_remembered().value(_KEY, 1.0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            saved = 1.0
        self.level = self._clamp(saved)
        self.apply()
        self.sweep = QTimer(self)
        self.sweep.timeout.connect(self.watch_new)
        self.sweep.start(3000)
        self.watch_new()

    @staticmethod
    def _clamp(level: float) -> float:
        return round(min(theme.ZOOM_MAX, max(theme.ZOOM_MIN, level)), 2)

    def set(self, level: float) -> None:
        level = self._clamp(level)
        if level == self.level:
            return
        self.level = level
        _remembered().setValue(_KEY, level)
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
            if not propagates and not _prop(widget, "role"):
                widget.setFont(font)
            self.fit(widget)
        self.changed.emit(self.level)

    def size_role(self, widget: QWidget) -> None:
        """A label larger or smaller than the text around it: titles, the sidebar."""
        points = theme.ROLE_POINTS.get(str(_prop(widget, "role") or ""))
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
            widths = _prop(widget, "fitWidths")
            if isinstance(widths, (list, tuple)):
                for column, width in enumerate(widths):
                    if width:
                        widget.setColumnWidth(column, round(int(width) * self.level))
        elif isinstance(widget, QGraphicsView) and _prop(widget, "zooms"):
            widget.setTransform(QTransform.fromScale(self.level, self.level))

    def watch_new(self) -> None:
        """Listen for Ctrl and the wheel where it arrives, on what has appeared since last time:
        each window, and each scrolling area (its viewport), list and number box."""
        for widget in self.app.allWidgets():
            # A widget on its way out (a window closing, a part replaced) is left alone: touching
            # one whose C++ side is being destroyed is what crashes a program on Windows.
            if not _alive(widget) or _prop(widget, "zoomWatched"):
                continue
            kind = widget.metaObject().className()
            if "WebEngine" in kind or "Quick" in kind:
                continue  # the browser engine's own widgets are never touched
            if isinstance(widget, QAbstractScrollArea):
                target: QWidget = widget.viewport()
            elif widget.isWindow() or isinstance(widget, (QComboBox, QAbstractSpinBox)):
                target = widget
            else:
                continue
            widget.setProperty("zoomWatched", True)
            target.installEventFilter(self)

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


def _alive(widget: QObject) -> bool:
    """Whether a widget's C++ side still exists (its Python handle can outlive it)."""
    try:
        from shiboken6 import isValid
    except ImportError:  # pragma: no cover - PySide6 always brings it
        return True
    return bool(isValid(widget))
