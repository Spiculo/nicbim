# SPDX-License-Identifier: GPL-3.0-or-later
"""Point-cloud import: XYZ/PTS/CSV text, uncompressed LAS, decimation to markers, the proxy and its
KIMBIM_PointCloud property set, IFC2X3 fallback, error reports and a saved-model validation."""
import json
import os
import pathlib
import struct
import subprocess

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as B
from kimbim import pointcloud as P
from kimbim.testing import _reset_owner, build_model


def call(fn, *args):
    return json.loads(fn(*args))


def open_model(schema="IFC4"):
    f = build_model(schema=schema, walls=0)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


def issues(model=None):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model or B._model, logger, express_rules=True)
    return logger.statements


def write(tmp_path, name, content):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def las_file() -> bytes:
    """A LAS 1.2 file with three points (scale 1 cm)."""
    data = bytearray(227)
    data[0:4] = b"LASF"
    data[24], data[25] = 1, 2
    struct.pack_into("<H", data, 94, 227)
    struct.pack_into("<I", data, 96, 227)
    data[104] = 0
    struct.pack_into("<H", data, 105, 20)
    struct.pack_into("<I", data, 107, 3)
    struct.pack_into("<3d", data, 131, 0.01, 0.01, 0.01)
    struct.pack_into("<3d", data, 155, 0.0, 0.0, 0.0)
    for x, y, z in ((0, 0, 0), (100, 0, 0), (0, 100, 0)):
        data += struct.pack("<3i", x, y, z) + b"\x00" * 8
    return bytes(data)


def laz_file() -> bytes:
    """The same three points as `las_file`, compressed with lazrs."""
    import io

    import lazrs

    records = b"".join(struct.pack("<3i", *p) + b"\x00" * 8
                       for p in ((0, 0, 0), (100, 0, 0), (0, 100, 0)))
    vlr = lazrs.LazVlr.new_for_compression(0, 0)
    out = io.BytesIO()
    compressor = lazrs.LasZipCompressor(out, vlr)
    compressor.compress_many(records)
    compressor.done()
    header_size = 227
    vlr_data = vlr.record_data()
    offset = header_size + 54 + len(vlr_data)
    data = bytearray(header_size)
    data[0:4] = b"LASF"
    data[24], data[25] = 1, 2
    struct.pack_into("<H", data, 94, header_size)
    struct.pack_into("<I", data, 96, offset)
    data[104] = 0
    struct.pack_into("<H", data, 105, 20)
    struct.pack_into("<I", data, 107, 3)
    struct.pack_into("<3d", data, 131, 0.01, 0.01, 0.01)
    struct.pack_into("<3d", data, 155, 0.0, 0.0, 0.0)
    struct.pack_into("<I", data, 100, 1)  # one VLR
    vlr_block = (b"\x00\x00" + b"laszip encoded".ljust(16, b"\x00") + struct.pack("<HH", 22204, len(vlr_data))
                 + b"LASzip VLR".ljust(32, b"\x00") + vlr_data)
    return bytes(data) + vlr_block + out.getvalue()


def test_pointcloud_formats():
    assert call(P.pointcloud_formats) == {"ok": True,
                                          "formats": ["xyz", "pts", "csv", "txt", "las", "laz", "e57"]}


def test_xyz_points_become_markers(tmp_path):
    f, level = open_model()
    path = write(tmp_path, "scan.xyz", "0 0 0\n1 0 0\n0 1 0\n")
    r = call(P.import_pointcloud, path, level, json.dumps({"marker": 0.05, "name": "Scan"}))
    assert r["ok"], r
    assert r["format"] == "xyz" and r["points"] == 3 and r["imported"] == 3
    assert r["triangles"] == 12  # four per point
    assert r["bounds"] == {"min": [-0.05, -0.05, 0.0], "max": [1.05, 1.05, 0.1]}
    element = f.by_guid(r["guid"])
    assert element.is_a("IfcBuildingElementProxy") and element.ObjectType == "Imported point cloud"
    data = ifcopenshell.util.element.get_pset(element, P.PSET)
    assert data["Points"] == 3 and data["Imported"] == 3 and data["Format"] == "xyz"
    assert json.loads(data["Bounds"]) == r["bounds"]
    assert issues() == []


def test_pts_count_line_and_transforms(tmp_path):
    _f, level = open_model()
    path = write(tmp_path, "scan.pts", "2\n0 0 0 255 0 0\n100 100 100 0 255 0\n")
    r = call(P.import_pointcloud, path, level, json.dumps({"scale": 0.01, "x": 5, "rotation": 90}))
    assert r["ok"], r
    assert r["points"] == 2 and r["imported"] == 2
    assert r["bounds"] == {"min": [3.97, -0.03, 0.0], "max": [5.03, 1.03, 1.06]}


def test_csv_header_and_decimation(tmp_path):
    _f, level = open_model()
    rows = ["x,y,z"] + [f"{k},0,0" for k in range(100)]
    path = write(tmp_path, "scan.csv", "\n".join(rows) + "\n")
    r = call(P.import_pointcloud, path, level, json.dumps({"max_points": 10}))
    assert r["ok"], r
    assert r["points"] == 100 and r["imported"] == 10
    assert r["triangles"] == 40


def test_uncompressed_las(tmp_path):
    f, level = open_model()
    r = call(P.import_pointcloud, write(tmp_path, "scan.las", las_file()), level,
             json.dumps({"marker": 0.01}))
    assert r["ok"], r
    assert r["format"] == "las" and r["points"] == 3
    assert r["bounds"] == {"min": [-0.01, -0.01, 0.0], "max": [1.01, 1.01, 0.02]}
    assert ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), P.PSET)["Format"] == "las"
    assert issues() == []


def test_compressed_laz(tmp_path):
    f, level = open_model()
    r = call(P.import_pointcloud, write(tmp_path, "scan.laz", laz_file()), level,
             json.dumps({"marker": 0.01}))
    assert r["ok"], r
    assert r["format"] == "laz" and r["points"] == 3
    assert r["bounds"] == {"min": [-0.01, -0.01, 0.0], "max": [1.01, 1.01, 0.02]}
    assert ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), P.PSET)["Format"] == "laz"
    assert issues() == []


def e57_file(tmp_path):
    root = pathlib.Path(__file__).resolve().parents[2]
    helper = root / "build" / "e57dump" / ("e57dump.exe" if os.name == "nt" else "e57dump")
    if not helper.is_file():
        pytest.skip("e57dump is not built (run `pixi run e57dump-build`)")
    path = tmp_path / "scan.e57"
    subprocess.run([str(helper), "--write-simple", str(path)], check=True, capture_output=True)
    return path


def test_e57_scan(tmp_path):
    f, level = open_model()
    path = e57_file(tmp_path)
    r = call(P.import_pointcloud, str(path), level, json.dumps({"marker": 0.05}))
    assert r["ok"], r
    assert r["format"] == "e57" and r["points"] == 3
    assert r["bounds"] == {"min": [-0.05, -0.05, 0.0], "max": [1.05, 1.05, 0.1]}
    assert ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), P.PSET)["Format"] == "e57"
    assert issues() == []


def test_a_broken_laz_is_reported(tmp_path):
    _f, level = open_model()
    r = call(P.import_pointcloud, write(tmp_path, "scan.laz", b"LASF" + b"\x00" * 300), level)
    assert r["ok"] is False and "LAS" in r["error"]


@pytest.mark.parametrize("name,content", [
    ("empty.xyz", ""),
    ("notes.txt", "no points here"),
    ("tiny.csv", "x,y,z\n1,2\n"),
    ("broken.las", b"NOTLAS" + b"\x00" * 300),
    ("mesh.obj", "v 0 0 0"),
])
def test_bad_files_are_reported_not_raised(tmp_path, name, content):
    f, level = open_model()
    r = call(P.import_pointcloud, write(tmp_path, name, content), level)
    assert r["ok"] is False and r["error"]
    assert not f.by_type("IfcBuildingElementProxy")


def test_missing_file_and_bad_options(tmp_path):
    _f, level = open_model()
    path = write(tmp_path, "scan.xyz", "0 0 0\n1 0 0\n0 1 0\n")
    assert call(P.import_pointcloud, str(tmp_path / "absent.xyz"), level)["ok"] is False
    assert call(P.import_pointcloud, "", level)["ok"] is False
    for options in ("not json", json.dumps({"scale": 0}), json.dumps({"max_points": 2}),
                    json.dumps({"marker": 5}), json.dumps([1, 2])):
        r = call(P.import_pointcloud, path, level, options)
        assert r["ok"] is False and r["error"], options


def test_saved_model_validates_and_ifc2x3(tmp_path):
    f, level = open_model()
    assert call(P.import_pointcloud, write(tmp_path, "scan.xyz", "0 0 0\n1 0 0\n0 1 0\n"), level)["ok"]
    path = tmp_path / "cloud.ifc"
    f.write(str(path))
    written = ifcopenshell.open(str(path))
    assert len(written.by_type("IfcBuildingElementProxy")) == 1
    assert issues(written) == []
    _reset_owner()
    try:
        f, level = open_model("IFC2X3")
        r = call(P.import_pointcloud, write(tmp_path, "scan2.xyz", "0 0 0\n1 0 0\n0 1 0\n"), level)
        assert r["ok"], r
        assert issues() == []
    finally:
        _reset_owner()


def test_agent_tools_are_registered():
    from kimbim.agent import catalogue
    from kimbim.agent.tools import imports  # noqa: F401  (registers the import tools)

    assert "import.pointcloud" in catalogue.TOOLS and catalogue.TOOLS["import.pointcloud"].writes
    assert "import.pointcloud_formats" in catalogue.TOOLS
    assert not catalogue.TOOLS["import.pointcloud_formats"].writes
