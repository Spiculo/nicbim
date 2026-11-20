# SPDX-License-Identifier: GPL-3.0-or-later
"""Walkthrough tools (D249): camera paths saved with the project and rendered into a video. Cameras are given in
project units (or strings with units) and listed in metres; rendering uses the same windowless renderer as
snapshot.take, one frame per camera, then ffmpeg joins the frames."""
from __future__ import annotations

import pathlib
import shutil
import tempfile

from ... import app_bridge as B
from ... import walkthrough as W
from ..catalogue import AgentError, bridge, tool
from .common import lengths
from .snapshot import _check_purpose, _out_path, _renderer

_POINT = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": ["number", "string"]}}
_CAMERAS = {"type": "array", "minItems": 2, "items": {
    "type": "object", "required": ["eye", "target"], "additionalProperties": False, "properties": {
        "eye": _POINT, "target": _POINT,
        "fov": {"type": "number", "minimum": 1, "maximum": 170, "description": "Degrees (default 60)."}}},
    "description": "The cameras in order: where the eye is and what it looks at (project units)."}
_NAME = {"type": "string", "description": "The walkthrough's name (walkthrough.list lists them)."}


def _cameras(session, cameras) -> list[dict]:
    out = []
    for cam in cameras or ():
        eye, target = (lengths(session, *cam.get(k) or ()) for k in ("eye", "target"))
        if len(eye) != 3 or len(target) != 3:
            raise AgentError("bad_input", hint="a camera's eye and target are [x, y, z]")
        out.append({"eye": eye, "target": target, **({"fov": float(cam["fov"])} if "fov" in cam else {})})
    return out


@tool("walkthrough.list", {})
def walkthrough_list(session):
    """List the project's walkthroughs (camera paths for a video): cameras in metres, duration, frame rate, size
    and frame count."""
    return {"walkthroughs": bridge(W.walkthroughs)["walkthroughs"], "unit": "m"}


@tool("walkthrough.save", {"required": ["name", "cameras"], "properties": {
    "name": _NAME, "cameras": _CAMERAS,
    "seconds": {"type": "number", "minimum": 0.1, "maximum": 3600, "description": "Duration (default 10)."},
    "fps": {"type": "integer", "minimum": 1, "maximum": 120, "description": "Frames a second (default 25)."},
    "smooth": {"type": "boolean", "description": "A curve through every camera (default) or straight lines."},
    "closed": {"type": "boolean", "description": "Come back to the first camera (default false)."},
    "size": {"type": "array", "items": {"type": "integer"}, "description": "[w, h] even pixels (default "
                                                                           "[1280, 720])."}}}, writes=True)
def walkthrough_save(session, name, cameras, seconds=None, fps=None, smooth=None, closed=None, size=None):
    """Add or replace a walkthrough: the camera moves along the cameras at an even speed for the duration. It is
    saved with the project; walkthrough.render makes the video."""
    data = {"cameras": _cameras(session, cameras)}
    for key, value in (("seconds", seconds), ("fps", fps), ("smooth", smooth), ("closed", closed), ("size", size)):
        if value is not None:
            data[key] = value
    r = bridge(W.save_walkthrough, name, data)
    return {k: r[k] for k in ("name", "seconds", "fps", "smooth", "closed", "size", "frames")}


@tool("walkthrough.delete", {"required": ["name"], "properties": {"name": _NAME}}, writes=True)
def walkthrough_delete(session, name):
    """Delete a saved walkthrough."""
    bridge(W.delete_walkthrough, name)
    return {"deleted": name}


@tool("walkthrough.render", {"required": ["name"], "properties": {
    "name": _NAME,
    "out": {"type": "string", "description": "The video file (.mp4, .mov or .webm); default a new .mp4 in the "
                                             "NicBim data folder."},
    "style": {"type": "string", "enum": ["shaded", "white", "lines", "textured", "render"],
              "description": "Default shaded; render is ray traced (slow for long videos)."},
    "purpose": {"type": "string", "description": "The purpose (pen set, visibility); default the project's."},
    "keep_frames": {"type": "boolean", "description": "Keep the PNG frames next to the video (default false)."}}})
def walkthrough_render(session, name, out="", style="", purpose="", keep_frames=False):
    """Render a saved walkthrough into a video: one picture per frame with the windowless renderer, joined by
    ffmpeg. Returns the video's path and frame count. It changes nothing in the model."""
    if B._model is None:
        raise AgentError("no_model")
    _check_purpose(purpose)
    try:
        full, frames = W.frames_for(name)
    except ValueError as ex:
        raise AgentError("bad_input", hint=str(ex)) from None
    out = out or _out_path("", "mp4")
    try:
        W.codec_args(out)
    except ValueError as ex:
        raise AgentError("bad_input", hint=str(ex)) from None
    if W.find_ffmpeg() is None:
        raise AgentError("bridge_error", hint=f"ffmpeg was not found: install it or set {W.ENV_FFMPEG}")
    folder = pathlib.Path(out).parent / (pathlib.Path(out).stem + "-frames") if keep_frames \
        else pathlib.Path(tempfile.mkdtemp(prefix="kimbim-walk-"))
    folder.mkdir(parents=True, exist_ok=True)
    renderer = _renderer(session)
    try:
        for index, cam in enumerate(frames):
            req = {"out": str(folder / (W.FRAME_PATTERN % index)), "size": full["size"],
                   "camera": {"eye": cam["eye"], "target": cam["target"], "up": cam["up"], "fov": cam["fov"]}}
            for key, value in (("style", style), ("purpose", purpose)):
                if value:
                    req[key] = value
            renderer.render3d(session, **req)
        r = bridge(W.encode_walkthrough_video, str(folder), full["fps"], out)
    finally:
        if not keep_frames:
            shutil.rmtree(folder, ignore_errors=True)
    result = {"path": r["path"], "frames": len(frames), "fps": full["fps"], "size": full["size"]}
    if keep_frames:
        result["frames_folder"] = str(folder)
    return result
