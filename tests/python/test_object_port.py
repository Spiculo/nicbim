# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled objects keep their geometry (tests/golden/library_objects.json): bounding box, volume and plan symbol
at their defaults and recorded value sets. It began as the D99 port proof; since D256 it is a regression record
rewritten by tools/update_library_golden.py after a deliberate change."""
import json
import pathlib

import pytest

from kimbim import objects

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests/golden/library_objects.json").read_text(encoding="utf-8"))
BUNDLED = ROOT / "python/kimbim/bundled_objects"


def cases():
    return [(key, name) for key in sorted(GOLDEN) for name in sorted(GOLDEN[key])]


@pytest.mark.parametrize("key, name", cases())
def test_port_matches_the_python_object(key, name):
    want = GOLDEN[key][name]
    d = objects.load_file(str(BUNDLED / f"{key}.nicobj"), "bundled")
    assert d.key == key
    values = d.values(want["values"])
    for k, v in want["values"].items():
        assert values[k] == pytest.approx(v), k
    got = d.shape(values).metrics()
    assert got["bbox"] == pytest.approx(want["bbox"], abs=1e-3)
    assert got["volume"] == pytest.approx(want["volume"], rel=5e-3)
    assert got["symbol_bbox"] == pytest.approx(want["symbol_bbox"], abs=1e-3)
    assert got["symbol_length"] == pytest.approx(want["symbol_length"], rel=5e-3)


def test_every_bundled_file_is_a_golden_object():
    assert sorted(p.stem for p in BUNDLED.glob("*.nicobj")) == sorted(GOLDEN)
