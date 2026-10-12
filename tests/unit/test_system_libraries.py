"""The system libraries Qt needs are found all at once, and the command that adds them is given.

A clean Ubuntu without a desktop has no libEGL. The desktop application then failed with "the
desktop application needs PySide6: pip install 'eli-legal[gui]'", which was already installed,
and named only the first library missing.
"""

import subprocess
import types

import pytest

from eli_legal import system_libraries as libs


@pytest.fixture
def qt_folder(tmp_path, monkeypatch):
    """A PySide6 folder with Qt's files in it, on a Linux with ldd."""
    for rel in (
        "Qt/lib/libQt6Gui.so.6",
        "Qt/lib/libQt6XcbQpa.so.6",
        "Qt/plugins/platforms/libqxcb.so",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    monkeypatch.setattr(libs.sys, "platform", "linux")
    monkeypatch.setattr(
        libs.importlib.util,
        "find_spec",
        lambda name: types.SimpleNamespace(submodule_search_locations=[str(tmp_path)]),
    )
    return tmp_path


def _system(monkeypatch, ldd, tools, apt_knows=()):
    monkeypatch.setattr(
        libs.shutil, "which", lambda name: f"/usr/bin/{name}" if name in tools else None
    )

    def run(cmd, **kw):
        if cmd[0] == "ldd":
            return types.SimpleNamespace(
                stdout=ldd.get(cmd[1].rsplit("/", 1)[-1], ""), returncode=0
            )
        if cmd[:2] == ["apt-cache", "show"]:
            return types.SimpleNamespace(stdout="", returncode=0 if cmd[2] in apt_knows else 100)
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "run", run)


def test_every_missing_library_is_found_at_once_and_qt_s_own_are_not_counted(
    qt_folder, monkeypatch
):
    _system(
        monkeypatch,
        ldd={
            "libQt6Gui.so.6": "\tlibEGL.so.1 => not found\n\tlibGL.so.1 => not found\n\tlibc.so.6 => /lib/libc.so.6\n",
            "libQt6XcbQpa.so.6": "\tlibxcb-cursor.so.0 => not found\n\tlibEGL.so.1 => not found\n",
            "libqxcb.so": "\tlibQt6XcbQpa.so.6 => not found\n",
        },
        tools={"ldd", "apt-get", "apt-cache"},
        apt_knows={"libegl1", "libgl1", "libxcb-cursor0"},
    )
    assert libs.missing() == ["libEGL.so.1", "libGL.so.1", "libxcb-cursor.so.0"]
    command, unknown = libs.install_command(libs.missing())
    assert command == "sudo apt-get install -y libegl1 libgl1 libxcb-cursor0" and unknown == []
    said = libs.window_cannot_start(ImportError("libEGL.so.1: cannot open shared object file"))
    assert "libEGL.so.1, libGL.so.1, libxcb-cursor.so.0" in said and command in said
    assert "PySide6" not in said, "it is installed; the system's libraries are what is missing"


@pytest.mark.parametrize(
    "tools,expected",
    [
        ({"dnf"}, "sudo dnf install -y 'libEGL.so.1()(64bit)'"),
        ({"zypper"}, "sudo zypper install 'libEGL.so.1()(64bit)'"),
        ({"pacman"}, "sudo pacman -S --needed libglvnd"),
        ({"apk"}, "sudo apk add so:libEGL.so.1"),
    ],
)
def test_the_command_is_the_one_for_this_system_s_package_manager(monkeypatch, tools, expected):
    _system(monkeypatch, ldd={}, tools=tools)
    assert libs.install_command(["libEGL.so.1"]) == (expected, [])


def test_a_library_no_package_is_known_for_is_said_so_not_guessed(monkeypatch):
    _system(monkeypatch, ldd={}, tools={"apt-get", "apt-cache"}, apt_knows={"libegl1"})
    command, unknown = libs.install_command(["libEGL.so.1", "libstrange.so.7"])
    assert command == "sudo apt-get install -y libegl1" and unknown == ["libstrange.so.7"]
    assert "For libstrange.so.7, install the package that provides it" in libs.explain(
        ["libEGL.so.1", "libstrange.so.7"]
    )
    _system(monkeypatch, ldd={}, tools=set())
    assert libs.install_command(["libEGL.so.1"]) == (None, ["libEGL.so.1"])


def test_a_toolkit_that_is_not_installed_is_said_to_be_not_installed(monkeypatch):
    missing = ModuleNotFoundError("No module named 'PySide6'")
    missing.name = "PySide6"
    assert "pip install 'eli-legal[gui]'" in libs.window_cannot_start(missing)
    monkeypatch.setattr(libs, "missing", lambda: [])
    other = libs.window_cannot_start(ImportError("something else"))
    assert other == "PySide6 is installed but did not load: something else"


def test_nothing_is_looked_for_where_the_system_ships_what_qt_needs(monkeypatch):
    monkeypatch.setattr(libs.sys, "platform", "win32")
    assert libs.missing() == []
