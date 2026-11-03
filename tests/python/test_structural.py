# SPDX-License-Identifier: GPL-3.0-or-later
"""D224: derive an IFC structural analytical model from the physical columns, beams and slabs."""
import json

import ifcopenshell.util.element
import pytest

from kimbim import app_bridge as B
from kimbim import structural as S


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def frame():
    """A column, a beam and a slab on Level 1."""
    assert call("new_project", "Frame")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    column = call("column_types")["types"][0]["guid"]
    beam = call("beam_types")["types"][0]["guid"]
    slab = call("slab_types")["types"][0]["guid"]
    assert call("create_column", level, column, 0, 0, 3.0)["ok"]
    assert call("create_beam", level, beam, 0, 0, 4, 0, 3.0)["ok"]
    assert call("create_slab", level, slab, json.dumps([[0, 0], [4, 0], [4, 4], [0, 4]]))["ok"]
    return level


def test_a_derived_model_has_curve_and_surface_members():
    frame()
    r = call(S.create_analysis_model)
    assert r["ok"] and r["curves"] == 2 and r["surfaces"] == 1
    state = call(S.analysis_model)
    assert state["model"]["name"] == "Analytical model"
    assert state["model"]["curves"] == 2 and state["model"]["surfaces"] == 1
    assert len(state["members"]) == 3
    # The curve members carry an edge from the placement origin along the extrusion axis.
    curves = [m for m in state["members"] if m["kind"] == "curve"]
    assert len(curves) == 2
    starts = []
    for entry in curves:
        member = B._model.by_guid(entry["guid"])
        edge = member.Representation.Representations[0].Items[0]
        starts.append(tuple(round(v) for v in edge.EdgeStart.VertexGeometry.Coordinates))
        assert tuple(round(v) for v in edge.EdgeEnd.VertexGeometry.Coordinates) != starts[-1]
    assert (0.0, 0.0, 0.0) in starts  # the column starts on the level
    # The surface member is a shell face with the slab's four corners.
    surface = next(m for m in state["members"] if m["kind"] == "surface")
    face = B._model.by_guid(surface["guid"]).Representation.Representations[0].Items[0]
    loop = face.Bounds[0].Bound
    assert len(loop.Polygon) == 4
    # Re-deriving replaces the members instead of duplicating them.
    again = call(S.create_analysis_model)
    assert again["ok"] and again["guid"] == r["guid"]
    assert len(call(S.analysis_model)["members"]) == 3
    # The physical model is untouched.
    assert len(B._model.by_type("IfcColumn")) == 1 and len(B._model.by_type("IfcBeam")) == 1


def test_undo_and_removal():
    frame()
    r = call(S.create_analysis_model)
    guid = r["guid"]
    assert call(S.remove_analysis_model)["ok"]
    assert call(S.analysis_model)["model"] is None
    assert B._model.by_type("IfcStructuralCurveMember") == ()
    assert not call(S.remove_analysis_model)["ok"]


def test_each_derivation_is_one_undo_step():
    frame()
    r = call(S.create_analysis_model)
    assert call("undo")["ok"]
    assert call(S.analysis_model)["model"] is None
    assert B._model.by_type("IfcStructuralAnalysisModel") == ()
    # Re-running after undo starts a new model with a new id.
    again = call(S.create_analysis_model)
    assert again["ok"] and again["guid"] != r["guid"]
