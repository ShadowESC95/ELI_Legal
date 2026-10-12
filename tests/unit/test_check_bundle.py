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
