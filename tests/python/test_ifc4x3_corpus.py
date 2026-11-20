# SPDX-License-Identifier: GPL-3.0-or-later
"""IFC4X3 in the app's own workflow (D241, docs/02): every buildingSMART IFC 4.3 ADD2 sample in the corpus opens
as a .nic, its products mesh, an edit is saved as a version, and the reopened project is still IFC4X3_ADD2 with
the edit in it. Needs the corpus (pixi run fetch-corpus)."""
import json
import pathlib

import ifcopenshell
import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import nicfile as K
from kimbim import versioning as V

ROOT = pathlib.Path(__file__).resolve().parents[2]
FOLDER = ROOT / "tests" / "corpus" / "files" / "bsi" / "IFC 4.3.2.0 (IFC 4.3 ADD2)" / "Simple-Scene"
FILES = sorted(FOLDER.glob("*.ifc")) if FOLDER.exists() else []


def call(fn, *args):
    return json.loads(fn(*args))


@pytest.mark.golden
@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_ifc4x3_sample_opens_edits_and_versions(path, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    assert ifcopenshell.open(str(path)).schema_identifier == "IFC4X3_ADD2"
    nic = tmp_path / f"{path.stem}.nic"
    made = call(D.import_ifc, str(path), str(nic))
    assert made["ok"], made
    D.close_document()
    try:
        opened = call(D.open_nic, str(nic))
        assert opened["ok"], opened
        assert call(B.open_model, opened["path"])["ok"]
        assert B._model.schema_identifier == "IFC4X3_ADD2"
        products = [p for p in B._model.by_type("IfcProduct") if p.Representation is not None]
        assert products, "the sample has products with geometry"
        meshes = B.mesh_elements(json.dumps([p.GlobalId for p in products[:50]]))
        assert meshes is not None, "its products mesh"
        assert len(meshes[1]) > 0, "the meshes have vertices"  # (meta, vertices bytes, ...)
        target = products[0]
        assert call(B.set_name, json.dumps([target.GlobalId]), "Edited in NicBim")["ok"]
        saved = call(V.save_version, "Rename one element")
        assert saved["ok"], saved
        D.close_document()
        again = call(D.open_nic, str(nic))
        assert again["ok"], again
        assert call(B.open_model, again["path"])["ok"]
        assert B._model.schema_identifier == "IFC4X3_ADD2"
        assert B._model.by_guid(target.GlobalId).Name == "Edited in NicBim"
        assert len(B._model.by_type("IfcProduct")) == len(ifcopenshell.open(str(path)).by_type("IfcProduct"))
    finally:
        D.close_document()
