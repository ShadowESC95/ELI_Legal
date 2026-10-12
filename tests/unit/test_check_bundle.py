"""The Linux build refuses a bundle that carries half of a library pair.

0.4.0 carried libxkbcommon from Ubuntu 22.04 but not libxkbcommon-x11, so the host's newer
libxkbcommon-x11 loaded against it and the window crashed on the first key press.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_bundle", ROOT / "packaging/linux/check_bundle.py"
)
check_bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_bundle)


def _bundle(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"\x7fELF" + b"\0" * 12)
    return str(tmp_path)


def _world(monkeypatch, needed, host, sources):
    monkeypatch.setattr(check_bundle, "_needed", lambda path: needed.get(Path(path).name, []))
    monkeypatch.setattr(check_bundle, "_host_libraries", lambda: host)
    monkeypatch.setattr(check_bundle, "_source_package", lambda path: sources.get(Path(path).name))


def test_a_host_library_needing_a_bundled_sibling_is_refused(tmp_path, monkeypatch):
    root = _bundle(tmp_path, "libQt6XcbQpa.so.6", "libxkbcommon.so.0")
    _world(
        monkeypatch,
        needed={
            "libQt6XcbQpa.so.6": ["libxkbcommon-x11.so.0", "libxkbcommon.so.0"],
            "libxkbcommon-x11.so.0": ["libxkbcommon.so.0", "libxcb.so.1"],
        },
        host={
            "libxkbcommon-x11.so.0": "/usr/lib/libxkbcommon-x11.so.0",
            "libxkbcommon.so.0": "/usr/lib/libxkbcommon.so.0",
        },
        sources={
            "libxkbcommon-x11.so.0": ("libxkbcommon-x11-0", "libxkbcommon"),
            "libxkbcommon.so.0": ("libxkbcommon0", "libxkbcommon"),
        },
    )
    found = check_bundle.splits(root)
    assert len(found) == 1 and "Install libxkbcommon-x11-0" in found[0]


def test_libraries_from_different_projects_may_meet(tmp_path, monkeypatch):
    # the host's libxcb needing a bundled libXau is a stable interface between two projects
    root = _bundle(tmp_path, "libX11.so.6", "libXau.so.6")
    _world(
        monkeypatch,
        needed={"libX11.so.6": ["libxcb.so.1"], "libxcb.so.1": ["libXau.so.6"]},
        host={"libxcb.so.1": "/usr/lib/libxcb.so.1", "libXau.so.6": "/usr/lib/libXau.so.6"},
        sources={"libxcb.so.1": ("libxcb1", "libxcb"), "libXau.so.6": ("libxau6", "libxau")},
    )
    assert check_bundle.splits(root) == []


def test_a_bundle_carrying_both_halves_passes(tmp_path, monkeypatch):
    root = _bundle(tmp_path, "libQt6XcbQpa.so.6", "libxkbcommon.so.0", "libxkbcommon-x11.so.0")
    _world(
        monkeypatch,
        needed={"libQt6XcbQpa.so.6": ["libxkbcommon-x11.so.0", "libxkbcommon.so.0"]},
        host={},
        sources={},
    )
    assert check_bundle.splits(root) == []


def test_the_release_build_installs_both_halves():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "libxkbcommon-x11-0" in workflow
    assert "check_bundle.py" in (ROOT / "packaging/linux/build.sh").read_text(encoding="utf-8")
    # the command line never touches the keyboard path: the release types into the window
    assert "window_smoke.sh" in workflow


def test_a_bundle_that_carries_the_c_plus_plus_runtime_is_refused(tmp_path):
    # the build machine's copy is older than what a graphics pack and the user's graphics
    # drivers need, and a process holds only one
    assert check_bundle.carried(_bundle(tmp_path, "libQt6Core.so.6", "libgomp.so.1")) == []
    (tmp_path / "deeper").mkdir()
    (tmp_path / "deeper" / "libstdc++.so.6").write_bytes(b"\x7fELF")
    found = check_bundle.carried(_bundle(tmp_path, "libgcc_s.so.1"))
    assert len(found) == 2 and "libstdc++.so.6" in found[1] and "user's system" in found[0]


def test_only_what_the_gtk_and_glib_io_plug_ins_needed_is_removed(tmp_path, monkeypatch):
    """0.6.0 carried GTK and GLib's I/O library from the build machine. On a newer system they
    loaded that system's plug-ins, built for a newer GLib: "undefined symbol:
    g_task_set_static_name" for gvfs, dconf and the ibus input method."""
    needed = {
        "libqgtk3.so": ["libgtk-3.so.0", "libgio-2.0.so.0", "libglib-2.0.so.0", "libQt6Gui.so.6"],
        "libqglib.so": ["libgio-2.0.so.0", "libQt6Core.so.6"],
        "libgtk-3.so.0": ["libgdk-3.so.0", "libgio-2.0.so.0", "libpng16.so.16"],
        "libgdk-3.so.0": ["libglib-2.0.so.0"],
        "libgio-2.0.so.0": ["libglib-2.0.so.0", "libmount.so.1"],
        "libmount.so.1": [],
        "QtWidgets.abi3.so": ["libQt6Gui.so.6", "libQt6Core.so.6"],  # the application's own use
        "libQt6Core.so.6": ["libglib-2.0.so.0"],
        "libQt6Gui.so.6": ["libQt6Core.so.6", "libpng16.so.16"],
        "libglib-2.0.so.0": [],
        "libpng16.so.16": [],
        "libpython3.12.so.1.0": [],
    }
    themes, network = tmp_path / "plugins/platformthemes", tmp_path / "plugins/networkinformation"
    themes.mkdir(parents=True), network.mkdir(parents=True)
    for name in needed:
        folder = themes if name == "libqgtk3.so" else network if name == "libqglib.so" else tmp_path
        (folder / name).write_bytes(b"\x7fELF" + b"\0" * 12)
    (themes / "libqxdgdesktopportal.so").write_bytes(b"\x7fELF" + b"\0" * 12)
    monkeypatch.setattr(check_bundle, "_needed", lambda path: needed.get(Path(path).name, []))

    assert any("libgtk-3.so.0" in line for line in check_bundle.carried(str(tmp_path)))
    removed = {Path(name).name for name in check_bundle.trim(str(tmp_path))}
    assert removed == {
        "libqgtk3.so",
        "libqglib.so",
        "libgtk-3.so.0",
        "libgdk-3.so.0",
        "libgio-2.0.so.0",
        "libmount.so.1",
    }
    left = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    # what Qt itself needs stays, and so does a library nothing names (it is opened by name)
    assert {
        "libglib-2.0.so.0",
        "libpng16.so.16",
        "libQt6Core.so.6",
        "libpython3.12.so.1.0",
        "libqxdgdesktopportal.so",
    } <= left
    assert check_bundle.carried(str(tmp_path)) == []
    assert check_bundle.trim(str(tmp_path)) == [], "nothing more to remove the second time"


def test_the_frozen_window_asks_for_the_desktop_s_own_dialogs_and_no_gtk():
    entry = (ROOT / "packaging/pyinstaller/entry_gui.py").read_text(encoding="utf-8")
    assert 'os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"' in entry
    assert entry.index("QT_QPA_PLATFORMTHEME") < entry.index("from eli_legal.gui.app import main")
    build = (ROOT / "packaging/linux/build.sh").read_text(encoding="utf-8")
    assert build.index("check_bundle.py --trim") < build.index('check_bundle.py "$STAGE/_internal"')
