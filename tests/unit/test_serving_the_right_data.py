"""The browser and the desktop must use one set of data: a developer checkout does not serve its
test data by mistake where an installed copy's data exists; the server says what it serves."""

from __future__ import annotations

from eli_legal import paths


def test_a_developer_checkout_refuses_to_serve_its_test_data_beside_an_installed_copy(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ELI_LEGAL_HOME", raising=False)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "installed")
    assert paths.serving_test_data_by_mistake() == "", "no installed data here: nothing to confuse"
    (tmp_path / "installed" / "data").mkdir(parents=True)
    said = paths.serving_test_data_by_mistake()
    assert "developer checkout" in said and str(tmp_path / "installed") in said
    assert "--dev-data" in said and "Settings → System → Server" in said
    monkeypatch.setenv("ELI_LEGAL_HOME", str(tmp_path / "chosen"))
    assert paths.serving_test_data_by_mistake() == "", "a folder chosen on purpose is served"
    assert paths.installation()["kind"] == "the folder ELI_LEGAL_HOME names"
