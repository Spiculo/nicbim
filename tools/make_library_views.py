# SPDX-License-Identifier: GPL-3.0-or-later
"""D255: hand-drawn front views for entourage and large equipment, and their low-poly 3D bodies.

Sections and elevations draw an object with `views` from its 2D view (like Archicad's 2D symbols), so the 3D
body can stay low-poly for the viewer: a tree crown is a few 12-sided prisms in 3D and a soft outline on paper.
Run after tools/make_library_wave1.py; it edits the named bundled objects in place.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "python" / "kimbim" / "bundled_objects"


def blob(cx, cz, rx, rz, n=36, wobble=0.05, lobes=7):
    """A soft closed outline (a tree crown seen from the side) as one repeated line item: 36 segments of an
    ellipse whose radius wobbles by `wobble` with `lobes` bumps."""
    def pt(a):
        k = f"(1 + {wobble} * sin({lobes} * ({a})))"
        return [f"{cx} + {rx} * {k} * cos({a})", f"{cz} + {rz} * {k} * sin({a})"]
    step = 360 / n
    return {"repeat": {"count": n}, "line": {"points": [pt(f"{step} * i"), pt(f"{step} * (i + 1)")]}}


def crown_prisms(cx, cy, z0, h, r, n=12):
    """A low-poly crown: three stacked 12-sided prisms (wide, widest, narrow)."""
    rings = ((0.0, 0.3, 0.8), (0.3, 0.4, 1.0), (0.7, 0.3, 0.7))
    return [{"id": f"crown{k + 1}", "material": "leaves",
             "prism": {"points": [{"ellipse": [cx, cy, f"{r} * {s}", f"{r} * {s}"], "n": n}],
                       "z": f"{z0} + {h} * {a}", "h": f"{h} * {b}"}} for k, (a, b, s) in enumerate(rings)]


def edit(name, fn):
    p = OUT / f"{name}.nicobj"
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    lines = ["{"]
    keys = list(d)
    for i, k in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        v = d[k]
        if isinstance(v, list) and k in ("params", "parts", "symbol"):
            lines.append(f' "{k}": [')
            lines += ["  " + json.dumps(it, ensure_ascii=False) + ("," if j < len(v) - 1 else "") for j, it in enumerate(v)]
            lines.append(" ]" + comma)
        else:
            lines.append(f' "{k}": ' + json.dumps(v, ensure_ascii=False) + comma)
    lines.append("}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def materials(d, **slots):
    d.setdefault("materials", {})
    for k, (en, es, default) in slots.items():
        d["materials"][k] = {"label": {"en": en, "es": es}, "default": default}
    # keep "views" last, after the symbol (doc 16 order)
    if "views" in d:
        d["views"] = d.pop("views")


def tree(d):
    d["parts"] = [{"id": "trunk_post", "material": "trunk",
                   "cylinder": {"cx": "width / 2", "cy": "width / 2", "r": "trunk / 2", "h": "height * 0.35"}},
                  *crown_prisms("width / 2", "width / 2", "height * 0.3", "height * 0.7", "width / 2")]
    d["views"] = {"front": [
        {"line": {"points": [["width / 2 - trunk / 2", 0], ["width / 2 - trunk / 2", "height * 0.3"]]}},
        {"line": {"points": [["width / 2 + trunk / 2", 0], ["width / 2 + trunk / 2", "height * 0.3"]]}},
        blob("width / 2", "height * 0.62", "width / 2", "height * 0.36"),
        {"line": {"points": [["width / 2", "height * 0.3"], ["width / 2 - width * 0.2", "height * 0.55"]]}},
        {"line": {"points": [["width / 2", "height * 0.35"], ["width / 2 + width * 0.18", "height * 0.6"]]}},
        {"line": {"points": [["width / 2", "height * 0.3"], ["width / 2", "height * 0.7"]]}}]}
    materials(d, trunk=("Trunk", "Tronco", "Timber"), leaves=("Leaves", "Hojas", "Generic"))


def shrub(d):
    d["parts"] = [{"id": "body", "material": "leaves",
                   "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2", "width / 2"], "n": 12}],
                             "z": "height * 0.1", "h": "height * 0.9"}}]
    d["views"] = {"front": [blob("width / 2", "height / 2", "width / 2", "height / 2", 30, 0.07, 6)]}
    materials(d, leaves=("Leaves", "Hojas", "Generic"))


def person(d):
    d["parts"] = [p for p in d["parts"] if p["id"] != "head"] + [
        {"id": "head", "cylinder": {"cx": "width / 2", "cy": "depth / 2", "z": "height * 0.85", "r": "height * 0.065",
                                    "h": "height * 0.15"}}]
    w, h = "width", "height"
    d["views"] = {"front": [
        {"ellipse": {"cx": f"{w} / 2", "cy": f"{h} * 0.925", "rx": f"{h} * 0.06", "ry": f"{h} * 0.075"}},
        {"line": {"points": [[f"{w} * 0.38", f"{h} * 0.85"], [f"{w} * 0.12", f"{h} * 0.82"], [f"{w} * 0.08", f"{h} * 0.5"]]}},
        {"line": {"points": [[f"{w} * 0.62", f"{h} * 0.85"], [f"{w} * 0.88", f"{h} * 0.82"], [f"{w} * 0.92", f"{h} * 0.5"]]}},
        {"line": {"points": [[f"{w} * 0.22", f"{h} * 0.8"], [f"{w} * 0.26", f"{h} * 0.47"], [f"{w} * 0.3", 0], [f"{w} * 0.46", 0],
                             [f"{w} / 2", f"{h} * 0.45"], [f"{w} * 0.54", 0], [f"{w} * 0.7", 0], [f"{w} * 0.74", f"{h} * 0.47"],
                             [f"{w} * 0.78", f"{h} * 0.8"]]}}]}


def car(d):
    w, dep, h = "width", "depth", "height"
    d["views"] = {
        # seen from the front (-y): the car's width
        "front": [
            {"line": {"points": [{"rounded_rect": [0, 0.25, w, f"{h} * 0.55 - 0.25", 0.12], "n": 3}], "closed": True}},
            {"line": {"points": [[0.12, f"{h} * 0.55"], [0.3, f"{h}"], [f"{w} - 0.3", f"{h}"], [f"{w} - 0.12", f"{h} * 0.55"]]}},
            {"rect": {"x": 0.05, "y": 0, "dx": 0.22, "dy": 0.32}}, {"rect": {"x": f"{w} - 0.27", "y": 0, "dx": 0.22, "dy": 0.32}}],
        # seen from the side (+x): the car's length, with its wheels
        "side": [
            {"line": {"points": [[0.1, 0.3], [0, 0.45], [0.05, f"{h} * 0.55"], [f"{dep} * 0.3", f"{h} * 0.58"],
                                 [f"{dep} * 0.42", f"{h}"], [f"{dep} * 0.75", f"{h}"], [f"{dep} * 0.87", f"{h} * 0.58"],
                                 [f"{dep} - 0.05", f"{h} * 0.52"], [f"{dep}", 0.45], [f"{dep} - 0.1", 0.3]]}},
            {"circle": {"cx": f"{dep} * 0.18", "cy": 0.32, "r": 0.32}}, {"circle": {"cx": f"{dep} * 0.78", "cy": 0.32, "r": 0.32}},
            {"line": {"points": [[f"{dep} * 0.18 + 0.32", 0.3], [f"{dep} * 0.78 - 0.32", 0.3]]}},
            {"line": {"points": [[f"{dep} * 0.44", f"{h} * 0.95"], [f"{dep} * 0.44", f"{h} * 0.6"]]}},
            {"line": {"points": [[f"{dep} * 0.6", f"{h} * 0.98"], [f"{dep} * 0.6", f"{h} * 0.6"]]}}]}


def palm(d):
    d["parts"] = [{"id": "trunk", "material": "trunk",
                   "prism": {"points": [{"ellipse": ["width / 2", "width / 2", 0.2, 0.2], "n": 8}], "h": "height - 0.5"}},
                  {"id": "crown", "material": "leaves",
                   "box": {"x": "width * 0.1", "y": "width * 0.1", "z": "height - 0.9", "dx": "width * 0.8",
                           "dy": "width * 0.8", "dz": 0.8, "taper": 0.3}}]
    fronds = [{"line": {"points": [["width / 2", "height - 0.2"],
                                   [f"width / 2 + width / 2 * {dx * 0.55}", f"height + {dy * 0.5}"],
                                   [f"width / 2 + width / 2 * {dx}", f"height - 0.2 - {abs(dx) * 1.1}"]]}}
              for dx, dy in ((1.0, 0.3), (-1.0, 0.3), (0.7, 0.6), (-0.7, 0.6), (0.35, 0.9), (-0.35, 0.9))]
    d["views"] = {"front": [
        {"line": {"points": [["width / 2 - 0.2", 0], ["width / 2 - 0.15", "height - 0.3"]]}},
        {"line": {"points": [["width / 2 + 0.2", 0], ["width / 2 + 0.15", "height - 0.3"]]}}, *fronds]}


def steel_tank(d):
    d["parts"] = [p for p in d["parts"] if p["id"] == "leg"] + [
        {"id": "shell", "material": "body",
         "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2", "width / 2"], "n": 16}],
                   "z": "legs_height", "h": "height - legs_height"}}]
    d["views"] = {"front": [
        {"line": {"points": [[0, "legs_height + width * 0.15"], [0, "height - width * 0.15"], ["width * 0.35", "height"],
                             ["width * 0.65", "height"], ["width", "height - width * 0.15"], ["width", "legs_height + width * 0.15"],
                             ["width * 0.62", "legs_height"], ["width * 0.38", "legs_height"]], "closed": True}},
        {"line": {"points": [["width * 0.12", 0], ["width * 0.12", "legs_height + width * 0.08"]]}},
        {"line": {"points": [["width * 0.88", 0], ["width * 0.88", "legs_height + width * 0.08"]]}},
        {"rect": {"x": "width * 0.4", "y": "legs_height + 0.4", "dx": "width * 0.2", "dy": 0.45}},
        {"line": {"points": [[0, "height * 0.45"], ["width", "height * 0.45"]]}},
        {"line": {"points": [[0, "height * 0.75"], ["width", "height * 0.75"]]}}]}


def planter(d):
    d["parts"] = [p for p in d["parts"] if p["id"] != "plants"] + [
        {"id": "plants", "material": "plants",
         "prism": {"points": [{"ellipse": ["width / 2", "depth / 2", "width / 2 * 0.9", "depth / 2 * 0.9"], "n": 12}],
                   "z": "height", "h": 0.35}}]
    d["views"] = {"front": [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "height"}},
                            blob("width / 2", "height + 0.15", "width / 2 * 0.95", 0.25, 24, 0.08, 5)]}


def street_light(d):
    d["parts"] = [p for p in d["parts"] if p["id"] != "head"] + [
        {"id": "head", "material": "body", "cylinder": {"cx": 0, "cy": 0, "z": "height", "r": "width / 2", "h": 0.12}}]


for name, fn in (("tree", tree), ("shrub", shrub), ("person", person), ("car", car), ("palm_tree", palm),
                 ("steel_tank", steel_tank), ("planter", planter), ("street_light", street_light)):
    edit(name, fn)
print("ok")
