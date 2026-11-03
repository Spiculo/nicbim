# SPDX-License-Identifier: GPL-3.0-or-later
"""Code-signing wrapper (D145): commands for signtool and osslsigncode, password masking, fake
runner signing, verification and the CLI dry run."""
from types import SimpleNamespace

import pytest

from kimbim import signing
from kimbim.agent import cli


def files(tmp_path):
    exe, cert = tmp_path / "kimbim-app.exe", tmp_path / "owner.pfx"
    exe.write_bytes(b"exe")
    cert.write_bytes(b"cert")
    return exe, cert


def test_windows_signing_command_and_masking():
    command = signing.sign_command("app.exe", "owner.pfx", password="s3cret", platform="windows",
                                   tool="signtool")
    assert command[:5] == ["signtool", "sign", "/fd", "sha256", "/f"]
    assert "/p" in command and command[command.index("/p") + 1] == "s3cret"
    assert command[-1] == "app.exe" and "/tr" in command
    shown = signing.describe(command)
    assert "s3cret" not in shown and "***" in shown


def test_linux_signing_command_uses_a_temporary_output():
    command = signing.sign_command("app", "owner.p12", password="pw", platform="linux",
                                   tool="osslsigncode", out="app.signed")
    assert command[0] == "osslsigncode" and "-pkcs12" in command and "-out" in command
    assert command[-1] == "app.signed"


def test_sign_with_a_fake_runner(tmp_path):
    exe, cert = files(tmp_path)
    seen = []

    def runner(command, capture_output=True, text=True):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = signing.sign(str(exe), str(cert), password="pw", platform="windows", runner=runner)
    assert result["ok"] and seen and seen[0][0] == signing.default_tool("windows")
    assert "pw" in seen[0]


def test_linux_sign_replaces_the_executable(tmp_path):
    exe, cert = files(tmp_path)

    def runner(command, capture_output=True, text=True):
        target = command[command.index("-out") + 1]
        with open(target, "wb") as f:
            f.write(b"signed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    signing.sign(str(exe), str(cert), platform="linux", runner=runner)
    assert exe.read_bytes() == b"signed"


def test_missing_files_and_failure_are_reported(tmp_path):
    exe, cert = files(tmp_path)
    with pytest.raises(ValueError, match="executable"):
        signing.sign(str(tmp_path / "missing.exe"), str(cert), platform="windows")
    with pytest.raises(ValueError, match="certificate"):
        signing.sign(str(exe), str(tmp_path / "missing.pfx"), platform="windows")

    def failed(command, capture_output=True, text=True):
        return SimpleNamespace(returncode=1, stdout="", stderr="bad certificate")

    with pytest.raises(OSError, match="bad certificate"):
        signing.sign(str(exe), str(cert), platform="windows", runner=failed)


def test_verify_command_and_fake_runner(tmp_path):
    exe, _cert = files(tmp_path)
    assert "signtool" in signing.verify_command(str(exe), platform="windows")[0].lower()
    assert signing.verify_command(str(exe), platform="windows")[1] == "verify"
    seen = []

    def runner(command, capture_output=True, text=True):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert signing.verify(str(exe), platform="windows", runner=runner)["ok"]
    assert "signtool" in seen[0][0].lower()


def test_cli_dry_run_does_not_print_the_password(tmp_path, capsys):
    exe, cert = files(tmp_path)
    code = cli.main(["sign", "--exe", str(exe), "--certificate", str(cert), "--password", "s3cret",
                     "--dry-run", "--verify"])
    out = capsys.readouterr().out
    assert code == 0 and "dry run" in out and "s3cret" not in out and "***" in out
