# SPDX-License-Identifier: GPL-3.0-or-later
"""The delivery package (D254): one call writes what a project hands over.

    <out>/
      <number> <name> - drawing set.pdf     every sheet, in sheet order (combined)
      sheets/<number> <title>.pdf           one PDF per sheet
      dxf/<number> <title>.dxf              one DXF per sheet
      ifc/<number> <name>.ifc               the model (georeferenced when the project is on the map)
      schedules/<name>.csv                  every schedule
      transmittal.md / transmittal.json     what is in the package, which version it describes, open issues
      <number> <name>.zip                   all of the above (optional)
"""
from __future__ import annotations

import builtins
import json
import pathlib
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone

from ... import app_bridge as B
from ... import checks as C
from ... import documents as D
from ... import schedules as SC
from ... import sheets as SH
from ... import site as SITE
from ... import versioning as V
from .. import messages
from ..catalogue import AgentError, bridge, tool
from ..render import app_binary, app_env


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name or "")).strip(" .")
    return name[:80] or "untitled"


def _pdfs(numbers: list[str], outs: list[pathlib.Path]) -> list[str]:
    """Render sheets to PDF with the app binary, exporting the model once. Returns problems (empty when fine)."""
    app = app_binary()
    if app is None:
        raise AgentError("render_failed", hint=messages.text("hint_no_app"))
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        ifc = str(pathlib.Path(tmp) / "model.ifc")
        bridge(D.export_ifc, ifc)
        for number, out in zip(numbers, outs):
            try:
                done = subprocess.run([str(app), "--export-sheet", number, ifc, str(out)], capture_output=True,
                                      text=True, timeout=600, env=app_env())
            except (OSError, subprocess.SubprocessError) as ex:
                problems.append(f"sheet {number}: {ex}")
                continue
            if done.returncode != 0 or not out.exists():
                problems.append(f"sheet {number}: {(done.stderr or done.stdout or str(done.returncode)).strip()[:300]}")
    return problems


def _combine(paths: list[pathlib.Path], out: pathlib.Path) -> bool:
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # older PyMuPDF
        except ImportError:
            return False
    book = pymupdf.open()
    for path in paths:
        with pymupdf.open(str(path)) as part:
            book.insert_pdf(part)
    book.save(str(out))
    book.close()
    return True


@tool("deliver.package", {"required": ["out"], "properties": {
    "out": {"type": "string", "description": "The folder to write the package into (created if missing)."},
    "sheets": {"type": "array", "items": {"type": "string"},
               "description": "Sheet numbers to include (default every sheet)."},
    "pdf": {"type": "boolean", "description": "Sheets as PDF and the combined drawing set (default true)."},
    "dxf": {"type": "boolean", "description": "Sheets as DXF (default true)."},
    "ifc": {"type": "boolean", "description": "The model as IFC (default true)."},
    "schedules": {"type": "boolean", "description": "Every schedule as CSV (default true)."},
    "checks": {"type": "boolean", "description": "Run the model check and list its issues in the transmittal "
                                                 "(default true)."},
    "zip": {"type": "boolean", "description": "Also zip the package (default true)."},
    "note": {"type": "string", "description": "A line for the transmittal, e.g. \"Anteproyecto, revisión B\"."}}})
def package(session, out, sheets=None, pdf=True, dxf=True, ifc=True, schedules=True, checks=True, zip=True,
            note=""):
    """Write the delivery package: the drawing set as one PDF and per sheet, DXF sheets, the IFC model
    (georeferenced when the project is on the map), schedules as CSV and a transmittal listing the contents,
    the version it describes and open issues; optionally zipped. Save a version first so the transmittal names it."""
    root = pathlib.Path(out)
    root.mkdir(parents=True, exist_ok=True)
    info = bridge(SH.project_info)
    number, name = info.get("number") or "", info.get("name") or ""
    stem = _safe(" ".join(x for x in (number, name) if x) or "project")
    all_sheets = bridge(SH.sheets)["sheets"]
    wanted = [s for s in all_sheets if not sheets or s["number"] in sheets]
    if sheets and len(wanted) < len(sheets):
        missing = sorted(set(sheets) - {s["number"] for s in wanted})
        raise AgentError("not_found", what=", ".join(missing))
    if (pdf or dxf) and not wanted:
        raise AgentError("bad_input", hint="the project has no sheets: create sheets and place drawings first "
                                           "(sheets.create, sheets.place_drawing)")
    files: list[dict] = []
    problems: list[str] = []

    def add(path: pathlib.Path, kind: str, **extra):
        files.append({"path": str(path.relative_to(root)).replace("\\", "/"), "kind": kind,
                      "bytes": path.stat().st_size, **extra})

    if pdf and wanted:
        folder = root / "sheets"
        folder.mkdir(exist_ok=True)
        outs = [folder / f"{_safe(s['number'])} {_safe(s['title'])}.pdf" for s in wanted]
        problems += _pdfs([s["number"] for s in wanted], outs)
        done = [p for p in outs if p.exists()]
        for s, p in builtins.zip(wanted, outs):  # `zip` is the parameter here
            if p.exists():
                add(p, "sheet pdf", sheet=s["number"], title=s["title"], paper=s.get("paper", ""))
        if done:
            combined = root / f"{stem} - drawing set.pdf"
            if _combine(done, combined):
                add(combined, "drawing set", sheets=len(done))
            else:
                problems.append("the combined PDF needs PyMuPDF; the per-sheet PDFs are there")
    if dxf and wanted:
        folder = root / "dxf"
        folder.mkdir(exist_ok=True)
        for s in wanted:
            path = folder / f"{_safe(s['number'])} {_safe(s['title'])}.dxf"
            try:
                bridge(B.export_sheet_dxf, s["number"], str(path))
                add(path, "sheet dxf", sheet=s["number"])
            except AgentError as ex:
                problems.append(f"DXF of sheet {s['number']}: {ex.envelope()['error'].get('hint', '')}")
    if ifc:
        folder = root / "ifc"
        folder.mkdir(exist_ok=True)
        path = folder / f"{stem}.ifc"
        bridge(D.export_ifc, str(path))
        add(path, "ifc", schema=B._model.schema)
    if schedules:
        folder = root / "schedules"
        for scheme in SC.schemes():
            folder.mkdir(exist_ok=True)
            path = folder / f"{_safe(scheme.get('name') or scheme['id'])}.csv"
            try:
                bridge(SC.export_schedule, scheme["id"], False, str(path))
                add(path, "schedule", schedule=scheme.get("name") or scheme["id"])
            except AgentError as ex:
                problems.append(f"schedule {scheme.get('name')}: {ex.envelope()['error'].get('hint', '')}")
    issues: list[dict] = []
    if checks:
        try:
            r = bridge(C.run_check, "model", "{}")
            issues = [{"severity": i.get("severity", ""), "message": i.get("message") or i.get("title", "")}
                      for i in (r.get("issues") or [])][:200]
        except AgentError as ex:
            problems.append(f"model check: {ex.envelope()['error'].get('hint', '')}")
    state = json.loads(V.project_state()) if V._project is not None else {}
    head = state.get("head") or {}
    location = json.loads(SITE.site_state())
    transmittal = {
        "project": {"number": number, "name": name, "client": info.get("client", ""),
                    "address": info.get("address", "")},
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "version": {"id": head.get("id", "") if isinstance(head, dict) else str(head),
                    "message": head.get("message", "") if isinstance(head, dict) else "",
                    "option": state.get("option", ""), "unsaved_changes": bool(state.get("dirty", False))},
        "location": {"latitude": location.get("latitude"), "longitude": location.get("longitude"),
                     "crs": ((location.get("georeference") or {}).get("crs") or {}).get("name", "")},
        "files": files, "issues": issues, "problems": problems,
    }
    (root / "transmittal.json").write_text(json.dumps(transmittal, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Transmittal — {number} {name}".rstrip(), "",
             f"- Date: {transmittal['date'][:10]}",
             f"- Client: {info.get('client', '')}", f"- Address: {info.get('address', '')}"]
    if note:
        lines.append(f"- Note: {note}")
    v = transmittal["version"]
    lines.append(f"- Version: {v['id'][:12] or '(not saved)'} {v['message']}"
                 + (" — with unsaved changes" if v["unsaved_changes"] else ""))
    if transmittal["location"]["crs"]:
        loc = transmittal["location"]
        lines.append(f"- Location: {loc['latitude']:.6f}, {loc['longitude']:.6f} ({loc['crs']})")
    lines += ["", "## Contents", "", "| File | Kind |", "|---|---|"]
    lines += [f"| {f['path']} | {f['kind']} |" for f in files]
    if issues:
        lines += ["", f"## Open issues ({len(issues)})", ""] + [f"- {i['severity']}: {i['message']}" for i in issues]
    if problems:
        lines += ["", "## Not produced", ""] + [f"- {p}" for p in problems]
    (root / "transmittal.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    add(root / "transmittal.md", "transmittal")
    archive = ""
    if zip:
        path = root / f"{stem}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files + [{"path": "transmittal.json"}]:
                z.write(root / f["path"], f["path"])
        archive = str(path)
    return {"folder": str(root), "files": len(files), "zip": archive, "problems": problems,
            "issues": len(issues), "version": v["id"][:12]}
