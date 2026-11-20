# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable installer/uninstaller (D144): copy the packaged build, marker, associations and safety."""
import json

import pytest

from kimbim import installer
from kimbim.agent import cli


def fake_build(tmp_path):
    source = tmp_path / "dist" / "NicBim"
    source.mkdir(parents=True)
    (source / "kimbim-app.exe").write_text("app", encoding="utf-8")
    (source / "NicBim.cmd").write_text("launcher", encoding="utf-8")
    (source / "runtime").mkdir()
    (source / "runtime" / "python.dat").write_text("runtime", encoding="utf-8")
    return source


def test_install_copies_the_build_and_associates(tmp_path):
    source = fake_build(tmp_path)
    dest = tmp_path / "Programs" / "NicBim"
    called = []
    result = installer.install(source, dest, associate=called.append)
    assert result["ok"] and not result["dry_run"]
    assert (dest / "kimbim-app.exe").is_file()
    assert (dest / "runtime" / "python.dat").read_text() == "runtime"
    assert called == [str(dest / "kimbim-app.exe")]
    marker = json.loads((dest / installer.MARKER).read_text())
    assert marker["product"] == "NicBim" and marker["app"] == str(dest / "kimbim-app.exe")
    assert installer.status(dest)["installed"] is True

    with pytest.raises(ValueError, match="already installed"):
        installer.install(source, dest, associate=called.append)
    installer.install(source, dest, force=True, associate=called.append)
    assert (dest / "kimbim-app.exe").is_file()


def test_dry_run_changes_nothing(tmp_path):
    source = fake_build(tmp_path)
    dest = tmp_path / "not-created"
    result = installer.install(source, dest, dry_run=True, associate=lambda _p: None)
    assert result["dry_run"] and not dest.exists()
    assert any("copy" in action for action in result["actions"])


def test_install_refuses_a_foreign_folder(tmp_path):
    source = fake_build(tmp_path)
    dest = tmp_path / "someones-folder"
    dest.mkdir()
    (dest / "important.txt").write_text("keep me")
    with pytest.raises(ValueError, match="not installed by NicBim"):
        installer.install(source, dest, force=True)
    assert (dest / "important.txt").is_file()


def test_install_requires_the_app_executable(tmp_path):
    source = tmp_path / "empty-build"
    source.mkdir()
    with pytest.raises(ValueError, match="not a NicBim build"):
        installer.install(source, tmp_path / "dest", associate=lambda _p: None)


def test_uninstall_removes_files_and_associations(tmp_path):
    source = fake_build(tmp_path)
    dest = tmp_path / "Programs" / "NicBim"
    installer.install(source, dest, associate=lambda _p: None)
    removed = []
    result = installer.uninstall(dest, unassociate=lambda: removed.append(True))
    assert result["ok"] and not dest.exists() and removed == [True]
    with pytest.raises(ValueError, match="not a NicBim installation"):
        installer.uninstall(dest)


def test_uninstall_dry_run_and_foreign_folder(tmp_path):
    dest = tmp_path / "nothing"
    with pytest.raises(ValueError, match="not a NicBim installation"):
        installer.uninstall(dest, dry_run=True)


def test_cli_install_dry_run(tmp_path, capsys):
    source = fake_build(tmp_path)
    dest = tmp_path / "cli-dest"
    code = cli.main(["install", "--source", str(source), "--dest", str(dest), "--dry-run",
                     "--no-associations"])
    out = capsys.readouterr().out
    assert code == 0 and "dry run" in out and not dest.exists()
