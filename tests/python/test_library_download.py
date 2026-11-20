# SPDX-License-Identifier: GPL-3.0-or-later
"""D216: download a library object from a web link into the office library."""
import json
from pathlib import Path

from kimbim import app_bridge as b
from kimbim import library

OBJECT = {
    "format": "kimbim-object/1",
    "id": "downloaded_lamp",
    "name": {"en": "Downloaded lamp", "es": "Lámpara descargada"},
    "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
    "params": [
        {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 0.4},
        {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.6},
    ],
    "parts": [{"id": "body", "box": {"dx": "width", "dy": "width", "dz": "height"}}],
    "symbol": [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "width"}}],
}


def test_download_an_object_from_a_link(tmp_path):
    source = tmp_path / "downloaded_lamp.nicobj"
    source.write_text(json.dumps(OBJECT), encoding="utf-8")
    destination = tmp_path / "office"
    r = json.loads(library.download_object(source.as_uri(), str(destination)))
    assert r["ok"], r
    assert Path(r["path"]).is_file() and r["ref"] == "office:downloaded_lamp"
    # a second download gets its own name
    again = json.loads(library.download_object(source.as_uri(), str(destination)))
    assert again["ok"] and Path(again["path"]).name == "downloaded_lamp-1.nicobj"

    bad = tmp_path / "bad.nicobj"
    bad.write_text("{", encoding="utf-8")
    r = json.loads(library.download_object(bad.as_uri(), str(destination)))
    assert not r["ok"] and not (destination / "bad.nicobj").exists()
    assert not json.loads(library.download_object("ftp://example.com/x.nicobj", str(destination)))["ok"]
    assert not json.loads(library.download_object(str(tmp_path / "nope.txt"), str(destination)))["ok"]

    saved = dict(library._office_paths)
    try:
        library._office_paths["folder"], library._office_paths["files"] = str(destination), []
        r = json.loads(library.download_object(source.as_uri(), str(destination)))
        assert r["ok"] and r["reloaded"] and "office:downloaded_lamp" in library._office
    finally:
        library.load_office(saved["folder"], saved["files"])
