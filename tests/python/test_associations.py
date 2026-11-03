# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user file associations for .kim and .ifc (D139): the Windows registry plan and apply (with a
fake registry), the Linux desktop/MIME files, `--print` and `--remove`."""
import json

from kimbim import associations as A
from kimbim.agent import cli


class FakeKey:
    def __init__(self, registry, key):
        self.registry, self.key = registry, key
        self.registry.keys.add(key)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_SET_VALUE = 1
    REG_SZ = "REG_SZ"

    def __init__(self):
        self.keys, self.values = set(), {}

    def CreateKeyEx(self, root, key, _reserved, _access):
        return FakeKey(self, key)

    def SetValueEx(self, key, name, _reserved, _type, value):
        self.values[(key.key, name)] = value

    def DeleteKey(self, root, key):
        if key not in self.keys:
            raise FileNotFoundError(key)
        self.keys.discard(key)
        for k in list(self.values):
            if k[0] == key:
                del self.values[k]


def test_windows_plan_associates_both_extensions():
    exe = r"C:\Program Files\KimBim\kimbim-app.exe"
    actions = A.windows_actions(exe)
    assert {a["key"] for a in actions} >= {r"Software\Classes\.kim", r"Software\Classes\.ifc"}
    kim = next(a for a in actions if a["key"] == r"Software\Classes\.kim")
    assert kim["value"] == "KimBim.Project"
    ifc = next(a for a in actions if a["key"] == r"Software\Classes\.ifc")
    assert ifc["value"] == "KimBim.Ifc"
    command = next(a for a in actions if a["key"].endswith(r"KimBim.Project\shell\open\command"))
    assert command["value"] == f'"{exe}" "%1"'
    assert A.describe({"platform": "windows", "actions": actions, "exe": exe}).count("HKCU\\") == len(actions)


def test_windows_apply_and_remove_with_a_fake_registry():
    reg = FakeRegistry()
    removed = A._windows_apply(A.windows_actions(r"C:\KimBim\kimbim-app.exe"), registry=reg)
    assert removed and (r"Software\Classes\.kim", "") in reg.values
    assert reg.values[(r"Software\Classes\.kim", "")] == "KimBim.Project"
    assert reg.values[(r"Software\Classes\KimBim.Ifc\shell\open\command", "")] == \
        r'"C:\KimBim\kimbim-app.exe" "%1"'
    A._windows_apply(A.windows_actions(""), remove=True, registry=reg)
    assert reg.values == {}  # every class and extension key is gone


def test_linux_desktop_and_mime_files(tmp_path):
    exe = "/opt/kimbim/kimbim-app"
    desktop = A.linux_desktop(exe)
    assert 'Exec="/opt/kimbim/kimbim-app" %f' in desktop
    assert "application/x-kimbim-project" in desktop and "application/x-ifc" in desktop
    xml = A.linux_mime_xml()
    assert 'glob pattern="*.kim"' in xml and 'glob pattern="*.ifc"' in xml
    actions = A.linux_actions(exe, str(tmp_path))
    paths = [action["path"].replace("\\", "/") for action in actions]
    assert paths[0].endswith("applications/kimbim.desktop")
    assert paths[1].endswith("mime/packages/kimbim.xml")
    for path in paths:
        assert tmp_path.as_posix() in path


def test_the_cli_prints_without_writing(capsys):
    code = cli.main(["setup", "associations", "--print", "--exe", r"C:\KimBim\kimbim-app.exe"])
    out = capsys.readouterr().out
    assert code == 0
    assert "kimbim-app.exe" in out
    assert ("HKCU" in out) or ("kimbim.desktop" in out)


def test_plan_needs_an_executable():
    try:
        A.plan("")
    except ValueError as ex:
        assert "executable" in str(ex)
    else:  # pragma: no cover
        raise AssertionError("plan('') should raise")
