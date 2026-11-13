# SPDX-License-Identifier: GPL-3.0-or-later
"""D242: the MEP network core - ports, connections, tees, terminals, systems and traversal."""
import json

import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np
import pytest

from kimbim import app_bridge as B
from kimbim import mep as M


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def level(schema="", tmp_path=None):
    if schema == "IFC2X3":  # new projects are IFC4/IFC4X3; IFC2X3 arrives as an opened file
        from kimbim.testing import _reset_owner, build_model

        path = str(tmp_path / "old.ifc")
        build_model(schema="IFC2X3", walls=0).write(path)
        _reset_owner()  # its owner-history callbacks are global: never leak them into later files
        assert call("open_model", path)["ok"]
    else:
        assert call("new_project", "MEP", schema)["ok"] if schema else call("new_project", "MEP")["ok"]
    return call("storeys")["storeys"][0]["guid"]


def open_ports():
    return [p for p in B._model.by_type("IfcDistributionPort") if M._connected(p) is None]


def test_a_vertical_pipe_has_ports_at_both_ends():
    l1 = level()
    r = call(M.create_mep_segment3d, l1, "pipe", 1, 2, 0, 1, 2, 3, 0.05, 0.05)
    assert r["ok"], r
    assert abs(r["length"] - 3) < 1e-9
    e = B._model.by_guid(r["guid"])
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    assert abs(m[2][2] - 1.0) < 1e-9  # local Z (the extrusion) points up
    points = sorted(tuple(np.round(q, 6)) for _p, q in M.port_points(e))
    assert points == [(1.0, 2.0, 0.0), (1.0, 2.0, 3.0)]
    # the old 2D segment gets ports too
    r2 = call("create_mep_segment", l1, "duct", 0, 0, 4, 0, 2.7, 0.4, 0.25)
    assert len(M.port_points(B._model.by_guid(r2["guid"]))) == 2


def test_a_run_is_connected_inside_and_joins_the_next_run():
    l1 = level()
    r = call("create_mep_run", l1, "duct", json.dumps([[0, 0], [5, 0], [5, 4]]), 2.7, 0.4, 0.25, "Supply")
    assert r["ok"], r
    assert len(open_ports()) == 2  # only the two ends
    # a straight run continuing from its end connects to it
    r2 = call(M.create_mep_run3d, l1, "duct", json.dumps([[5, 4, 2.7], [5, 8, 2.7]]), 0.4, 0.25, "Supply")
    assert r2["ok"], r2
    assert len(open_ports()) == 2


def test_a_run_landing_on_a_segment_makes_a_tee_and_undo_restores_it():
    l1 = level()
    r = call("create_mep_run", l1, "pipe", json.dumps([[0, 0], [10, 0]]), 1.0, 0.05, 0.05, "Cold")
    assert r["ok"]
    segments_before = len(B._model.by_type("IfcPipeSegment"))
    ports_before = len(B._model.by_type("IfcDistributionPort"))
    branch = call(M.create_mep_run3d, l1, "pipe", json.dumps([[4, 3, 1.0], [4, 0, 1.0]]), 0.032, 0.032, "Cold")
    assert branch["ok"], branch
    assert len(branch["tees"]) == 1
    assert len(B._model.by_type("IfcPipeSegment")) == segments_before + 2  # the branch + the split-off part
    assert len(open_ports()) == 3  # the main's two ends and the branch's far end
    main = B._model.by_guid(r["segments"][0])
    a, b = M.segment_ends(main)
    assert abs(float(np.linalg.norm(b - a)) - 4.0) < 1e-6  # the original now stops at the tee
    tee = B._model.by_guid(branch["tees"][0])
    assert tee.PredefinedType == "JUNCTION" and len(M.port_points(tee)) == 3
    assert call("undo")["ok"]
    assert len(B._model.by_type("IfcPipeSegment")) == segments_before
    assert len(B._model.by_type("IfcDistributionPort")) == ports_before
    a, b = M.segment_ends(B._model.by_guid(r["segments"][0]))
    assert abs(float(np.linalg.norm(b - a)) - 10.0) < 1e-6


def test_terminals_have_typed_ports_and_design_values():
    l1 = level()
    r = call(M.place_mep_terminal, "wc", l1, 2, 2)
    assert r["ok"], r
    wc = B._model.by_guid(r["guid"])
    assert wc.is_a("IfcSanitaryTerminal") and wc.PredefinedType == "TOILETPAN"
    kinds = sorted((M.port_kind(p), p.FlowDirection) for p, _q in M.port_points(wc))
    assert kinds == [("cold_water", "SINK"), ("sanitary", "SOURCE")]
    assert M.design_values(wc)["DischargeUnits"] == 2.0
    board = B._model.by_guid(call(M.place_mep_terminal, "board", l1, 0, 0)["guid"])
    assert board.is_a("IfcElectricDistributionBoard")
    assert call(M.set_design_values, r["guid"], json.dumps({"DischargeUnits": 2.5}))["ok"]
    assert M.design_values(wc)["DischargeUnits"] == 2.5
    assert not call(M.place_mep_terminal, "spaceship", l1, 0, 0)["ok"]


def test_every_catalogue_kind_places_in_ifc2x3_ifc4_and_ifc4x3(tmp_path):
    for schema in ("IFC2X3", "IFC4", "IFC4X3"):
        l1 = level(schema, tmp_path)
        for kind in M.CATALOGUE:
            r = call(M.place_mep_terminal, kind, l1, 0, 0)
            assert r["ok"], (schema, kind, r)
            assert M.port_points(B._model.by_guid(r["guid"])), (schema, kind)
        run = call(M.create_mep_run3d, l1, "pipe", json.dumps([[0, 0, 1], [4, 0, 1], [4, 4, 1]]), 0.05, 0.05)
        assert run["ok"] and len(run["fittings"]) == 1, (schema, run)


def test_the_network_walks_from_the_air_handler():
    l1 = level()
    assert call(M.create_mep_system, "SA-1", "supply_air")["ok"]
    ahu = call(M.place_mep_terminal, "ahu", l1, 0, 0, 0, 0, "SA-1")["guid"]
    # the AHU's supply port is at (-0.5, 0, 1.5); duct up to 2.7, then along to two diffusers
    run = call(M.create_mep_run3d, l1, "duct", json.dumps([[-0.5, 0, 1.5], [-0.5, 0, 2.75], [6, 0, 2.75]]),
               0.4, 0.25, "SA-1")
    assert run["ok"], run
    d1 = call(M.place_mep_terminal, "supply_diffuser", l1, 6, 0, 2.7, 0, "SA-1")["guid"]
    branch = call(M.create_mep_run3d, l1, "duct", json.dumps([[3, 0, 2.75], [3, 3, 2.75]]), 0.2, 0.2, "SA-1")
    assert branch["ok"] and branch["tees"]
    d2 = call(M.place_mep_terminal, "supply_diffuser", l1, 3, 3, 2.7, 0, "SA-1")["guid"]
    assert call(M.connect_network, "SA-1")["ok"]
    net = call(M.mep_network, "SA-1")
    assert net["ok"] and net["sources"] == [ahu]
    assert net["tree"][ahu] is None
    assert d1 in net["tree"] and d2 in net["tree"]
    assert net["unreached"] == [] and net["loops"] == 0, net
    systems = {s["name"]: s for s in call("mep_systems")["systems"]}
    assert systems["SA-1"]["kind"] == "supply_air" and systems["SA-1"]["domain"] == "air"


def test_foreign_elements_without_ports_are_reported_not_crashing():
    l1 = level()
    assert call(M.create_mep_system, "CW", "cold_water")["ok"]
    seg = call(M.create_mep_segment3d, l1, "pipe", 0, 0, 1, 5, 0, 1, 0.05, 0.05, "CW")["guid"]
    e = B._model.by_guid(seg)
    for rel in list(e.IsNestedBy):  # strip the ports as if the file came from elsewhere
        for p in rel.RelatedObjects:
            B._model.remove(p)
        B._model.remove(rel)
    net = call(M.mep_network, "CW")
    assert net["ok"] and seg in net["unreached"] and net["issues"]
    from kimbim import checks

    out = checks.check_model(B._model, {"model_checks": ["mep_no_source"]})
    assert any("no source" in i["message"] for i in out["issues"])


def test_create_system_refuses_bad_input():
    level()
    assert not call(M.create_mep_system, "", "supply_air")["ok"]
    assert not call(M.create_mep_system, "X", "lava")["ok"]
    assert call(M.create_mep_system, "X", "power")["ok"]
    assert not call(M.create_mep_system, "X", "power")["ok"]
    assert not call(M.create_mep_run3d, B._model.by_type("IfcBuildingStorey")[0].GlobalId, "duct",
                    json.dumps([[0, 0, 1], [1, 0, 1]]), 0.2, 0.2, "", "cold_water")["ok"]
