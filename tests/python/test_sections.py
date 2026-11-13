# SPDX-License-Identifier: GPL-3.0-or-later
"""D247: section properties of IFC profiles."""
import math

import ifcopenshell
import pytest

from kimbim import sections as S


@pytest.fixture
def f():
    return ifcopenshell.file(schema="IFC4")


def test_rectangle_and_circle(f):
    rect = f.createIfcRectangleProfileDef("AREA", None, None, 0.2, 0.4)
    s = S.section(rect)
    assert s["A"] == pytest.approx(0.08)
    assert s["Iy"] == pytest.approx(0.2 * 0.4 ** 3 / 12) and s["Iz"] == pytest.approx(0.4 * 0.2 ** 3 / 12)
    assert s["Wy"] == pytest.approx(0.2 * 0.4 ** 2 / 6)
    circ = f.createIfcCircleProfileDef("AREA", None, None, 0.1)
    c = S.section(circ)
    assert c["Iy"] == pytest.approx(math.pi * 0.1 ** 4 / 4) and c["J"] == pytest.approx(math.pi * 0.1 ** 4 / 2)
    mm = S.section(f.createIfcRectangleProfileDef("AREA", None, None, 200.0, 400.0), 0.001)
    assert mm["A"] == pytest.approx(0.08)


def test_i_section_matches_ipe300(f):
    ipe = f.createIfcIShapeProfileDef("AREA", None, None, 0.150, 0.300, 0.0071, 0.0107, 0.015)
    s = S.section(ipe)
    assert s["A"] == pytest.approx(5.38e-3, rel=0.01)  # with the 15 mm root fillets
    assert s["Iy"] == pytest.approx(8.356e-5, rel=0.03)
    assert s["Iz"] == pytest.approx(6.04e-6, rel=0.03)


def test_polygon_square_equals_rectangle(f):
    pts = [f.createIfcCartesianPoint(p) for p in ((0.0, 0.0), (0.3, 0.0), (0.3, 0.5), (0.0, 0.5), (0.0, 0.0))]
    prof = f.createIfcArbitraryClosedProfileDef("AREA", None, f.createIfcPolyline(pts))
    s = S.section(prof)
    assert s["A"] == pytest.approx(0.15) and s["Iy"] == pytest.approx(0.3 * 0.5 ** 3 / 12)
    hollow = S.section(f.createIfcRectangleHollowProfileDef("AREA", None, None, 0.2, 0.2, 0.01))
    assert hollow["A"] == pytest.approx(0.04 - 0.18 ** 2)


def test_unsupported_is_none(f):
    assert S.section(None) is None
    assert S.section(f.createIfcEllipseProfileDef("AREA", None, None, 0.1, 0.2)) is None
