# SPDX-License-Identifier: GPL-3.0-or-later
"""D247: loads, supports, analysis and member checks from the physical model."""
import json

import ifcopenshell.util.element
import numpy as np
import pytest

from kimbim import app_bridge as B
from kimbim import engsettings as E
from kimbim import structanalysis as SA


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def bay(slab=True, columns=True, span=4.0):
    """Four columns 3 m high, four beams on top and (optionally) a slab on level 2 at +3.0."""
    assert call("new_project", "Bay")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    ct = call("column_types")["types"][0]["guid"]
    bt = call("beam_types")["types"][0]["guid"]
    st = call("slab_types")["types"][0]["guid"]
    corners = [(0, 0), (span, 0), (span, span), (0, span)]
    if columns:
        for x, y in corners:
            assert call("create_column", l1, ct, x, y, 3.0)["ok"]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        assert call("create_beam", l1, bt, *a, *b, 3.0)["ok"]
    if slab:
        assert call("create_slab", l2, st, json.dumps([list(c) for c in corners]))["ok"]
    return l1, l2


def slab_case_total(report, case, kind="beam"):
    an = report["_analysis"]
    out = {}
    for l in an.cases[case]["member"]:
        fm = an.frame_members[l["member"]]
        m = an.members[fm["phys"]]
        if m.kind != kind:
            continue
        L = float(np.linalg.norm(np.asarray(an.nodes[fm["j"]]) - an.nodes[fm["i"]]))
        out[m.element.GlobalId] = out.get(m.element.GlobalId, 0.0) + -l["w"][2] * L
    return out


def test_a_bay_has_fixed_bases_and_its_slab_load_shared_by_four_beams():
    bay()
    r = SA.run_analysis()
    assert r["ok"], r.get("error")
    assert sorted(x["kind"] for x in r["reactions"]) == ["fixed"] * 4
    q = slab_case_total(r, "Q")
    assert len(q) == 4
    for v in q.values():  # 16 m2 x 2 kN/m2, two-way: a quarter each
        assert v == pytest.approx(8.0, rel=0.03)
    assert r["total_reaction_kN"] == pytest.approx(r["total_uls_kN"], rel=1e-6)
    assert not any("nothing supports" in w for w in r["warnings"])


def test_member_self_weight_follows_density_and_area():
    bay(slab=False)
    r = SA.run_analysis()
    g = slab_case_total(r, "G")
    beam = next(m for m in r["_analysis"].members if m.kind == "beam")
    expected = beam.material["density"] * beam.section["A"] * beam.length
    assert g[beam.element.GlobalId] == pytest.approx(expected, rel=1e-6)


def test_a_heavy_use_fails_the_beams_and_apply_colours_them_red():
    bay()
    assert call(E.set_engineering_settings, "structure_settings",
                json.dumps({"use_loads": {"X": 1000.0}, "level_use": {"Level 2": "X"}}))["ok"]
    r = call(SA.analyse_structure, True)
    assert r["ok"] and r["applied"], r
    beams = [m for m in r["members"] if m["kind"] == "beam"]
    assert all(m["status"] == "fail" for m in beams)
    colours = call(SA.utilisation_colours)["colours"]
    assert all(colours[m["guid"]] == SA.COLOURS["fail"] for m in beams)
    stored = ifcopenshell.util.element.get_pset(B._model.by_guid(beams[0]["guid"]), SA.RESULT_PSET)
    assert stored["Status"] == "fail" and stored["MaxUtilisation"] > 1
    # IFC: supports, load cases, a combination and reactions on the analysis model
    model = B._model.by_type("IfcStructuralAnalysisModel")[0]
    assert len(model.LoadedBy) == 5 and len(model.HasResults) == 1
    assert len(B._model.by_type("IfcStructuralPointConnection")) == 4
    assert len(B._model.by_type("IfcStructuralPointReaction")) == 4
    # re-running replaces rather than piles up
    assert call(SA.analyse_structure, True)["ok"]
    assert len(B._model.by_type("IfcStructuralPointConnection")) == 4
    assert len(B._model.by_type("IfcStructuralLoadGroup")) == 5
    # one undo step takes the second run away, a second the first
    assert call("undo")["ok"] and call("undo")["ok"]
    assert not B._model.by_type("IfcStructuralPointConnection")
    assert ifcopenshell.util.element.get_pset(B._model.by_guid(beams[0]["guid"]), SA.RESULT_PSET) is None


def test_a_normal_floor_passes():
    bay()
    r = SA.run_analysis()
    assert r["counts"]["fail"] == 0
    assert all(m["utilisation"] < 1 for m in r["members"])


def test_beams_alone_are_not_analysed_and_say_why():
    bay(columns=False, slab=False)
    r = call(SA.analyse_structure, False)
    assert not r["ok"] and "nothing to analyse" in r["error"]
    assert any("not connected to any support" in w for w in r["warnings"])


def test_an_unknown_material_falls_back_with_a_warning():
    bay(slab=False)
    for m in B._model.by_type("IfcMaterial"):
        m.Name = "Unobtainium"
        if hasattr(m, "Category"):
            m.Category = None
    r = SA.run_analysis()
    assert r["ok"]
    assert any("Unobtainium" in w for w in r["warnings"])


def test_slabs_on_bearing_walls_load_the_walls():
    assert call("new_project", "Walls")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    wt = call("wall_types")["types"][0]["guid"]
    for a, b in (((0, 0), (5, 0)), ((5, 0), (5, 4)), ((5, 4), (0, 4)), ((0, 4), (0, 0))):
        assert call("create_wall", l1, wt, *a, *b, 3.0)["ok"]
    st = call("slab_types")["types"][0]["guid"]
    assert call("create_slab", l2, st, json.dumps([[0, 0], [5, 0], [5, 4], [0, 4]]))["ok"]
    r = call(SA.analyse_structure, False)
    assert r["ok"] and len(r["walls"]) == 4 and r["members"] == []  # a masonry building: loads to the walls
    assert all(w["uls_kN_per_m"] > 0 for w in r["walls"])
    rr = SA.run_analysis()
    total = sum(v["Q"] for v in rr["_analysis"].wall_loads.values())
    assert total == pytest.approx(20 * 2.0, rel=0.02)


def test_a_beam_on_two_walls_is_simply_supported():
    assert call("new_project", "Lintel")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    wt = call("wall_types")["types"][0]["guid"]
    bt = call("beam_types")["types"][0]["guid"]
    assert call("create_wall", l1, wt, 0, -1, 0, 1, 3.0)["ok"]
    assert call("create_wall", l1, wt, 5, -1, 5, 1, 3.0)["ok"]
    assert call("create_beam", l1, bt, 0, 0, 5, 0, 3.4)["ok"]  # bottom at 3.0, on the walls
    r = SA.run_analysis()
    assert r["ok"], r.get("error")
    assert sorted(x["kind"] for x in r["reactions"]) == ["wall", "wall"]
    beam = r["_analysis"].members[0]
    w = 1.35 * beam.material["density"] * beam.section["A"]
    row = r["members"][0]
    assert row["My"] == pytest.approx(w * beam.length ** 2 / 8, rel=0.02)
    assert sum(x["force"][2] for x in r["reactions"]) == pytest.approx(w * beam.length, rel=1e-6)


def test_ifc4x3_projects_analyse_too():
    assert call("new_project", "Bay", "IFC4X3")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ct = call("column_types")["types"][0]["guid"]
    bt = call("beam_types")["types"][0]["guid"]
    assert call("create_column", l1, ct, 0, 0, 3.0)["ok"]
    assert call("create_beam", l1, bt, 0, 0, 3, 0, 3.0)["ok"]  # a cantilever off the column
    r = call(SA.analyse_structure, True)
    assert r["ok"] and r["applied"], r
    beam = next(m for m in r["members"] if m["kind"] == "beam")
    assert beam["cantilever"] and beam["deflection_limit"] == pytest.approx(3.0 / 125, rel=0.02)
