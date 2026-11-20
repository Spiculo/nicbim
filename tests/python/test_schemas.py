# SPDX-License-Identifier: GPL-3.0-or-later
"""IFC4X3 (doc 02, D30; D241): new projects in either schema, the sample house authored in IFC4X3, and the
explicit schema change, which in a versioned project is a version of its own."""
import json
import os
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import documents as D
from kimbim import nicfile as K
from kimbim import schemas as SC
from kimbim import versioning as V

# These tests choose the schema of every project themselves (and check the IFC4 default): not part of the forced
# IFC4X3 pass (KIMBIM_TEST_SCHEMA), which would change their starting point.
pytestmark = pytest.mark.skipif(bool(os.environ.get("KIMBIM_TEST_SCHEMA")), reason="the schema tests set it themselves")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


def call(fn, *args):
    return json.loads(fn(*args))


def _valid(path) -> list[str]:
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(str(path)), log, express_rules=True)
    return [str(s.get("message", s)) for s in log.statements]


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    yield tmp_path
    D.close_document()


def test_new_project_in_ifc4x3(clean):
    r = call(A.new_project, "Bridge site", "IFC4X3")
    assert r["ok"]
    assert B._model.schema_identifier == "IFC4X3_ADD2"
    assert call(SC.schema_info)["schema"] == "IFC4X3"
    assert call(A.new_project, "Default")["ok"] and B._model.schema == "IFC4"
    assert not call(A.new_project, "Bad", "IFC9")["ok"]


def test_the_house_authored_in_ifc4x3_is_valid(clean):
    out = clean / "house4x3.ifc"
    counts = make_house.build(str(out), schema="IFC4X3")
    assert counts["walls"] == 8 and counts["doors"] == 2 and counts["windows"] == 8
    f = ifcopenshell.open(str(out))
    assert f.schema_identifier == "IFC4X3_ADD2"
    assert _valid(out) == []


def test_plain_ifc_changes_schema_into_a_new_file(clean):
    src = clean / "house.ifc"
    make_house.build(str(src))
    assert call(B.open_model, str(src))["ok"]
    assert not call(SC.change_schema, "IFC4X3", "")["ok"]  # a plain file needs a target path
    assert not call(SC.change_schema, "IFC4X3", str(src))["ok"]  # never over the open file
    assert not call(SC.change_schema, "IFC4", str(clean / "same.ifc"))["ok"]  # already IFC4
    out = clean / "house-4x3.ifc"
    r = call(SC.change_schema, "IFC4X3", str(out))
    assert r["ok"] and r["open"] == str(out) and r["before"] == r["after"]
    assert ifcopenshell.open(str(out)).schema_identifier == "IFC4X3_ADD2"
    assert ifcopenshell.open(str(src)).schema == "IFC4"  # the original keeps its schema
    assert _valid(out) == []
    back = clean / "house-4.ifc"
    assert call(B.open_model, str(out))["ok"]
    assert call(SC.change_schema, "IFC4", str(back))["ok"]
    assert ifcopenshell.open(str(back)).schema == "IFC4"


def test_versioned_project_changes_schema_as_a_version(clean):
    src = clean / "house.ifc"
    make_house.build(str(src))
    nic = clean / "house.nic"
    assert call(D.import_ifc, str(src), str(nic))["ok"]
    D.close_document()
    opened = call(D.open_nic, str(nic))
    assert opened["ok"]
    assert call(B.open_model, opened["path"])["ok"]
    guid = B._model.by_type("IfcWall")[0].GlobalId
    assert call(B.set_name, json.dumps([guid]), "Edited")["ok"]
    refused = call(SC.change_schema, "IFC4X3")
    assert not refused["ok"] and "save a version first" in refused["error"]
    assert call(V.save_version, "Rename a wall")["ok"]
    r = call(SC.change_schema, "IFC4X3")
    assert r["ok"], r
    assert r["reload"] and r["from"] == "IFC4" and r["to"] == "IFC4X3"
    assert V._project.schema() == "IFC4X3_ADD2"
    assert V._project.log(limit=1)[0].message.strip() == "Change IFC schema to IFC4X3"
    # Later versions are in the new schema, and a plain commit of an IFC4 file is still refused.
    assert call(B.open_model, r["reload"])["ok"]
    assert B._model.schema_identifier == "IFC4X3_ADD2"
    assert B._model.by_guid(guid).Name == "Edited"
    assert call(B.set_name, json.dumps([guid]), "Edited again")["ok"]
    assert call(V.save_version, "After the change")["ok"]
    from kimbim.project import SchemaMismatch

    with pytest.raises(SchemaMismatch):
        V._project.commit(str(src), "an IFC4 file")


SAMPLES = ROOT / "tests" / "corpus" / "files" / "bsi" / "IFC 4.3.2.0 (IFC 4.3 ADD2)" / "Simple-Scene"


def test_the_house_converts_both_ways_without_loss(clean):
    src = clean / "house.ifc"
    make_house.build(str(src), schema="IFC4")
    f = ifcopenshell.open(str(src))
    up = SC.migrated(f, "IFC4X3")
    assert SC.loss_report(f, up)["lossless"]
    assert SC.loss_report(up, SC.migrated(up, "IFC4"))["lossless"]


def test_a_lossy_conversion_asks_first(clean):
    sample = SAMPLES / "Building-Landscaping.ifc"
    if not sample.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    assert call(B.open_model, str(sample))["ok"]
    out = clean / "landscaping-ifc4.ifc"
    asked = call(SC.change_schema, "IFC4", str(out))
    assert not asked["ok"] and asked["needs_confirm"] and not out.exists()
    changed = asked["loss"]["attributes"]
    assert any(c["attribute"] == "PredefinedType" and c["before"] == "VEGETATION" and c["after"] is None
               for c in changed)  # IFC4 has no VEGETATION
    done = call(SC.change_schema, "IFC4", str(out), "", "1")
    assert done["ok"] and out.exists() and not done["loss"]["lossless"]


def test_entities_with_no_ifc4_equivalent_are_refused(clean):
    sample = SAMPLES / "Infra-Road.ifc"
    if not sample.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    assert call(B.open_model, str(sample))["ok"]
    out = clean / "road-ifc4.ifc"
    r = call(SC.change_schema, "IFC4", str(out), "", "1")  # even accepting losses
    assert not r["ok"] and "IfcRoad" in r["error"] and not out.exists()


def test_versioned_ifc4x3_project_goes_back_to_ifc4(clean):
    src = clean / "house4x3.ifc"
    make_house.build(str(src), schema="IFC4X3")
    nic = clean / "house4x3.nic"
    assert call(D.import_ifc, str(src), str(nic))["ok"]
    D.close_document()
    opened = call(D.open_nic, str(nic))
    assert call(B.open_model, opened["path"])["ok"]
    assert V._project.schema() == "IFC4X3_ADD2"
    r = call(SC.change_schema, "IFC4")
    assert r["ok"], r
    assert V._project.schema() == "IFC4" and r["loss"]["lossless"]


def _versioned_house(clean, schema="IFC4"):
    src = clean / f"house-{schema}.ifc"
    make_house.build(str(src), schema=schema)
    nic = clean / f"house-{schema}.nic"
    assert call(D.import_ifc, str(src), str(nic))["ok"]
    D.close_document()
    opened = call(D.open_nic, str(nic))
    assert call(B.open_model, opened["path"])["ok"]
    return nic


def test_options_of_two_schemas_are_not_combined(clean):
    _versioned_house(clean)
    assert call(V.create_option, "upgrade")["ok"]
    assert call(SC.change_schema, "IFC4X3")["ok"]
    assert call(V.switch_option, "main")["ok"]
    wall = B._model.by_type("IfcWall")[0].GlobalId
    assert call(B.set_name, json.dumps([wall]), "Main edit")["ok"]
    assert call(V.save_version, "Edit on main")["ok"]  # a real three-way merge, not a fast-forward
    refused = call(V.combine_preview, "upgrade")
    assert not refused["ok"] and "IFC4X3" in refused["error"] and "Change IFC schema" in refused["error"]


def test_work_saved_with_ctrl_s_but_in_no_version_blocks_the_change(clean):
    _versioned_house(clean)
    wall = B._model.by_type("IfcWall")[0].GlobalId
    assert call(B.set_name, json.dumps([wall]), "Saved, not versioned")["ok"]
    assert call(D.save_document)["ok"]  # Ctrl+S: the file is saved, no version holds it
    refused = call(SC.change_schema, "IFC4X3")
    assert not refused["ok"] and "save a version first" in refused["error"]


def test_after_the_change_the_project_is_versioned(clean):
    _versioned_house(clean)
    wall = B._model.by_type("IfcWall")[0].GlobalId
    assert call(B.set_name, json.dumps([wall]), "Edited")["ok"]  # the session has undo history
    assert call(V.save_version, "Edit")["ok"]
    r = call(SC.change_schema, "IFC4X3")
    assert r["ok"], r
    assert not V._unversioned() and not B._dirty()
    assert B._model.schema_identifier == "IFC4X3_ADD2" and B._model.by_guid(wall).Name == "Edited"
    assert call(V.create_option, "next")["ok"]  # switching options isn't refused for "unsaved changes"


def test_ifc2x3_data_with_no_ifc4_equivalent_is_refused_clearly(clean):
    folder = ROOT / "tests" / "corpus" / "files" / "bsi" / "IFC 2.3.0.1 (IFC 2x3 TC1)"
    samples = sorted(folder.rglob("*.ifc")) if folder.exists() else []
    if not samples:
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    results = []
    for sample in samples[:3]:
        assert call(B.open_model, str(sample))["ok"]
        r = call(SC.change_schema, "IFC4", str(clean / f"{sample.stem}-4.ifc"), "", "1")
        results.append(r)
        if not r["ok"]:
            assert "cannot hold everything" in r["error"] and "NotImplementedError" not in r["error"], r["error"]
    assert results
