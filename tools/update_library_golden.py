# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite tests/golden/library_objects.json from the bundled objects (D256).

The golden began as the proof of the D99 port (each .nicobj built what the Python object it replaced built);
since the library is designed as data now, it is a regression record: every bundled object's bounding box,
volume and plan-symbol extent at its defaults and at the value sets already recorded for it. Run it after a
deliberate change to a bundled object and review the diff.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from kimbim import objects  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "library_objects.json"
BUNDLED = ROOT / "python" / "kimbim" / "bundled_objects"


def main() -> int:
    old = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    out = {}
    for path in sorted(BUNDLED.glob("*.nicobj")):
        d = objects.load_file(str(path), "bundled")
        sets = {name: case["values"] for name, case in (old.get(d.key) or {}).items()} or {"default": {}}
        out[d.key] = {}
        for name, given in sets.items():
            m = d.shape(d.values(given)).metrics()
            out[d.key][name] = {"values": given, "bbox": [round(v, 6) for v in m["bbox"]],
                                "volume": round(m["volume"], 9), "symbol_bbox": [round(v, 6) for v in m["symbol_bbox"]],
                                "symbol_length": round(m["symbol_length"], 6)}
    GOLDEN.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(out)} objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
