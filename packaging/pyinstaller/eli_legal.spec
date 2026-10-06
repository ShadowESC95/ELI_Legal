# PyInstaller build of ELI Legal: one folder holding two programs that share everything else.
#
#   eli-legal       console: the command line and the server (no arguments: the desktop app)
#   eli-legal-gui   no console window: the desktop application
#
# Build from the repository root:  python -m PyInstaller packaging/pyinstaller/eli_legal.spec
#
# One folder, not one file: the Qt libraries stay as separate files that can be replaced, which
# is what their licence (LGPL-3.0) asks of anyone who distributes them. See THIRD_PARTY_NOTICES.md.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
ICON_PNG = SRC / "eli_legal" / "gui" / "assets" / "eli_legal_256.png"
ICON = {"win32": ROOT / "packaging" / "windows" / "eli_legal.ico", "darwin": ROOT / "packaging" / "macos" / "eli_legal.icns"}.get(sys.platform)
ICON = str(ICON) if ICON and ICON.exists() else None

# Configuration, registers, jurisdiction packs and the web application ship as files. The Python
# sources ship too, so the register check can confirm that every control still points at code.
datas = collect_data_files("eli_legal", include_py_files=True)
datas += copy_metadata("eli-legal")
for name in ("THIRD_PARTY_NOTICES.md", "LICENSE", "NOTICE", "README.md"):
    if (ROOT / name).is_file():
        datas.append((str(ROOT / name), "."))

hidden = collect_submodules("eli_legal") + collect_submodules("uvicorn")
hidden += ["pypdf", "cryptography", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]

excluded = [
    # A browser engine is not part of this product; neither is anything used only to develop it.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtTest", "PySide6.QtSql",
    "tkinter", "pytest", "mypy", "ruff", "IPython", "matplotlib", "numpy", "PyInstaller",
]

a = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "entry_cli.py"), str(ROOT / "packaging" / "pyinstaller" / "entry_gui.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hidden,
    excludes=excluded,
    noarchive=False,
)
pyz = PYZ(a.pure)

def program(script, name, console):
    return EXE(
        pyz, [s for s in a.scripts if Path(s[1]).name == script or not s[0].startswith("entry_")],
        [], exclude_binaries=True, name=name, console=console, icon=ICON, upx=False, strip=False,
    )

cli = program("entry_cli.py", "eli-legal", True)
gui = program("entry_gui.py", "eli-legal-gui", False)
bundle = COLLECT(cli, gui, a.binaries, a.datas, name="eli-legal", upx=False, strip=False)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle, name="ELI Legal.app", icon=ICON, bundle_identifier="legal.eli.desktop",
        info_plist={"CFBundleExecutable": "eli-legal-gui", "NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.business"},
    )
