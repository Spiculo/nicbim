# SPDX-License-Identifier: GPL-3.0-or-later
"""Revit-style phases (doc 14 9): an ordered list of named phases (the `phases` project setting), each
element created in one and optionally demolished in a later one (`KIMBIM_Phase` Created/Demolished;
an element without it is created in the first phase and never demolished). A view shows the model at
a phase through a phase filter:

* ``all`` - what exists then, new and demolished included (Revit's "Show All");
* ``complete`` - the building as it stands at the end of the phase: demolished elements hidden;
* ``new`` - only what is built in the phase;
* ``existing`` - what was there before the phase, demolished included (Revit's "Show Previous + Demo").

Elements created after the phase or demolished before it are always hidden. This sits beside the
Archicad renovation statuses (D74), which stay the quick existing/demolish/new tool.
"""
from __future__ import annotations

import json

import ifcopenshell.api.pset
import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A
from . import settings

PSET = "KIMBIM_Phase"
KEY = "phases"
VIEW_KEY = "phase_view"
FILTERS = ("all", "complete", "new", "existing")


def _names() -> list[str]:
    value = settings.current().get(KEY) or settings.DEFAULTS[KEY]
    return [str(v) for v in value]


def phases() -> str:
    """The project's phases in order and the view's phase and filter."""
    view = settings.current().get(VIEW_KEY) or settings.DEFAULTS[VIEW_KEY]
    names = _names()
    phase = view.get("phase") if view.get("phase") in names else names[-1]
    return B._dump({"ok": True, "phases": names, "phase": phase,
                    "filter": view.get("filter") if view.get("filter") in FILTERS else "all", "filters": list(FILTERS)})


def set_phases(names_json: str) -> str:
    """Replace the phase list (order matters; names must be unique and non-empty)."""
    try:
        names = [str(n).strip() for n in json.loads(names_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    return settings.set_project_settings(json.dumps({KEY: names}))


def set_phase_view(phase: str, filter: str = "all") -> str:
    """The phase and phase filter the views show."""
    if phase not in _names():
        return A._fail(f"unknown phase {phase}")
    if filter not in FILTERS:
        return A._fail(f"unknown phase filter {filter}")
    return settings.set_project_settings(json.dumps({VIEW_KEY: {"phase": phase, "filter": filter}}))


def assign_phase(guids_json: str, created: str, demolished: str = "") -> str:
    """Set the phase the elements are created in and (optionally) demolished in; one undo step."""
    if B._model is None:
        return A._fail("no model open")
    names = _names()
    if created not in names:
        return A._fail(f"unknown phase {created}")
    if demolished and (demolished not in names or names.index(demolished) < names.index(created)):
        return A._fail("an element is demolished in its own phase or a later one")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return A._fail(str(ex))
    if not elements:
        return A._fail("select elements first")

    def action():
        f = B._model
        for e in elements:
            data = ifcopenshell.util.element.get_pset(e, PSET)
            pset = f.by_id(data["id"]) if data else ifcopenshell.api.pset.add_pset(f, product=e, name=PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Created": created, "Demolished": demolished})
        return len(elements), [e.GlobalId for e in elements], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _phased():
    """(element, created index, demolished index or None) for every element with KIMBIM_Phase."""
    names = _names()
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        values = {p.Name: getattr(p.NominalValue, "wrappedValue", None) for p in pset.HasProperties}
        created = names.index(values["Created"]) if values.get("Created") in names else 0
        demolished = names.index(values["Demolished"]) if values.get("Demolished") in names else None
        for e in B._pset_users(pset):
            out.append((e, created, demolished))
    return out


def state(created: int, demolished: int | None, at: int) -> str:
    """An element's state at phase index `at`: existing, new, demolished, future or gone."""
    if created > at:
        return "future"
    if demolished is not None and demolished < at:
        return "gone"
    if demolished == at:
        return "demolished"
    return "new" if created == at else "existing"


SHOWN = {"all": {"existing", "new", "demolished"}, "complete": {"existing", "new"}, "new": {"new"},
         "existing": {"existing", "demolished"}}


def phase_filter(phase: str = "", filter: str = "") -> str:
    """What the views show at a phase: {"hidden", "demolished", "new"} GlobalIds (elements without a
    phase are existing). Empty phase/filter: the project's phase view."""
    if B._model is None:
        return A._fail("no model open")
    current = json.loads(phases())
    phase = phase or current["phase"]
    filter = filter or current["filter"]
    names = _names()
    if phase not in names or filter not in FILTERS:
        return A._fail("unknown phase or phase filter")
    at = names.index(phase)
    hidden, demolished, new = [], [], []
    for e, created, gone in _phased():
        s = state(created, gone, at)
        if s not in SHOWN[filter]:
            hidden.append(e.GlobalId)
        elif s == "demolished":
            demolished.append(e.GlobalId)
        elif s == "new":
            new.append(e.GlobalId)
    # unphased elements are existing: hidden only by the "new" filter
    if filter == "new" and at > 0:
        phased = {g for g in hidden + demolished + new}
        for e in B._model.by_type("IfcElement"):
            if e.GlobalId not in phased and not ifcopenshell.util.element.get_pset(e, PSET):
                hidden.append(e.GlobalId)
    return B._dump({"ok": True, "phase": phase, "filter": filter, "hidden": hidden, "demolished": demolished,
                    "new": new})
