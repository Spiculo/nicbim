# SPDX-License-Identifier: GPL-3.0-or-later
"""Code signing for the packaged app with a user-provided certificate (D145).

Windows uses `signtool.exe` (Windows SDK); Linux uses `osslsigncode` for the PE executable. The
certificate (.pfx/.p12) and its password are the owner's: the password comes from `--password` or
`KIMBIM_SIGN_PASSWORD`, is never written to the plan or the output, and is shown as `***` in
`describe()`. No certificate is bundled and no signing happens automatically.

`plan()` builds the command; `sign()` runs it; `verify()` asks the platform tool to check the
signature. The module raises `OSError`/`ValueError`; the CLI reports them.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"


def _windows() -> bool:
    return sys.platform.startswith("win")


def default_tool(platform: str | None = None) -> str:
    name = "signtool" if (platform or ("windows" if _windows() else "linux")) == "windows" else "osslsigncode"
    return shutil.which(name) or name


def _platform(platform: str | None = None) -> str:
    if platform:
        return platform
    return "windows" if _windows() else "linux"


def sign_command(exe: str, certificate: str, *, password: str | None = None,
                 timestamp: str = DEFAULT_TIMESTAMP, tool: str | None = None,
                 platform: str | None = None, out: str | None = None) -> list[str]:
    """The signing command for this platform. The password is included here (it must be passed to
    the tool); use `describe()` for anything shown to a person."""
    if platform is None and sys.platform == "darwin":
        raise ValueError("macOS signing needs codesign and notarytool; not built yet")
    kind = _platform(platform)
    executable = tool or default_tool(kind)
    if kind == "windows":
        command = [executable, "sign", "/fd", "sha256", "/f", certificate]
        if password:
            command += ["/p", password]
        command += ["/tr", timestamp or DEFAULT_TIMESTAMP, "/td", "sha256", exe]
        return command
    target = out or f"{exe}.signed"
    command = [executable, "sign", "-pkcs12", certificate, "-h", "sha256"]
    if password:
        command += ["-pass", password]
    command += ["-t", timestamp or DEFAULT_TIMESTAMP, "-in", exe, "-out", target]
    return command


def verify_command(exe: str, *, tool: str | None = None, platform: str | None = None) -> list[str]:
    kind = _platform(platform)
    executable = tool or default_tool(kind)
    if kind == "windows":
        return [executable, "verify", "/pa", exe]
    return [executable, "verify", "-in", exe]


def describe(command: list[str]) -> str:
    """The command with a password masked, safe to print."""
    out = []
    hide_next = False
    for part in command:
        if hide_next:
            out.append("***")
            hide_next = False
            continue
        out.append(part)
        if part in ("/p", "-pass"):
            hide_next = True
    return " ".join(f'"{p}"' if " " in p else p for p in out)


def _password(password: str | None) -> str | None:
    return password if password is not None else os.environ.get("KIMBIM_SIGN_PASSWORD") or None


def plan(exe: str, certificate: str, *, password: str | None = None,
         timestamp: str = DEFAULT_TIMESTAMP, tool: str | None = None,
         platform: str | None = None, verify: bool = False) -> dict:
    """The commands and a display-safe summary, without running anything."""
    command = sign_command(exe, certificate, password=_password(password), timestamp=timestamp,
                           tool=tool, platform=platform)
    result = {"platform": _platform(platform), "command": command, "display": describe(command),
              "exe": exe, "certificate": certificate}
    if verify:
        check = verify_command(exe, tool=tool, platform=platform)
        result["verify"] = check
        result["verify_display"] = describe(check)
    return result


def _no_macos() -> None:
    if sys.platform == "darwin":
        raise ValueError("macOS signing needs a .app bundle and codesign/notarytool; not built yet")


def sign(exe: str, certificate: str, *, password: str | None = None,
         timestamp: str = DEFAULT_TIMESTAMP, tool: str | None = None,
         platform: str | None = None, runner=None) -> dict:
    """Sign `exe` with the owner's certificate. Linux needs a temporary output that replaces the
    input after a successful signing; Windows signs in place."""
    if platform is None and sys.platform == "darwin":
        raise ValueError("macOS signing needs codesign and notarytool; not built yet")
    exe_path, cert_path = pathlib.Path(exe), pathlib.Path(certificate)
    if not exe_path.is_file():
        raise ValueError(f"the executable does not exist: {exe}")
    if not cert_path.is_file():
        raise ValueError(f"the certificate does not exist: {certificate}")
    kind = _platform(platform)
    run = runner or subprocess.run
    target = None
    command = sign_command(str(exe_path), str(cert_path), password=_password(password),
                           timestamp=timestamp, tool=tool, platform=kind)
    if kind != "windows":
        target = str(exe_path) + ".signed"
        command = sign_command(str(exe_path), str(cert_path), password=_password(password),
                               timestamp=timestamp, tool=tool, platform=kind, out=target)
    process = run(command, capture_output=True, text=True)
    if getattr(process, "returncode", 1) != 0:
        raise OSError((getattr(process, "stderr", "") or getattr(process, "stdout", "") or "signing failed").strip())
    if target:
        os.replace(target, exe_path)
    return {"ok": True, "exe": str(exe_path), "display": describe(command)}


def verify(exe: str, *, tool: str | None = None, platform: str | None = None, runner=None) -> dict:
    """Verify the signature of `exe` with the platform tool."""
    if not pathlib.Path(exe).is_file():
        raise ValueError(f"the executable does not exist: {exe}")
    command = verify_command(exe, tool=tool, platform=platform)
    process = (runner or subprocess.run)(command, capture_output=True, text=True)
    if getattr(process, "returncode", 1) != 0:
        raise OSError((getattr(process, "stderr", "") or getattr(process, "stdout", "") or "verify failed").strip())
    return {"ok": True, "exe": exe, "display": describe(command)}
