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


STYLESHEET = f"""
QMainWindow, QWidget, QDialog {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QMenuBar {{ background: #10141c; color: #dce4f2; border-bottom: 1px solid #232b38; }}
QMenuBar::item {{ background: transparent; padding: 6px 10px; }}
QMenuBar::item:selected {{ background: #243043; border-radius: 4px; }}
QMenu {{ background: #18202c; color: {TEXT}; border: 1px solid {BORDER}; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: #273449; }}
QPushButton, QToolButton {{
    background: #232b38; color: #edf3fb; border: 1px solid #334055;
    padding: 6px 12px; border-radius: 8px;
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
    background: #111723; color: #9fb0c9; padding: 6px 12px; border: 1px solid #243043;
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
    background: #161d29; color: {MUTED}; padding: 5px 8px; border: none;
    border-bottom: 1px solid {BORDER}; font-weight: bold;
}}
QSplitter::handle {{ background: #202938; }}
QScrollBar:vertical {{ background: #10151d; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #334055; border-radius: 6px; min-height: 26px; }}
QScrollBar:horizontal {{ background: #10151d; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #334055; border-radius: 6px; min-width: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: #10141c; color: #dce4f2; border-top: 1px solid #232b38; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QLabel[role="title"] {{ font-size: 15pt; font-weight: bold; color: #ffffff; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="chip"] {{
    background: #10151e; border: 1px solid #2c384c; border-radius: 10px; padding: 3px 10px;
}}
QFrame[role="header"] {{ background: #0f131a; border-bottom: 1px solid #232b38; }}
QGraphicsView {{ background: #0e131b; border: 1px solid #2c384c; border-radius: 8px; }}
"""
