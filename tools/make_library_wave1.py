# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes the D256 library wave 1 (objects for the five benchmark projects) into python/kimbim/bundled_objects.

The objects are data (.nicobj, doc 16); this script only keeps them consistent while they are authored. Run it
again after editing an object here: it overwrites the wave's files and leaves the others alone.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "python" / "kimbim" / "bundled_objects"


def L(en, es):
    return {"en": en, "es": es}


def P(key, en, es, default, kind="length", **extra):
    return {"key": key, "kind": kind, "label": L(en, es), "default": default, **extra}


WDH = lambda w, d, h: [P("width", "Width", "Ancho", w), P("depth", "Depth", "Fondo", d),  # noqa: E731
                       P("height", "Height", "Altura", h)]
M = lambda **kw: {k: {"label": L(*v[0]), "default": v[1]} for k, v in kw.items()}  # noqa: E731
BODY = lambda default: M(body=(("Material", "Material"), default))  # noqa: E731
RECT = [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}}]


def obj(id, en, es, category, ifc, params, parts, symbol=None, materials=None):
    d = {"format": "kimbim-object/1", "id": id, "name": L(en, es), "category": category, "ifc": ifc,
         "params": params}
    if materials:
        d["materials"] = materials
    d["parts"] = parts
    d["symbol"] = symbol if symbol is not None else RECT
    return d


def furn(t, x2=None):
    # USERDEFINED needs the element type's name (IFC rule); the IFC2X3 type has no predefined type
    name = x2 or t.title()
    return {"IFC4": ["IfcFurnitureType", t, name if t == "USERDEFINED" else None], "IFC2X3": ["IfcFurnitureType", None, name]}


def user(cls, name):
    return {"IFC4": [cls, "USERDEFINED", name], "IFC2X3": ["IfcBuildingElementProxyType", "USERDEFINED", name]}


def legs(z_top, inset=0.04, size=0.04, mat="frame"):
    return {"id": "leg", "material": mat, "repeat": {"count": 4},
            "box": {"x": f"if(i % 2 == 0, {inset}, width - {inset} - {size})",
                    "y": f"if(i < 2, {inset}, depth - {inset} - {size})", "dx": size, "dy": size, "dz": z_top}}


OBJECTS = [
    # ---------------------------------------------------------------- office
    obj("office_chair", "Office chair", "Silla de oficina", "office", furn("CHAIR"), WDH(0.62, 0.62, 1.0), [
        {"id": "base", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "r": "width * 0.45", "h": 0.05}},
        {"id": "column", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "z": 0.05, "r": 0.025, "h": 0.36}},
        {"id": "seat", "material": "body", "rounded_box": {"x": "width * 0.1", "y": "depth * 0.1", "z": 0.41, "dx": "width * 0.8", "dy": "depth * 0.75", "dz": 0.07, "r": 0.06}},
        {"id": "back", "material": "body", "rounded_box": {"x": "width * 0.12", "y": "depth * 0.82", "z": 0.52, "dx": "width * 0.76", "dy": 0.06, "dz": "height - 0.52", "r": 0.025}}],
        [{"circle": {"cx": "width / 2", "cy": "depth / 2", "r": "width * 0.45"}},
         {"rect": {"x": "width * 0.1", "y": "depth * 0.1", "dx": "width * 0.8", "dy": "depth * 0.75"}}],
        M(body=(("Upholstery", "Tapizado"), "Fabric"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("meeting_table", "Meeting table", "Mesa de reuniones", "office", furn("TABLE"),
        WDH(2.4, 1.1, 0.75) + [P("seats", "Seats", "Puestos", 8, "count", min=2, max=20)], [
        {"id": "top", "material": "top", "rounded_box": {"z": "height - 0.03", "dx": "width", "dy": "depth", "dz": 0.03, "r": "min(0.15, depth / 4)"}},
        {"id": "pedestal", "material": "frame", "repeat": {"count": 2}, "box": {"x": "if(i == 0, width * 0.2, width * 0.8 - 0.08)", "y": "depth / 2 - 0.25", "dx": 0.08, "dy": 0.5, "dz": "height - 0.03"}}],
        [{"line": {"points": [{"rounded_rect": [0, 0, "width", "depth", "min(0.15, depth / 4)"], "n": 3}], "closed": True}}],
        M(top=(("Top", "Tablero"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("filing_cabinet", "Filing cabinet", "Archivador", "office", furn("FILECABINET", "File cabinet"),
        WDH(0.45, 0.6, 1.3) + [P("drawers", "Drawers", "Cajones", 4, "count", min=1, max=6)], [
        {"id": "body", "material": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}},
        {"id": "front", "material": "body", "repeat": {"count": "drawers"}, "box": {"x": 0.01, "y": -0.01, "z": "0.02 + (height - 0.04) * i / drawers", "dx": "width - 0.02", "dy": 0.01, "dz": "(height - 0.04) / drawers - 0.01"}}],
        RECT + [{"line": {"points": [[0, 0.02], ["width", 0.02]]}}], BODY("Steel")),
    obj("storage_cabinet", "Storage cabinet", "Armario de guardado", "office", furn("SHELF", "Cabinet"),
        WDH(0.9, 0.45, 1.9), [
        {"id": "body", "material": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}},
        {"id": "door_line", "material": "body", "box": {"x": "width / 2 - 0.002", "y": -0.005, "z": 0.05, "dx": 0.004, "dy": 0.005, "dz": "height - 0.1"}}],
        RECT + [{"line": {"points": [["width / 2", 0], ["width / 2", "depth"]]}}], BODY("Timber - finish")),
    obj("workstation", "Workstation", "Puesto de trabajo", "office", furn("DESK"),
        WDH(1.6, 0.8, 0.75) + [P("screen", "Screen height", "Altura de mampara", 0.4)], [
        {"id": "top", "material": "top", "box": {"z": "height - 0.025", "dx": "width", "dy": "depth", "dz": 0.025}},
        {"id": "side", "material": "frame", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0.03, width - 0.06)", "y": 0.05, "dx": 0.03, "dy": "depth - 0.1", "dz": "height - 0.025"}},
        {"id": "screen", "material": "screen", "box": {"y": "depth - 0.03", "z": "height", "dx": "width", "dy": 0.03, "dz": "screen"}},
        {"id": "monitor", "material": "frame", "box": {"x": "width / 2 - 0.3", "y": "depth - 0.25", "z": "height + 0.12", "dx": 0.6, "dy": 0.03, "dz": 0.35}}],
        RECT + [{"line": {"points": [["width / 2 - 0.3", "depth - 0.25"], ["width / 2 + 0.3", "depth - 0.25"]]}}],
        M(top=(("Top", "Tablero"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"),
          screen=(("Screen", "Mampara"), "Fabric"))),
    # ---------------------------------------------------------------- education
    obj("student_desk", "Student desk", "Pupitre", "education", furn("DESK"), WDH(0.7, 0.5, 0.72), [
        {"id": "top", "material": "top", "box": {"z": "height - 0.02", "dx": "width", "dy": "depth", "dz": 0.02}},
        legs("height - 0.02", 0.03, 0.03),
        {"id": "tray", "material": "frame", "box": {"x": 0.03, "y": 0.1, "z": "height - 0.15", "dx": "width - 0.06", "dy": "depth - 0.13", "dz": 0.01}}],
        materials=M(top=(("Top", "Tablero"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("student_chair", "Student chair", "Silla escolar", "education", furn("CHAIR"), WDH(0.42, 0.45, 0.8), [
        legs(0.43, 0.02, 0.025),
        {"id": "seat", "material": "body", "rounded_box": {"z": 0.43, "dx": "width", "dy": "depth", "dz": 0.02, "r": 0.04}},
        {"id": "back", "material": "body", "rounded_box": {"y": "depth - 0.03", "z": 0.55, "dx": "width", "dy": 0.02, "dz": "height - 0.55", "r": 0.01}}],
        [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
         {"line": {"points": [[0, "depth - 0.03"], ["width", "depth - 0.03"]]}}],
        M(body=(("Shell", "Asiento"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("teacher_desk", "Teacher desk", "Escritorio docente", "education", furn("DESK"), WDH(1.4, 0.7, 0.75), [
        {"id": "top", "material": "body", "box": {"z": "height - 0.03", "dx": "width", "dy": "depth", "dz": 0.03}},
        {"id": "drawers", "material": "body", "box": {"x": "width - 0.42", "y": 0.02, "dx": 0.4, "dy": "depth - 0.04", "dz": "height - 0.03"}},
        {"id": "side", "material": "body", "box": {"x": 0.02, "y": 0.02, "dx": 0.025, "dy": "depth - 0.04", "dz": "height - 0.03"}}],
        materials=BODY("Timber - finish")),
    obj("whiteboard", "Whiteboard", "Pizarra blanca", "education", user("IfcFurnitureType", "WHITEBOARD"),
        [P("width", "Width", "Ancho", 3.0), P("height", "Board height", "Altura de la pizarra", 1.2),
         P("sill", "Bottom above floor", "Altura inferior", 0.9), P("depth", "Depth", "Fondo", 0.06)], [
        {"id": "board", "material": "body", "box": {"z": "sill", "dx": "width", "dy": 0.02, "dz": "height"}},
        {"id": "tray", "material": "frame", "box": {"y": -0.04, "z": "sill - 0.02", "dx": "width", "dy": "depth", "dz": 0.02}}],
        [{"rect": {"x": 0, "y": -0.04, "dx": "width", "dy": "depth"}}],
        M(body=(("Board", "Pizarra"), "Paint - white"), frame=(("Frame", "Marco"), "Aluminium"))),
    obj("lockers", "Lockers", "Casilleros", "education", user("IfcFurnitureType", "LOCKER"),
        WDH(1.2, 0.45, 1.8) + [P("columns", "Columns", "Columnas", 4, "count", min=1, max=12),
                                P("rows", "Rows", "Filas", 2, "count", min=1, max=6)], [
        {"id": "body", "material": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}},
        {"id": "joint_v", "material": "body", "repeat": {"count": "columns - 1"}, "box": {"x": "width * (i + 1) / columns - 0.002", "y": -0.004, "dx": 0.004, "dy": 0.004, "dz": "height"}},
        {"id": "joint_h", "material": "body", "repeat": {"count": "rows - 1"}, "box": {"y": -0.004, "z": "height * (i + 1) / rows - 0.002", "dx": "width", "dy": 0.004, "dz": 0.004}}],
        RECT + [{"repeat": {"count": "columns - 1"}, "line": {"points": [["width * (i + 1) / columns", 0], ["width * (i + 1) / columns", 0.05]]}}],
        BODY("Steel")),
    obj("library_shelving", "Library shelving", "Estantería de biblioteca", "education", furn("SHELF"),
        WDH(1.0, 0.6, 1.8) + [P("shelves", "Shelves per side", "Estantes por lado", 5, "count", min=2, max=8)], [
        {"id": "end", "material": "body", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0, width - 0.025)", "dx": 0.025, "dy": "depth", "dz": "height"}},
        {"id": "spine", "material": "body", "box": {"x": 0.025, "y": "depth / 2 - 0.01", "dx": "width - 0.05", "dy": 0.02, "dz": "height"}},
        {"id": "shelf", "material": "body", "repeat": {"count": "shelves"}, "box": {"x": 0.025, "z": "0.05 + (height - 0.1) * i / (shelves - 1)", "dx": "width - 0.05", "dy": "depth", "dz": 0.02}}],
        RECT + [{"line": {"points": [[0, "depth / 2"], ["width", "depth / 2"]]}}], BODY("Timber - finish")),
    obj("cafeteria_table", "Cafeteria table", "Mesa de comedor escolar", "education", furn("TABLE"),
        WDH(1.8, 0.8, 0.72), [
        {"id": "top", "material": "top", "box": {"z": "height - 0.025", "dx": "width", "dy": "depth", "dz": 0.025}},
        legs("height - 0.025", 0.06, 0.04)],
        materials=M(top=(("Top", "Tablero"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("bench", "Bench", "Banco", "furniture", furn("USERDEFINED", "Bench"), WDH(1.8, 0.4, 0.45), [
        {"id": "seat", "material": "body", "box": {"z": "height - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}},
        {"id": "support", "material": "frame", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0.1, width - 0.15)", "dx": 0.05, "dy": "depth", "dz": "height - 0.04"}}],
        materials=M(body=(("Seat", "Asiento"), "Timber"), frame=(("Frame", "Estructura"), "Steel"))),
    # ---------------------------------------------------------------- commercial
    obj("counter", "Counter", "Mostrador", "commercial", furn("USERDEFINED", "Counter"),
        WDH(2.4, 0.6, 1.05), [
        {"id": "body", "material": "body", "box": {"y": 0.03, "dx": "width", "dy": "depth - 0.03", "dz": "height - 0.04"}},
        {"id": "plinth", "material": "body", "box": {"x": 0.05, "y": 0.08, "dx": "width - 0.1", "dy": "depth - 0.1", "dz": 0.1}},
        {"id": "top", "material": "top", "box": {"z": "height - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}}],
        materials=M(body=(("Body", "Cuerpo"), "Timber - finish"), top=(("Top", "Tapa"), "Stone"))),
    obj("bar_stool", "Bar stool", "Taburete alto", "commercial", furn("CHAIR", "Stool"), WDH(0.4, 0.4, 0.75), [
        {"id": "base", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "r": "width * 0.45", "h": 0.02}},
        {"id": "column", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "z": 0.02, "r": 0.025, "h": "height - 0.07"}},
        {"id": "seat", "material": "body", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "z": "height - 0.05", "r": "width / 2", "h": 0.05}}],
        [{"circle": {"cx": "width / 2", "cy": "depth / 2", "r": "width / 2"}}],
        M(body=(("Seat", "Asiento"), "Timber - finish"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("cafe_table", "Café table", "Mesa de café", "commercial", furn("TABLE"),
        [P("width", "Diameter", "Diámetro", 0.7), P("height", "Height", "Altura", 0.75)], [
        {"id": "base", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "width / 2", "r": "width * 0.3", "h": 0.02}},
        {"id": "column", "material": "frame", "cylinder": {"cx": "width / 2", "cy": "width / 2", "z": 0.02, "r": 0.03, "h": "height - 0.05"}},
        {"id": "top", "material": "top", "cylinder": {"cx": "width / 2", "cy": "width / 2", "z": "height - 0.03", "r": "width / 2", "h": 0.03}}],
        [{"circle": {"cx": "width / 2", "cy": "width / 2", "r": "width / 2"}}],
        M(top=(("Top", "Tapa"), "Stone"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("display_shelf", "Display shelving", "Góndola de exhibición", "commercial", furn("SHELF"),
        WDH(1.2, 0.5, 1.6) + [P("shelves", "Shelves", "Estantes", 5, "count", min=2, max=8)], [
        {"id": "back", "material": "body", "box": {"y": "depth - 0.03", "dx": "width", "dy": 0.03, "dz": "height"}},
        {"id": "shelf", "material": "body", "repeat": {"count": "shelves"}, "box": {"z": "0.1 + (height - 0.15) * i / (shelves - 1)", "dx": "width", "dy": "depth * (1 - 0.3 * i / shelves)", "dz": 0.02}}],
        materials=BODY("Steel")),
    obj("checkout", "Checkout counter", "Caja registradora", "commercial", furn("USERDEFINED", "Checkout"),
        WDH(1.6, 0.8, 0.9), [
        {"id": "body", "material": "body", "rounded_box": {"dx": "width", "dy": "depth", "dz": "height", "r": 0.05}},
        {"id": "terminal", "material": "body", "box": {"x": "width - 0.45", "y": "depth / 2 - 0.15", "z": "height", "dx": 0.3, "dy": 0.25, "dz": 0.3}}],
        materials=BODY("Timber - finish")),
    obj("clothes_rack", "Clothes rail", "Perchero de exhibición", "commercial", furn("USERDEFINED", "Rail"),
        WDH(1.5, 0.5, 1.6), [
        {"id": "upright", "material": "body", "repeat": {"count": 2}, "cylinder": {"cx": "if(i == 0, 0.03, width - 0.03)", "cy": "depth / 2", "r": 0.015, "h": "height"}},
        {"id": "foot", "material": "body", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0, width - 0.06)", "dx": 0.06, "dy": "depth", "dz": 0.03}},
        {"id": "rail", "material": "body", "sweep": {"path": [[0.03, "depth / 2", "height - 0.03"], ["width - 0.03", "depth / 2", "height - 0.03"]], "r": 0.015}}],
        materials=BODY("Steel")),
    # ---------------------------------------------------------------- sanitary
    obj("urinal", "Urinal", "Mingitorio", "sanitary", {"IFC4": ["IfcSanitaryTerminalType", "URINAL", None]},
        WDH(0.36, 0.35, 0.65) + [P("rim", "Rim height", "Altura del borde", 0.6)], [
        {"id": "bowl", "material": "body", "rounded_box": {"z": "rim - height * 0.6", "dx": "width", "dy": "depth", "dz": "height", "r": "width / 2 - 0.001"}}],
        [{"line": {"points": [{"rounded_rect": [0, 0, "width", "depth", "width / 2 - 0.001"], "n": 4}], "closed": True}}],
        BODY("Porcelain")),
    obj("toilet_cubicle", "Toilet cubicle", "Cabina sanitaria", "sanitary", user("IfcFurnitureType", "CUBICLE"),
        WDH(0.9, 1.5, 2.0) + [P("door", "Door width", "Ancho de puerta", 0.6)], [
        {"id": "side", "material": "body", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0, width - 0.025)", "z": 0.15, "dx": 0.025, "dy": "depth", "dz": "height - 0.15"}},
        {"id": "front", "material": "body", "box": {"x": 0.025, "z": 0.15, "dx": "width - 0.05 - door", "dy": 0.025, "dz": "height - 0.15"}},
        {"id": "door", "material": "body", "box": {"x": "width - 0.025 - door", "z": 0.15, "dx": "door", "dy": 0.025, "dz": "height - 0.3"}}],
        [{"rect": {"x": 0, "y": 0, "dx": 0.025, "dy": "depth"}}, {"rect": {"x": "width - 0.025", "y": 0, "dx": 0.025, "dy": "depth"}},
         {"line": {"points": [[0.025, 0], ["width - 0.025 - door", 0]]}},
         {"arc": {"cx": "width - 0.025 - door", "cy": 0, "r": "door", "a0": 0, "a1": 90}},
         {"line": {"points": [["width - 0.025 - door", 0], ["width - 0.025 - door", "door"]]}}],
        BODY("Gypsum board")),
    obj("grab_bar", "Grab bar", "Barra de apoyo", "sanitary", user("IfcFurnitureType", "GRABBAR"),
        [P("width", "Length", "Largo", 0.8), P("height", "Height", "Altura", 0.75), P("depth", "Projection", "Saliente", 0.08)], [
        {"id": "bar", "material": "body", "sweep": {"path": [[0, 0, "height"], [0, "-depth", "height"], ["width", "-depth", "height"], ["width", 0, "height"]], "r": 0.017}}],
        [{"line": {"points": [[0, 0], [0, "-depth"], ["width", "-depth"], ["width", 0]]}}], BODY("Steel")),
    obj("double_sink", "Double washbasin vanity", "Mueble con doble lavatorio", "sanitary",
        {"IFC4": ["IfcSanitaryTerminalType", "WASHHANDBASIN", None]}, WDH(1.4, 0.5, 0.85), [
        {"id": "cabinet", "material": "cabinet", "box": {"y": 0.03, "z": 0.15, "dx": "width", "dy": "depth - 0.03", "dz": "height - 0.17"}},
        {"id": "top", "material": "body", "box": {"z": "height - 0.02", "dx": "width", "dy": "depth", "dz": 0.02}},
        {"id": "basin", "material": "body", "repeat": {"count": 2}, "rounded_box": {"x": "width * (0.25 + 0.5 * i) - 0.22", "y": 0.07, "z": "height - 0.15", "dx": 0.44, "dy": 0.32, "dz": 0.13, "r": 0.1}}],
        RECT + [{"repeat": {"count": 2}, "line": {"points": [{"rounded_rect": ["width * (0.25 + 0.5 * i) - 0.22", 0.07, 0.44, 0.32, 0.1], "n": 3}], "closed": True}}],
        M(body=(("Top and basins", "Tapa y piletas"), "Porcelain"), cabinet=(("Cabinet", "Mueble"), "Timber - finish"))),
    # ---------------------------------------------------------------- kitchen and home
    obj("kitchen_island", "Kitchen island", "Isla de cocina", "kitchen", furn("USERDEFINED", "Island"),
        WDH(1.8, 0.9, 0.9), [
        {"id": "body", "material": "body", "box": {"x": 0.03, "y": 0.03, "z": 0.1, "dx": "width - 0.06", "dy": "depth - 0.06", "dz": "height - 0.14"}},
        {"id": "plinth", "material": "body", "box": {"x": 0.08, "y": 0.08, "dx": "width - 0.16", "dy": "depth - 0.16", "dz": 0.1}},
        {"id": "top", "material": "top", "box": {"z": "height - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}}],
        materials=M(body=(("Body", "Cuerpo"), "Timber - finish"), top=(("Top", "Mesada"), "Stone"))),
    obj("washing_machine", "Washing machine", "Lavarropas", "kitchen",
        {"IFC4": ["IfcElectricApplianceType", "WASHINGMACHINE", None]}, WDH(0.6, 0.6, 0.85), [
        {"id": "body", "material": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}},
        {"id": "door", "material": "glass", "cylinder": {"cx": "width / 2", "cy": "height * 0.55", "r": 0.17, "h": 0.03}, "axes": ["x", "z", "-y"]}],
        RECT + [{"line": {"points": [[0, 0.03], ["width", 0.03]]}}],
        M(body=(("Body", "Cuerpo"), "Paint - white"), glass=(("Door", "Puerta"), "Glass"))),
    obj("dining_set", "Dining table with chairs", "Mesa de comedor con sillas", "furniture", furn("TABLE"),
        WDH(1.6, 0.9, 0.75) + [P("chairs", "Chairs per side", "Sillas por lado", 2, "count", min=1, max=5)], [
        {"id": "top", "material": "body", "box": {"z": "height - 0.03", "dx": "width", "dy": "depth", "dz": 0.03}},
        legs("height - 0.03", 0.05, 0.05, "body"),
        {"id": "chair_front", "material": "body", "repeat": {"count": "chairs"}, "box": {"x": "width * (i + 0.5) / chairs - 0.22", "y": -0.35, "dx": 0.44, "dy": 0.44, "dz": 0.45}},
        {"id": "back_front", "material": "body", "repeat": {"count": "chairs"}, "box": {"x": "width * (i + 0.5) / chairs - 0.22", "y": -0.37, "z": 0.45, "dx": 0.44, "dy": 0.03, "dz": 0.45}},
        {"id": "chair_back", "material": "body", "repeat": {"count": "chairs"}, "box": {"x": "width * (i + 0.5) / chairs - 0.22", "y": "depth - 0.09", "dx": 0.44, "dy": 0.44, "dz": 0.45}},
        {"id": "back_back", "material": "body", "repeat": {"count": "chairs"}, "box": {"x": "width * (i + 0.5) / chairs - 0.22", "y": "depth + 0.32", "z": 0.45, "dx": 0.44, "dy": 0.03, "dz": 0.45}}],
        RECT + [{"repeat": {"count": "chairs"}, "rect": {"x": "width * (i + 0.5) / chairs - 0.22", "y": -0.37, "dx": 0.44, "dy": 0.46}},
                {"repeat": {"count": "chairs"}, "rect": {"x": "width * (i + 0.5) / chairs - 0.22", "y": "depth - 0.09", "dx": 0.44, "dy": 0.46}}],
        BODY("Timber - finish")),
    obj("armchair", "Armchair", "Sillón", "furniture", furn("CHAIR", "Armchair"), WDH(0.85, 0.85, 0.8), [
        {"id": "seat", "material": "body", "rounded_box": {"x": 0.15, "dx": "width - 0.3", "dy": "depth - 0.2", "dz": 0.42, "r": 0.04}},
        {"id": "arm", "material": "body", "repeat": {"count": 2}, "rounded_box": {"x": "if(i == 0, 0, width - 0.15)", "dx": 0.15, "dy": "depth", "dz": "height * 0.72", "r": 0.05}},
        {"id": "back", "material": "body", "rounded_box": {"x": 0.15, "y": "depth - 0.2", "dx": "width - 0.3", "dy": 0.2, "dz": "height", "r": 0.05}}],
        [{"line": {"points": [{"rounded_rect": [0, 0, "width", "depth", 0.05], "n": 3}], "closed": True}},
         {"line": {"points": [[0.15, 0], [0.15, "depth"]]}}, {"line": {"points": [["width - 0.15", 0], ["width - 0.15", "depth"]]}},
         {"line": {"points": [[0.15, "depth - 0.2"], ["width - 0.15", "depth - 0.2"]]}}], BODY("Fabric")),
    obj("coffee_table", "Coffee table", "Mesa ratona", "furniture", furn("TABLE"), WDH(1.1, 0.6, 0.4), [
        {"id": "top", "material": "body", "rounded_box": {"z": "height - 0.03", "dx": "width", "dy": "depth", "dz": 0.03, "r": 0.05}},
        legs("height - 0.03", 0.05, 0.035, "body")], materials=BODY("Timber - finish")),
    # ---------------------------------------------------------------- industrial (winery, production)
    obj("steel_tank", "Stainless steel tank", "Tanque de acero inoxidable", "industrial",
        {"IFC4": ["IfcTankType", "VESSEL", None], "IFC2X3": ["IfcTankType", "VESSEL", None]},
        [P("width", "Diameter", "Diámetro", 1.8), P("height", "Height", "Altura", 3.2),
         P("legs_height", "Leg height", "Altura de patas", 0.5)], [
        {"id": "leg", "material": "body", "repeat": {"count": 4}, "cylinder": {"cx": "width / 2 + width * 0.38 * cos(90 * i + 45)", "cy": "width / 2 + width * 0.38 * sin(90 * i + 45)", "r": 0.04, "h": "legs_height + 0.1"}},
        {"id": "bottom", "material": "body", "cone": {"cx": "width / 2", "cy": "width / 2", "z": "legs_height", "r1": "width * 0.12", "r2": "width / 2", "h": "width * 0.15"}},
        {"id": "shell", "material": "body", "cylinder": {"cx": "width / 2", "cy": "width / 2", "z": "legs_height + width * 0.15", "r": "width / 2", "h": "height - legs_height - width * 0.3"}},
        {"id": "top", "material": "body", "cone": {"cx": "width / 2", "cy": "width / 2", "z": "height - width * 0.15", "r1": "width / 2", "r2": "width * 0.15", "h": "width * 0.15"}}],
        [{"circle": {"cx": "width / 2", "cy": "width / 2", "r": "width / 2"}},
         {"circle": {"cx": "width / 2", "cy": "width / 2", "r": "width * 0.15"}}], BODY("Steel")),
    obj("barrel_rack", "Barrel rack", "Estiba de barricas", "industrial", user("IfcFurnitureType", "BARRELRACK"),
        [P("width", "Length", "Largo", 3.0), P("height", "Height", "Altura", 1.44), P("depth", "Depth", "Fondo", 0.95)], [
        {"id": "barrel", "material": "body", "repeat": {"count": "max(1, floor(width / 0.75)) * max(1, floor(height / 0.72))"},
         "axes": ["x", "z", "-y"], "cylinder": {"cx": "0.36 + 0.75 * (i % max(1, floor(width / 0.75)))", "cy": "0.47 + 0.72 * floor(i / max(1, floor(width / 0.75)))", "z": "-depth", "r": 0.35, "h": "depth"}},
        {"id": "rail", "material": "frame", "repeat": {"count": "2 * max(1, floor(height / 0.72))"}, "box": {"y": "if(i % 2 == 0, 0.15, depth - 0.2)", "z": "0.72 * floor(i / 2)", "dx": "width", "dy": 0.05, "dz": 0.12}}],
        [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
         {"repeat": {"count": "max(1, floor(width / 0.75)) - 1"}, "line": {"points": [["0.75 * (i + 1)", 0], ["0.75 * (i + 1)", "depth"]]}}],
        M(body=(("Barrels", "Barricas"), "Timber"), frame=(("Rack", "Estiba"), "Steel"))),
    obj("pallet", "Pallet with load", "Pallet con carga", "industrial", user("IfcFurnitureType", "PALLET"),
        WDH(1.2, 0.8, 1.2), [
        {"id": "deck", "material": "frame", "box": {"dx": "width", "dy": "depth", "dz": 0.144}},
        {"id": "load", "material": "body", "box": {"x": 0.02, "y": 0.02, "z": 0.144, "dx": "width - 0.04", "dy": "depth - 0.04", "dz": "height - 0.144"}}],
        RECT + [{"line": {"points": [[0, 0], ["width", "depth"]]}}, {"line": {"points": [["width", 0], [0, "depth"]]}}],
        M(body=(("Load", "Carga"), "Fabric"), frame=(("Pallet", "Pallet"), "Timber"))),
    obj("pallet_racking", "Pallet racking", "Estantería industrial", "industrial", furn("SHELF", "Racking"),
        WDH(2.7, 1.1, 4.5) + [P("beams", "Beam levels", "Niveles de vigas", 3, "count", min=1, max=8)], [
        {"id": "upright", "material": "body", "repeat": {"count": 4}, "box": {"x": "if(i % 2 == 0, 0, width - 0.09)", "y": "if(i < 2, 0, depth - 0.09)", "dx": 0.09, "dy": 0.09, "dz": "height"}},
        {"id": "beam", "material": "body", "repeat": {"count": "2 * beams"}, "box": {"y": "if(i % 2 == 0, 0, depth - 0.05)", "z": "height * (floor(i / 2) + 1) / (beams + 1)", "dx": "width", "dy": 0.05, "dz": 0.12}}],
        RECT + [{"line": {"points": [[0, 0], ["width", "depth"]]}}], BODY("Steel")),
    obj("forklift", "Forklift", "Autoelevador", "industrial", user("IfcBuildingElementProxyType", "FORKLIFT"),
        WDH(1.2, 3.2, 2.2), [
        {"id": "body", "material": "body", "rounded_box": {"y": 1.1, "z": 0.25, "dx": "width", "dy": "depth - 1.1", "dz": 0.9, "r": 0.15}},
        {"id": "wheel", "material": "frame", "repeat": {"count": 4}, "axes": ["y", "z", "x"], "cylinder": {"cx": "if(i < 2, 1.35, depth - 0.4)", "cy": 0.28, "z": "if(i % 2 == 0, 0.0, width - 0.22)", "r": 0.28, "h": 0.22}},
        {"id": "mast", "material": "frame", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0.15, width - 0.25)", "y": 1.0, "dx": 0.1, "dy": 0.1, "dz": "height"}},
        {"id": "fork", "material": "frame", "repeat": {"count": 2}, "box": {"x": "if(i == 0, 0.25, width - 0.35)", "y": 0, "z": 0.05, "dx": 0.1, "dy": 1.0, "dz": 0.05}},
        {"id": "roof", "material": "frame", "box": {"y": 1.4, "z": "height - 0.08", "dx": "width", "dy": 1.1, "dz": 0.08}}],
        RECT + [{"line": {"points": [[0, 1.1], ["width", 1.1]]}}], M(body=(("Body", "Cuerpo"), "Paint - white"), frame=(("Frame", "Estructura"), "Steel"))),
    obj("wine_press", "Wine press", "Prensa neumática", "industrial", user("IfcBuildingElementProxyType", "PRESS"),
        WDH(1.6, 3.2, 2.0), [
        {"id": "frame", "material": "body", "repeat": {"count": 2}, "box": {"y": "if(i == 0, 0.1, depth - 0.3)", "dx": "width", "dy": 0.2, "dz": "height * 0.7"}},
        {"id": "drum", "material": "body", "axes": ["z", "x", "y"], "cylinder": {"cx": "height * 0.62", "cy": "width / 2", "z": 0.3, "r": "width * 0.45", "h": "depth - 0.6"}},
        {"id": "tray", "material": "body", "box": {"x": 0.1, "y": 0.3, "z": 0.3, "dx": "width - 0.2", "dy": "depth - 0.6", "dz": 0.15}}],
        RECT + [{"line": {"points": [[0, 0.3], ["width", 0.3]]}}, {"line": {"points": [[0, "depth - 0.3"], ["width", "depth - 0.3"]]}}],
        BODY("Steel")),
    # ---------------------------------------------------------------- site
    obj("bicycle", "Bicycle", "Bicicleta", "site", user("IfcBuildingElementProxyType", "BICYCLE"),
        WDH(0.6, 1.8, 1.0), [
        {"id": "wheel", "material": "body", "repeat": {"count": 2}, "axes": ["y", "z", "x"], "cylinder": {"cx": "if(i == 0, 0.35, depth - 0.35)", "cy": 0.35, "z": "width / 2 - 0.02", "r": 0.35, "h": 0.04}},
        {"id": "frame", "material": "body", "sweep": {"path": [["width / 2", 0.35, 0.35], ["width / 2", "depth / 2", 0.8], ["width / 2", "depth - 0.35", 0.35]], "r": 0.02}},
        {"id": "bar", "material": "body", "box": {"x": 0.05, "y": "depth - 0.45", "z": "height - 0.03", "dx": "width - 0.1", "dy": 0.03, "dz": 0.03}}],
        [{"line": {"points": [["width / 2", 0], ["width / 2", "depth"]]}}, {"line": {"points": [[0.05, "depth - 0.45"], ["width - 0.05", "depth - 0.45"]]}}],
        BODY("Steel")),
    obj("planter", "Planter", "Cantero", "site", user("IfcFurnitureType", "PLANTER"), WDH(1.2, 0.5, 0.5), [
        {"id": "box", "material": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}},
        {"id": "plants", "material": "plants", "ellipsoid": {"cx": "width / 2", "cy": "depth / 2", "cz": "height", "r": "min(width, depth) / 2", "rz": 0.3}}],
        RECT + [{"circle": {"cx": "width / 2", "cy": "depth / 2", "r": "min(width, depth) / 2"}}],
        M(body=(("Planter", "Cantero"), "Concrete"), plants=(("Plants", "Plantas"), "Generic"))),
    obj("street_light", "Street light", "Columna de alumbrado", "site", {"IFC4": ["IfcLightFixtureType", "USERDEFINED", "STREETLIGHT"], "IFC2X3": ["IfcLightFixtureType", None, "Street light"]},
        [P("height", "Height", "Altura", 4.0), P("width", "Head size", "Tamaño de luminaria", 0.5)], [
        {"id": "pole", "material": "body", "cylinder": {"cx": 0, "cy": 0, "r": 0.06, "h": "height"}},
        {"id": "head", "material": "body", "ellipsoid": {"cx": 0, "cy": 0, "cz": "height + 0.1", "r": "width / 2", "rz": 0.12}}],
        [{"circle": {"cx": 0, "cy": 0, "r": 0.06}}, {"circle": {"cx": 0, "cy": 0, "r": "width / 2"}}], BODY("Steel")),
    obj("palm_tree", "Palm tree", "Palmera", "site", user("IfcGeographicElementType", "PALM"),
        [P("width", "Crown diameter", "Diámetro de copa", 3.5), P("height", "Height", "Altura", 7.0)], [
        {"id": "trunk", "material": "trunk", "cone": {"cx": "width / 2", "cy": "width / 2", "r1": 0.25, "r2": 0.18, "h": "height - 0.5"}},
        {"id": "crown", "material": "leaves", "ellipsoid": {"cx": "width / 2", "cy": "width / 2", "cz": "height - 0.4", "r": "width / 2", "rz": 0.9}}],
        [{"circle": {"cx": "width / 2", "cy": "width / 2", "r": "width / 2"}},
         {"repeat": {"count": 10}, "line": {"points": [["width / 2", "width / 2"], ["width / 2 + width / 2 * cos(36 * i)", "width / 2 + width / 2 * sin(36 * i)"]]}}],
        M(trunk=(("Trunk", "Tronco"), "Timber"), leaves=(("Leaves", "Hojas"), "Generic"))),
]


def write(d):
    lines = ["{"]
    keys = list(d)
    for i, k in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        v = d[k]
        if isinstance(v, list) and k in ("params", "parts", "symbol"):
            lines.append(f' "{k}": [')
            lines += ["  " + json.dumps(item, ensure_ascii=False) + ("," if j < len(v) - 1 else "") for j, item in enumerate(v)]
            lines.append(" ]" + comma)
        else:
            lines.append(f' "{k}": ' + json.dumps(v, ensure_ascii=False) + comma)
    lines.append("}")
    (OUT / f"{d['id']}.nicobj").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    for d in OBJECTS:
        write(d)
    print(f"wrote {len(OBJECTS)} objects")
