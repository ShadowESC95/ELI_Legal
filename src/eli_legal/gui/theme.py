"""Look and feel shared with the ELI desktop applications: dark navy, cyan accent."""

from __future__ import annotations

from eli_legal.domain import plain

BG = "#141821"
PANEL = "#181e29"
INPUT = "#10151e"
BORDER = "#2b3647"
TEXT = "#e6ecf5"
MUTED = "#94a8c6"
ACCENT = "#88c0d0"
GOOD = "#a3be8c"
WARN = "#ebcb8b"
BAD = "#bf616a"
IDLE = "#6b7a90"
HUMAN = "#b48ead"

# How a state reads at a glance, everywhere in the application. The tone of each state is decided
# once, in eli_legal.domain.plain, for every front end; this only gives each tone its colour.
_TONE_COLOURS = {"good": GOOD, "warn": WARN, "bad": BAD, "active": ACCENT, "idle": IDLE}
STATE_COLOUR = {state: _TONE_COLOURS[tone] for state, tone in plain.TONE.items()}


def colour_for(state: str) -> str:
    """The colour for a state code (``held``) or its plain words ("On hold")."""
    return _TONE_COLOURS.get(plain.tone(state), TEXT)


ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.7, 2.5, 0.1


# Text sizes at normal size, in points. They are not in the stylesheet: zooming changes the
# application's font and these few labels (gui/zoom.py), which takes a hundredth of a second,
# where restyling every widget took more than a second.
BASE_POINTS = 10.0
ROLE_POINTS = {"title": 15.0, "navname": 12.0, "navabout": 9.0}


def stylesheet(zoom: float = 1.0) -> str:
    """The application's look (colours, borders, spacing). Applied once, at start."""

    def px(size: float) -> int:
        return max(1, round(size * zoom))

    return f"""
QMainWindow, QWidget, QDialog {{ background: {BG}; color: {TEXT}; }}
QMenuBar {{ background: #10141c; color: #dce4f2; border-bottom: 1px solid #232b38; }}
QMenuBar::item {{ background: transparent; padding: {px(6)}px {px(10)}px; }}
QMenuBar::item:selected {{ background: #243043; border-radius: 4px; }}
QMenu {{ background: #18202c; color: {TEXT}; border: 1px solid {BORDER}; }}
QMenu::item {{ padding: {px(5)}px {px(22)}px; }}
QMenu::item:selected {{ background: #273449; }}
QPushButton, QToolButton {{
    background: #232b38; color: #edf3fb; border: 1px solid #334055;
    padding: {px(6)}px {px(12)}px; border-radius: 8px;
}}
QPushButton:hover, QToolButton:hover {{ background: #2c384d; border-color: #4e6a91; }}
QPushButton:pressed {{ background: #1c2431; }}
QPushButton:disabled {{ color: #5b6779; border-color: #262f3d; background: #1a202b; }}
QPushButton[kind="primary"] {{ background: #2e6b4a; border-color: #3f8f63; }}
QPushButton[kind="primary"]:hover {{ background: #378058; }}
QPushButton[kind="danger"] {{ background: #5b2a30; border-color: #8a3d46; }}
QPushButton[kind="danger"]:hover {{ background: #6d323a; }}
QTextEdit, QPlainTextEdit, QTextBrowser, QLineEdit, QSpinBox, QComboBox, QListWidget, QDateEdit {{
    background: {INPUT}; color: #edf3fb; border: 1px solid #2c384c; border-radius: 8px;
    padding: 5px; selection-background-color: #35507a;
}}
QComboBox QAbstractItemView {{ background: #121925; selection-background-color: #273449; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding-top: 12px;
    background: {PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {ACCENT};
    font-weight: bold; letter-spacing: 1px;
}}
QTabWidget::pane {{ border: 1px solid #243043; background: {BG}; }}
QTabBar::tab {{
    background: #111723; color: #9fb0c9; padding: {px(6)}px {px(12)}px; border: 1px solid #243043;
    border-bottom: none; border-top-left-radius: 5px; border-top-right-radius: 5px;
    margin-right: 1px;
}}
QTabBar::tab:selected {{ background: #1f2a3a; color: #ffffff; }}
QTabBar::tab:hover {{ color: #dce4f2; }}
QTableWidget, QTreeWidget {{
    background: {INPUT}; alternate-background-color: #131a25; color: {TEXT};
    gridline-color: #1f2836; border: 1px solid #2c384c; border-radius: 8px;
    selection-background-color: #26384f; selection-color: #ffffff;
}}
QHeaderView::section {{
    background: #161d29; color: {MUTED}; padding: {px(5)}px {px(8)}px; border: none;
    border-bottom: 1px solid {BORDER}; font-weight: bold;
}}
QSplitter::handle {{ background: #202938; }}
QScrollBar:vertical {{ background: #10151d; width: {px(12)}px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #334055; border-radius: 6px; min-height: 26px; }}
QScrollBar:horizontal {{ background: #10151d; height: {px(12)}px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #334055; border-radius: 6px; min-width: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: #10141c; color: #dce4f2; border-top: 1px solid #232b38; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QLabel[role="title"] {{ font-weight: bold; color: #ffffff; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="chip"] {{
    background: #10151e; border: 1px solid #2c384c; border-radius: 10px; padding: 3px 10px;
}}
QFrame[role="header"] {{ background: #0f131a; border-bottom: 1px solid #232b38; }}
QGraphicsView {{ background: #0e131b; border: 1px solid #2c384c; border-radius: 8px; }}
QToolTip {{
    background: #fff3b0; color: #1b1b1b; border: 1px solid #c9a227; border-radius: 4px;
    padding: {px(6)}px;
}}
QListWidget#nav {{
    background: #0f131a; border: none; border-right: 1px solid #232b38; border-radius: 0;
    padding: {px(4)}px;
}}
QListWidget#nav::item {{ border-radius: 6px; margin: 1px 2px; }}
QListWidget#nav::item:selected {{ background: #26384f; }}
QListWidget#nav::item:hover {{ background: #1c2636; }}
QWidget#navitem, QWidget#navitem QLabel {{ background: transparent; }}
QLabel[role="navname"] {{ font-weight: bold; color: #ffffff; }}
QLabel[role="navabout"] {{ color: {MUTED}; }}
"""


STYLESHEET = stylesheet(1.0)
