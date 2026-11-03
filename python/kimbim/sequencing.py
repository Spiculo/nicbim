# SPDX-License-Identifier: GPL-3.0-or-later
"""Construction sequencing (4D, D214): dated phases and the elements assigned to them.

Phases live in the `construction_phases` project setting; each assigned element carries a
`KIMBIM_Construction` property set (Phase, Name, Start, End), so the sequence travels with the model,
copies with the element and survives versions. The schedule is a simple dated list (no resource
levelling or dependencies beyond the dates).
"""
from __future__ import annotations

import datetime as dt
import json
import uuid

import ifcopenshell.api.pset
import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A

PHASE_KEY = "construction_phases"
PSET = "KIMBIM_Construction"


def _stored() -> list[dict]:
    from . import settings as S

    data = S.current().get(PHASE_KEY, [])
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def _dates(start, end) -> tuple[dt.date, dt.date] | None:
    try:
        a = dt.date.fromisoformat(str(start))
        b = dt.date.fromisoformat(str(end))
    except ValueError:
        return None
    return (a, b) if b >= a else None


def phases() -> str:
    """The phases with the elements assigned to each and the overall span."""
    assigned: dict[str, list[str]] = {}
    if B._model is not None:
        for element in B._model.by_type("IfcProduct"):
            data = ifcopenshell.util.element.get_pset(element, PSET) or {}
            phase = data.get("Phase")
            if isinstance(phase, str) and phase:
                assigned.setdefault(phase, []).append(element.GlobalId)
    out = []
    for phase in _stored():
        elements = assigned.get(phase["id"], [])
        out.append({**phase, "elements": elements, "count": len(elements)})
    out.sort(key=lambda p: (p.get("start") or "", p.get("name") or ""))
    starts = [p["start"] for p in out if p.get("start")]
    ends = [p["end"] for p in out if p.get("end")]
    return B._dump({"ok": True, "phases": out, "start": min(starts) if starts else "",
                    "end": max(ends) if ends else ""})


def save_phase(name, start, end, color: str = "", id: str = "") -> str:
    """Add or update a phase; dates are YYYY-MM-DD and the end must not be before the start."""
    from . import settings as S

    name = str(name or "").strip()
    if not name:
        return A._fail("type a phase name")
    dates = _dates(start, end)
    if dates is None:
        return A._fail("the dates are YYYY-MM-DD and the end must not be before the start")
    phase = {"id": str(id or uuid.uuid4().hex[:12]), "name": name,
             "start": dates[0].isoformat(), "end": dates[1].isoformat(),
             "color": str(color or "").strip()}
    table = [p for p in _stored() if p.get("id") != phase["id"]] + [phase]
    r = json.loads(S.set_project_settings(json.dumps({PHASE_KEY: table})))
    return B._dump({**r, "phase": phase})


def delete_phase(id: str) -> str:
    """Remove a phase and clear it from the elements that carried it."""
    from . import settings as S

    table = _stored()
    kept = [p for p in table if p.get("id") != id]
    if len(kept) == len(table):
        return A._fail(f"unknown phase {id}")
    elements = [e for e in B._model.by_type("IfcProduct")
                if (ifcopenshell.util.element.get_pset(e, PSET) or {}).get("Phase") == id] if B._model else []

    def action():
        for e in elements:
            data = ifcopenshell.util.element.get_pset(e, PSET)
            if data:
                ifcopenshell.api.pset.remove_pset(B._model, product=e, pset=B._model.by_id(data["id"]))
        return len(elements), [e.GlobalId for e in elements], []

    try:
        result = B._run(action) if B._model is not None else {"ok": True}
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    saved = json.loads(S.set_project_settings(json.dumps({PHASE_KEY: kept})))
    return B._dump({**saved, "cleared": len(elements), "guids": result.get("guids", [])})


def assign_phase(guids_json: str, phase_id: str) -> str:
    """Assign selected elements to a phase; an empty phase clears their construction data."""
    phase = next((p for p in _stored() if p["id"] == phase_id), None) if phase_id else None
    if phase_id and phase is None:
        return A._fail(f"unknown phase {phase_id}")
    try:
        guids = json.loads(guids_json)
    except ValueError:
        return A._fail("bad selection")
    if not isinstance(guids, list) or not guids:
        return A._fail("select the elements to put in the phase")
    elements = [A._by_guid(g) for g in guids]
    elements = [e for e in elements if e is not None and e.is_a("IfcProduct")]
    if not elements:
        return A._fail("select model elements")

    def action():
        f = B._model
        for e in elements:
            data = ifcopenshell.util.element.get_pset(e, PSET)
            if phase is None:
                if data:
                    ifcopenshell.api.pset.remove_pset(f, product=e, pset=f.by_id(data["id"]))
                continue
            pset = f.by_id(data["id"]) if data else ifcopenshell.api.pset.add_pset(f, product=e, name=PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
                "Phase": phase["id"], "Name": phase["name"],
                "Start": phase["start"], "End": phase["end"]})
        return len(elements), [e.GlobalId for e in elements], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "phase": phase["id"] if phase else ""})
