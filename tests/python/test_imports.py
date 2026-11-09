# SPDX-License-Identifier: GPL-3.0-or-later
"""Every kimbim module imports on its own, in a fresh interpreter: no circular imports that only work
because another module happened to be imported first (the full suite hides those)."""
import pathlib
import subprocess
import sys

import pytest

import kimbim

PACKAGE = pathlib.Path(kimbim.__file__).parent
MODULES = sorted(p.stem for p in PACKAGE.glob("*.py") if p.stem not in ("__init__", "__main__"))


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_alone(name):
    r = subprocess.run([sys.executable, "-c", f"import kimbim.{name}"], capture_output=True, text=True,
                       cwd=PACKAGE.parent, timeout=120)
    assert r.returncode == 0, r.stderr


def test_every_exported_bridge_function_resolves():
    """The app calls bridge functions by name; an _EXPORTS module that was never imported failed only
    when the app used it (push/pull, energy, visual scripts... could not run from the menus)."""
    from kimbim import app_bridge

    missing = [name for name in app_bridge._EXPORTED if not callable(getattr(app_bridge, name, None))]
    assert missing == []


def test_no_two_modules_export_the_same_bridge_name():
    """A name listed under two modules silently shadows one of them (D234's phases hid D214's)."""
    from kimbim import app_bridge

    seen, clashes = {}, []
    for module, names in app_bridge._EXPORTS.items():
        for name in names:
            if name in seen:
                clashes.append(f"{name}: {seen[name]} and {module}")
            seen[name] = module
    assert clashes == []
