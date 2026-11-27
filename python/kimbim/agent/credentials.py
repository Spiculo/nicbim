# SPDX-License-Identifier: GPL-3.0-or-later
"""API keys in the OS credential store (D102 phase 3): Windows Credential Manager, macOS Keychain or the
Linux Secret Service. Keys never go into preferences.json or a project. If no store can be reached, the
assistant says so instead of falling back to a file."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

SERVICE_PREFIX = "kimbim-assistant-"
GIT_PREFIX = "kimbim-git-"


class KeyStoreError(Exception):
    pass


def _target(provider: str, prefix: str = SERVICE_PREFIX) -> str:
    return prefix + (provider or "anthropic")


# ---------------------------------------------------------------- Windows

if os.name == "nt":
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _advapi = ctypes.windll.advapi32
    _advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _advapi.CredReadW.restype = wintypes.BOOL
    _advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _advapi.CredWriteW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]


def _windows_get(target: str) -> str:
    ptr = ctypes.POINTER(_CREDENTIALW)()
    if not _advapi.CredReadW(target, 1, 0, ctypes.byref(ptr)):
        return ""
    try:
        cred = ptr.contents
        if not cred.CredentialBlobSize:
            return ""
        data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return data.decode("utf-8", "replace")
    finally:
        _advapi.CredFree(ptr)


def _windows_set(target: str, key: str) -> None:
    data = key.encode("utf-8")
    blob = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    cred = _CREDENTIALW(Type=1, TargetName=target, CredentialBlobSize=len(data),
                        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)), Persist=2,
                        UserName="kimbim")
    if not _advapi.CredWriteW(ctypes.byref(cred), 0):
        raise KeyStoreError("Windows Credential Manager refused to store the key")


def _windows_delete(target: str) -> None:
    _advapi.CredDeleteW(target, 1, 0)  # not there is fine


# ---------------------------------------------------------------- macOS / Linux

def _run(args: list[str], data: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, input=data, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as ex:
        raise KeyStoreError(f"cannot reach the credential store: {ex}") from None


def _mac_get(target: str) -> str:
    out = _run(["security", "find-generic-password", "-s", target, "-w"])
    return out.stdout.strip() if out.returncode == 0 else ""


def _mac_set(target: str, key: str) -> None:
    out = _run(["security", "add-generic-password", "-s", target, "-a", "kimbim", "-w", key, "-U"])
    if out.returncode != 0:
        raise KeyStoreError(out.stderr.strip() or "macOS Keychain refused to store the key")


def _mac_delete(target: str) -> None:
    _run(["security", "delete-generic-password", "-s", target])


def _linux_get(target: str) -> str:
    out = _run(["secret-tool", "lookup", "service", target])
    return out.stdout.strip() if out.returncode == 0 else ""


def _linux_set(target: str, key: str) -> None:
    out = _run(["secret-tool", "store", "--label", "NicBim", "service", target], key)
    if out.returncode != 0:
        raise KeyStoreError(out.stderr.strip() or "the Secret Service refused to store the key")


def _linux_delete(target: str) -> None:
    _run(["secret-tool", "clear", "service", target])


# ---------------------------------------------------------------- public

def get_key(provider: str, prefix: str = SERVICE_PREFIX) -> str:
    target = _target(provider, prefix)
    if os.name == "nt":
        return _windows_get(target)
    if sys.platform == "darwin":
        return _mac_get(target)
    return _linux_get(target)


def set_key(provider: str, key: str, prefix: str = SERVICE_PREFIX) -> None:
    if not (key or "").strip():
        clear_key(provider, prefix)
        return
    target = _target(provider, prefix)
    if os.name == "nt":
        _windows_set(target, key)
    elif sys.platform == "darwin":
        _mac_set(target, key)
    else:
        _linux_set(target, key)


def clear_key(provider: str, prefix: str = SERVICE_PREFIX) -> None:
    target = _target(provider, prefix)
    if os.name == "nt":
        _windows_delete(target)
    elif sys.platform == "darwin":
        _mac_delete(target)
    else:
        _linux_delete(target)


def has_key(provider: str, prefix: str = SERVICE_PREFIX) -> bool:
    try:
        return bool(get_key(provider, prefix))
    except KeyStoreError:
        return False


# -- NicGit / Git remotes (R4): one token per server host, never in preferences.json or .git/config.

def get_git_token(host: str) -> str:
    return get_key(host, GIT_PREFIX)


def set_git_token(host: str, token: str) -> None:
    set_key(host, token, GIT_PREFIX)


def clear_git_token(host: str) -> None:
    clear_key(host, GIT_PREFIX)


def has_git_token(host: str) -> bool:
    return has_key(host, GIT_PREFIX)
