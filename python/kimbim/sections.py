# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-section properties of IFC profiles for the structural analysis (D247).

Axes: the profile's X becomes the member's local y and its Y the local z, so for a beam whose
profile has its depth along Y (as NicBim's beams and columns do) ``Iy`` is the strong axis
(EN 1993 naming). Everything is SI: m², m⁴, m³. Properties are about the centroid.

Closed forms for rectangles, circles, their hollow versions and I sections; L, T, U and C shapes
and arbitrary polygons (with voids) are integrated as polygons. Torsion ``J`` is exact for circles,
Saint-Venant series for rectangles, thin-walled for hollow and open sections, and the A⁴/(40·Ip)
approximation for arbitrary solids.
"""
from __future__ import annotations

import math


def _rect_j(a: float, b: float) -> float:
    a, b = max(a, b), min(a, b)
    return a * b ** 3 * (1 / 3 - 0.21 * (b / a) * (1 - b ** 4 / (12 * a ** 4)))


def _result(kind, A, Iy, Iz, J, h, b) -> dict:
    return {"kind": kind, "A": A, "Iy": Iy, "Iz": Iz, "J": J, "Wy": Iy / (h / 2) if h else 0.0,
            "Wz": Iz / (b / 2) if b else 0.0, "h": h, "b": b}


def polygon(points: list[tuple[float, float]], voids: list[list[tuple[float, float]]] = ()) -> dict | None:
    """Area properties of a polygon (points in metres, profile x/y) minus its voids."""
    def raw(pts):
        A = Sx = Sy = Ixx = Iyy = 0.0  # Ixx = ∫y², Iyy = ∫x² about the origin
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            c = x0 * y1 - x1 * y0
            A += c
            Sx += (x0 + x1) * c
            Sy += (y0 + y1) * c
            Ixx += (y0 * y0 + y0 * y1 + y1 * y1) * c
            Iyy += (x0 * x0 + x0 * x1 + x1 * x1) * c
        A /= 2
        sign = 1.0 if A >= 0 else -1.0
        return abs(A), sign * Sx / 6, sign * Sy / 6, sign * Ixx / 12, sign * Iyy / 12

    if len(points) < 3:
        return None
    A, Sx, Sy, Ixx, Iyy = raw(points)
    for v in voids or ():
        if len(v) >= 3:
            a, sx, sy, ixx, iyy = raw(v)
            A, Sx, Sy, Ixx, Iyy = A - a, Sx - sx, Sy - sy, Ixx - ixx, Iyy - iyy
    if A <= 1e-12:
        return None
    cx, cy = Sx / A, Sy / A
    Iy = Ixx - A * cy * cy  # about the centroidal axis along profile x (bending in the profile's y)
    Iz = Iyy - A * cx * cx
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    h = 2 * max(max(ys) - cy, cy - min(ys))
    b = 2 * max(max(xs) - cx, cx - min(xs))
    J = A ** 4 / (40 * (Iy + Iz)) if Iy + Iz > 0 else 0.0
    return _result("polygon", A, Iy, Iz, J, h, b)


def _shape_points(profile, s: float):
    """Outlines of the parametric open shapes (L, T, U, C, Z) in metres, as polygons."""
    g = lambda name, default=0.0: float(getattr(profile, name, None) or default) * s  # noqa: E731
    if profile.is_a("IfcLShapeProfileDef"):
        d, w, t = g("Depth"), g("Width") or g("Depth"), g("Thickness")
        return [(0, 0), (w, 0), (w, t), (t, t), (t, d), (0, d)], "L"
    if profile.is_a("IfcTShapeProfileDef"):
        d, fw, tw, tf = g("Depth"), g("FlangeWidth"), g("WebThickness"), g("FlangeThickness")
        return [(-tw / 2, 0), (tw / 2, 0), (tw / 2, d - tf), (fw / 2, d - tf), (fw / 2, d), (-fw / 2, d),
                (-fw / 2, d - tf), (-tw / 2, d - tf)], "T"
    if profile.is_a("IfcUShapeProfileDef"):
        d, fw, tw, tf = g("Depth"), g("FlangeWidth"), g("WebThickness"), g("FlangeThickness")
        return [(0, 0), (fw, 0), (fw, tf), (tw, tf), (tw, d - tf), (fw, d - tf), (fw, d), (0, d)], "U"
    if profile.is_a("IfcCShapeProfileDef"):
        d, w, t, lip = g("Depth"), g("Width"), g("WallThickness"), g("Girth")
        return [(0, 0), (w, 0), (w, lip), (w - t, lip), (w - t, t), (t, t), (t, d - t), (w - t, d - t),
                (w - t, d - lip), (w, d - lip), (w, d), (0, d)], "C"
    if profile.is_a("IfcZShapeProfileDef"):
        d, fw, tw, tf = g("Depth"), g("FlangeWidth"), g("WebThickness"), g("FlangeThickness")
        return [(-tw / 2, 0), (fw - tw / 2, 0), (fw - tw / 2, tf), (tw / 2, tf), (tw / 2, d), (-fw + tw / 2, d),
                (-fw + tw / 2, d - tf), (-tw / 2, d - tf)], "Z"
    return None, ""


def _curve_points(curve, s: float) -> list[tuple[float, float]]:
    if curve is None:
        return []
    if curve.is_a("IfcPolyline"):
        pts = [(float(p.Coordinates[0]) * s, float(p.Coordinates[1]) * s) for p in curve.Points]
    elif curve.is_a("IfcIndexedPolyCurve"):
        pts = [(float(p[0]) * s, float(p[1]) * s) for p in curve.Points.CoordList]
    else:
        return []
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def section(profile, scale: float = 1.0) -> dict | None:
    """Section properties of an IFC profile (dimensions in model units x `scale` = metres), or None."""
    s = float(scale)
    if profile is None:
        return None
    try:
        if profile.is_a("IfcRectangleHollowProfileDef"):
            b, h, t = float(profile.XDim) * s, float(profile.YDim) * s, float(profile.WallThickness) * s
            bi, hi = b - 2 * t, h - 2 * t
            A = b * h - bi * hi
            Iy = (b * h ** 3 - bi * hi ** 3) / 12
            Iz = (h * b ** 3 - hi * bi ** 3) / 12
            J = 2 * t * (b - t) ** 2 * (h - t) ** 2 / ((b - t) + (h - t))
            return _result("rectangle_hollow", A, Iy, Iz, J, h, b)
        if profile.is_a("IfcRectangleProfileDef"):
            b, h = float(profile.XDim) * s, float(profile.YDim) * s
            return _result("rectangle", b * h, b * h ** 3 / 12, h * b ** 3 / 12, _rect_j(b, h), h, b)
        if profile.is_a("IfcCircleHollowProfileDef"):
            r, t = float(profile.Radius) * s, float(profile.WallThickness) * s
            ri = r - t
            I = math.pi * (r ** 4 - ri ** 4) / 4
            return _result("circle_hollow", math.pi * (r * r - ri * ri), I, I, 2 * I, 2 * r, 2 * r)
        if profile.is_a("IfcCircleProfileDef"):
            r = float(profile.Radius) * s
            I = math.pi * r ** 4 / 4
            return _result("circle", math.pi * r * r, I, I, 2 * I, 2 * r, 2 * r)
        if profile.is_a("IfcIShapeProfileDef"):
            b, h = float(profile.OverallWidth) * s, float(profile.OverallDepth) * s
            tw, tf = float(profile.WebThickness) * s, float(profile.FlangeThickness) * s
            hw = h - 2 * tf
            r = float(getattr(profile, "FilletRadius", None) or 0.0) * s
            fillet = (4 - math.pi) * r * r  # four root fillets of (1 - pi/4) r2 each
            A = 2 * b * tf + hw * tw + fillet
            Iy = (b * h ** 3 - (b - tw) * hw ** 3) / 12 + fillet * (h / 2 - tf - 0.2234 * r) ** 2
            Iz = 2 * tf * b ** 3 / 12 + hw * tw ** 3 / 12
            J = (2 * b * tf ** 3 + (h - tf) * tw ** 3) / 3
            return _result("I", A, Iy, Iz, J, h, b)
        pts, kind = _shape_points(profile, s)
        if pts:
            out = polygon(pts)
            if out:
                # thin-walled open section torsion: Σ l t³ / 3 from the outline's wall thickness
                t = float(getattr(profile, "Thickness", None) or getattr(profile, "WebThickness", None)
                          or getattr(profile, "WallThickness", None) or 0) * s
                if t > 0:
                    out["J"] = (out["A"] / t) * t ** 3 / 3
                out["kind"] = kind
            return out
        if profile.is_a("IfcArbitraryProfileDefWithVoids"):
            return polygon(_curve_points(profile.OuterCurve, s),
                           [_curve_points(c, s) for c in profile.InnerCurves or ()])
        if profile.is_a("IfcArbitraryClosedProfileDef"):
            return polygon(_curve_points(profile.OuterCurve, s))
    except (TypeError, ValueError, AttributeError, ZeroDivisionError):
        return None
    return None
