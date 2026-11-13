# SPDX-License-Identifier: GPL-3.0-or-later
"""Walkthroughs (D249, Archicad's Fly-through): a camera path through the model, made into a video.

A walkthrough is an ordered list of cameras (eye, target and an optional field of view, in metres
in the model's coordinates) with a duration and a frame rate, saved by name in the `walkthroughs`
project setting. `path_frames` turns it into one camera per frame: the eye moves along the path at
an even speed (straight lines, or a curve through every camera when `smooth`), the target and field
of view follow, and a closed path comes back to its first camera. The app (or the agent's renderer)
draws each frame and `encode_video` joins the PNGs into an MP4/MOV (H.264) or WebM (VP9) with
ffmpeg, found like the DWG converters: `KIMBIM_FFMPEG`, PATH, then the pixi environment.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import pathlib
import shutil
import subprocess

DEFAULT_FOV = 60.0
DEFAULTS = {"seconds": 10.0, "fps": 25, "smooth": True, "closed": False, "size": [1280, 720]}
MAX_FRAMES = 18000  # ten minutes at 30 fps
ENV_FFMPEG = "KIMBIM_FFMPEG"
FRAME_PATTERN = "frame-%05d.png"
UP = [0.0, 0.0, 1.0]


# ------------------------------------------------------------------ the path

def _xyz(value, what: str) -> list[float]:
    if not (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        raise ValueError(f"a camera's {what} is [x, y, z] in metres")
    return [float(v) for v in value]


def _cameras(cameras) -> list[dict]:
    if not isinstance(cameras, list) or len(cameras) < 2:
        raise ValueError("a walkthrough needs at least two cameras")
    out = []
    for index, cam in enumerate(cameras, start=1):
        if not isinstance(cam, dict):
            raise ValueError(f"camera {index} is a table {{eye, target, fov}}")
        eye, target = _xyz(cam.get("eye"), "eye"), _xyz(cam.get("target"), "target")
        if math.dist(eye, target) < 1e-6:
            raise ValueError(f"camera {index} looks at its own eye")
        fov = cam.get("fov", DEFAULT_FOV)
        if not (isinstance(fov, (int, float)) and not isinstance(fov, bool) and 1 <= fov <= 170):
            raise ValueError(f"camera {index}'s field of view is 1 to 170 degrees")
        out.append({"eye": eye, "target": target, "fov": float(fov)})
    return out


def _count(seconds, fps, closed: bool) -> int:
    if not (isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and 0.1 <= seconds <= 3600):
        raise ValueError("the duration is 0.1 to 3600 seconds")
    if not (isinstance(fps, int) and not isinstance(fps, bool) and 1 <= fps <= 120):
        raise ValueError("the frame rate is 1 to 120 frames a second (a whole number)")
    n = max(2, round(seconds * fps)) + (0 if closed else 1)
    if n > MAX_FRAMES:
        raise ValueError(f"too many frames (limit {MAX_FRAMES}): shorten it or lower the frame rate")
    return n


def _hermite(p0, p1, p2, p3, u: float) -> list[float]:
    """Uniform Catmull-Rom between p1 and p2 (it passes through every point)."""
    u2, u3 = u * u, u * u * u
    return [0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3)
            for a, b, c, d in zip(p0, p1, p2, p3)]


def _segment_points(points: list, closed: bool) -> list[tuple]:
    """(p0, p1, p2, p3) for each segment, ends mirrored on an open path."""
    n = len(points)
    if closed:
        return [(points[(i - 1) % n], points[i], points[(i + 1) % n], points[(i + 2) % n]) for i in range(n)]
    ext = ([[2 * a - b for a, b in zip(points[0], points[1])]] + points
           + [[2 * a - b for a, b in zip(points[-1], points[-2])]])
    return [tuple(ext[i:i + 4]) for i in range(n - 1)]


def _evaluate(segments, index: int, u: float, smooth: bool) -> list[float]:
    p0, p1, p2, p3 = segments[index]
    if smooth:
        return _hermite(p0, p1, p2, p3, u)
    return [a + (b - a) * u for a, b in zip(p1, p2)]


def path_frames(cameras, seconds=DEFAULTS["seconds"], fps=DEFAULTS["fps"], smooth: bool = True,
                closed: bool = False) -> list[dict]:
    """One camera {eye, target, up, fov} per frame along the walkthrough, the eye at an even speed."""
    cams = _cameras(cameras)
    n = _count(seconds, fps, bool(closed))
    eyes = _segment_points([c["eye"] for c in cams], closed)
    targets = _segment_points([c["target"] for c in cams], closed)
    fovs = [c["fov"] for c in cams]
    count = len(eyes)
    samples = 64
    # arc-length table over the eye path: (cumulative length, segment, u)
    table = [(0.0, 0, 0.0)]
    total = 0.0
    previous = _evaluate(eyes, 0, 0.0, smooth)
    for seg in range(count):
        for k in range(1, samples + 1):
            u = k / samples
            point = _evaluate(eyes, seg, u, smooth)
            total += math.dist(previous, point)
            table.append((total, seg, u))
            previous = point
    still = total < 1e-6  # turning on the spot: spread the frames evenly over the cameras
    span = n if closed else n - 1
    lengths = [row[0] for row in table]
    out = []
    for i in range(n):
        t = i / span
        if still:
            position = t * count
            seg = min(int(position), count - 1)
            u = position - seg
        else:
            s = t * total
            k = min(max(1, bisect.bisect_left(lengths, s)), len(table) - 1)
            (s0, seg0, u0), (s1, seg, u1) = table[k - 1], table[k]
            if seg0 != seg:
                u0 = 0.0  # the end of the previous segment is this one's start
            f = 0.0 if s1 - s0 < 1e-12 else min(1.0, max(0.0, (s - s0) / (s1 - s0)))
            u = u0 + (u1 - u0) * f
        eye = _evaluate(eyes, seg, u, smooth)
        target = _evaluate(targets, seg, u, smooth)
        if math.dist(eye, target) < 1e-6:  # a curve overshoot put the target on the eye
            target = _evaluate(targets, seg, u, False)
        fov = fovs[seg] + (fovs[(seg + 1) % len(fovs)] - fovs[seg]) * u
        out.append({"eye": [round(v, 9) for v in eye], "target": [round(v, 9) for v in target],
                    "up": list(UP), "fov": round(fov, 6)})
    return out


# ------------------------------------------------------------------ stored walkthroughs

def normalise(data) -> dict:
    """A walkthrough with its defaults filled in; raises ValueError when it is not valid."""
    if not isinstance(data, dict):
        raise ValueError("a walkthrough is a table {cameras, seconds, fps, smooth, closed, size}")
    unknown = set(data) - {"cameras", *DEFAULTS}
    if unknown:
        raise ValueError(f"unknown walkthrough field {sorted(unknown)[0]!r}")
    out = {**DEFAULTS, **data}
    out["cameras"] = _cameras(data.get("cameras"))
    out["smooth"], out["closed"] = bool(out["smooth"]), bool(out["closed"])
    if isinstance(out["seconds"], int) and not isinstance(out["seconds"], bool):
        out["seconds"] = float(out["seconds"])
    _count(out["seconds"], out["fps"], out["closed"])
    error = video_error(out)
    if error:
        raise ValueError(error)
    out["size"] = [int(v) for v in out["size"]]
    return out


def video_error(data: dict) -> str | None:
    size = data.get("size", DEFAULTS["size"])
    if not (isinstance(size, (list, tuple)) and len(size) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) and 128 <= v <= 7680 for v in size)):
        return "the video size is [width, height], 128 to 7680 pixels"
    if any(v % 2 for v in size):
        return "the video's width and height must be even numbers"
    return None


def settings_error(value) -> str | None:
    """Why a `walkthroughs` project setting is not valid, or None."""
    if not isinstance(value, dict):
        return "the walkthroughs are a table by name"
    for name, data in value.items():
        if not isinstance(name, str) or not name.strip():
            return "a walkthrough needs a name"
        try:
            normalise(data)
        except ValueError as ex:
            return f"walkthrough {name!r}: {ex}"
    return None


def _stored() -> dict:
    from . import settings as S

    data = S.current().get("walkthroughs", {})
    return data if isinstance(data, dict) else {}


def _fail(error: str, **extra) -> str:
    from . import app_bridge as B

    return B._dump({"ok": False, "error": error, **extra})


def _summary(name: str, data: dict) -> dict:
    full = normalise(data)
    return {"name": name, **full, "frames": _count(full["seconds"], full["fps"], full["closed"])}


def walkthroughs() -> str:
    """The saved walkthroughs in name order, with their frame counts."""
    from . import app_bridge as B

    out = []
    for name, data in sorted(_stored().items(), key=lambda kv: kv[0].lower()):
        try:
            out.append(_summary(name, data))
        except ValueError:
            continue  # validated on save; a hand-edited file's bad entry is skipped
    return B._dump({"ok": True, "walkthroughs": out})


def _store(table: dict) -> dict:
    from . import app_bridge as B
    from . import settings as S

    def action():
        S.set_project_settings(json.dumps({"walkthroughs": table}))
        return 0, [], []

    return B._run_settings(action)


def save_walkthrough(name: str, data_json) -> str:
    """Add or replace a walkthrough: {cameras: [{eye, target, fov?}], seconds?, fps?, smooth?, closed?, size?}."""
    from . import app_bridge as B

    name = str(name or "").strip()
    if not name:
        return _fail("type a walkthrough name")
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        full = normalise(data)
    except ValueError as ex:
        return _fail(str(ex))
    if B._model is None:
        return _fail("no model open")
    try:
        result = _store({**_stored(), name: full})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, **_summary(name, full)})


def delete_walkthrough(name: str) -> str:
    from . import app_bridge as B

    table = dict(_stored())
    if name not in table:
        return _fail("walkthrough not found")
    table.pop(name)
    try:
        result = _store(table)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "name": name})


def frames_for(name_or_data) -> tuple[dict, list[dict]]:
    """(the walkthrough, its frames) for a saved name or a walkthrough table."""
    if isinstance(name_or_data, str):
        data = _stored().get(name_or_data)
        if data is None:
            stripped = name_or_data.strip()
            if stripped.startswith("{"):
                data = json.loads(stripped)
            else:
                raise ValueError("walkthrough not found")
    else:
        data = name_or_data
    full = normalise(data)
    return full, path_frames(full["cameras"], full["seconds"], full["fps"], full["smooth"], full["closed"])


def walkthrough_frames(name_or_json: str) -> str:
    """The cameras of every frame of a saved walkthrough (or of a walkthrough given as JSON)."""
    from . import app_bridge as B

    try:
        full, frames = frames_for(name_or_json)
    except ValueError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, "fps": full["fps"], "size": full["size"], "frames": frames})


# ------------------------------------------------------------------ video

def _pixi_bin() -> list[pathlib.Path]:
    here = pathlib.Path(__file__).resolve()
    out = []
    for parent in here.parents:
        for env in ("default", "video"):
            out += [parent / ".pixi" / "envs" / env / "Library" / "bin", parent / ".pixi" / "envs" / env / "bin"]
    return out


def find_ffmpeg() -> str | None:
    """ffmpeg: `KIMBIM_FFMPEG` (the program), PATH, then a pixi environment."""
    exact = os.environ.get(ENV_FFMPEG, "")
    if exact and pathlib.Path(exact).is_file():
        return exact
    found = shutil.which("ffmpeg")
    if found:
        return found
    for folder in _pixi_bin():
        for name in ("ffmpeg.exe", "ffmpeg"):
            if (folder / name).is_file():
                return str(folder / name)
    return None


def codec_args(out: str) -> list[str]:
    suffix = pathlib.Path(out).suffix.lower()
    if suffix in (".mp4", ".mov", ".m4v"):
        return ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart"]
    if suffix == ".webm":
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", "32", "-b:v", "0"]
    raise ValueError("the video is .mp4, .mov or .webm")


def encode_video(folder: str, fps: int, out: str, timeout: float = 3600) -> str:
    """Join `folder`/frame-00000.png... into a video at `fps`; returns the video's path."""
    try:
        args = codec_args(out)
    except ValueError:
        raise
    frames = sorted(pathlib.Path(folder).glob("frame-*.png"))
    if not frames:
        raise ValueError("there are no frames to join")
    exe = find_ffmpeg()
    if exe is None:
        raise RuntimeError(f"ffmpeg was not found: install it or set {ENV_FFMPEG} to the program; "
                           f"the frames are kept in {folder}")
    first = frames[0].stem.split("-")[-1]
    cmd = [exe, "-y", "-loglevel", "error", "-framerate", str(int(fps)), "-start_number", str(int(first)),
           "-i", str(pathlib.Path(folder) / FRAME_PATTERN), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           *args, str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or not pathlib.Path(out).is_file():
        raise RuntimeError(f"ffmpeg failed: {(done.stderr or '').strip()[-500:] or done.returncode}")
    return str(out)


def encode_walkthrough_video(folder: str, fps, out: str) -> str:
    """The bridge's encode: {ok, path} or {ok: false, error, frames_kept}."""
    from . import app_bridge as B

    try:
        path = encode_video(str(folder), int(fps), str(out))
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as ex:
        return _fail(str(ex), frames_kept=True)
    return B._dump({"ok": True, "path": path})


def ffmpeg_state() -> str:
    from . import app_bridge as B

    exe = find_ffmpeg()
    return B._dump({"ok": True, "found": exe is not None, "path": exe or ""})
