# SPDX-License-Identifier: GPL-3.0-or-later
"""D249: walkthrough camera paths and video export."""
import json
import math
import pathlib
import shutil

import pytest

from kimbim import app_bridge as b
from kimbim import walkthrough as W

CAMS = [{"eye": [0, 0, 1.6], "target": [10, 0, 1.6]},
        {"eye": [10, 0, 1.6], "target": [10, 10, 1.6]},
        {"eye": [10, 10, 1.6], "target": [0, 10, 1.6], "fov": 60}]


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_frames_follow_the_path_at_an_even_speed():
    frames = W.path_frames(CAMS, seconds=4, fps=10, smooth=False)
    assert len(frames) == 41
    assert frames[0]["eye"] == pytest.approx([0, 0, 1.6])
    assert frames[-1]["eye"] == pytest.approx([10, 10, 1.6])
    assert frames[20]["eye"] == pytest.approx([10, 0, 1.6])  # half the length: the middle camera
    steps = [math.dist(a["eye"], b_["eye"]) for a, b_ in zip(frames, frames[1:])]
    assert max(steps) == pytest.approx(min(steps), rel=1e-6)  # constant speed
    assert frames[0]["fov"] == pytest.approx(W.DEFAULT_FOV) and frames[-1]["fov"] == pytest.approx(60)
    assert all(f["up"] == [0.0, 0.0, 1.0] for f in frames)


def test_smooth_paths_pass_through_every_camera_and_round_the_corners():
    frames = W.path_frames(CAMS, seconds=4, fps=10, smooth=True)
    assert frames[0]["eye"] == pytest.approx([0, 0, 1.6])
    assert frames[-1]["eye"] == pytest.approx([10, 10, 1.6])
    nearest = min(math.dist(f["eye"], [10, 0, 1.6]) for f in frames)
    assert nearest < 0.5  # passes by the corner camera
    # the smooth path leaves the straight edges (y == 0, then x == 10) to round the corner
    off = [f for f in frames if abs(f["eye"][1]) > 0.05 and abs(f["eye"][0] - 10) > 0.05]
    assert off


def test_a_closed_path_returns_to_the_start_without_repeating_it():
    frames = W.path_frames(CAMS, seconds=3, fps=10, smooth=True, closed=True)
    assert len(frames) == 30
    assert frames[0]["eye"] == pytest.approx([0, 0, 1.6])
    assert math.dist(frames[-1]["eye"], frames[0]["eye"]) < math.dist(frames[-1]["eye"], [10, 10, 1.6])


def test_turning_on_the_spot_spreads_the_frames_over_the_cameras():
    cams = [{"eye": [0, 0, 1.6], "target": [1, 0, 1.6]}, {"eye": [0, 0, 1.6], "target": [0, 1, 1.6]}]
    frames = W.path_frames(cams, seconds=1, fps=4, smooth=False)
    assert len(frames) == 5
    assert frames[2]["target"] == pytest.approx([0.5, 0.5, 1.6])


def test_bad_paths_are_refused():
    with pytest.raises(ValueError):
        W.path_frames(CAMS[:1], seconds=4, fps=10)
    with pytest.raises(ValueError):
        W.path_frames(CAMS, seconds=0, fps=10)
    with pytest.raises(ValueError):
        W.path_frames(CAMS, seconds=4, fps=0)
    with pytest.raises(ValueError):
        W.path_frames(CAMS, seconds=600, fps=60)  # over the frame limit
    with pytest.raises(ValueError):
        W.path_frames([{"eye": [0, 0, 0], "target": [0, 0, 0]}, CAMS[1]], seconds=4, fps=10)  # eye == target
    with pytest.raises(ValueError):
        W.path_frames([{"eye": [0, 0], "target": [1, 0, 0]}, CAMS[1]], seconds=4, fps=10)


def test_walkthroughs_are_saved_with_the_project_and_undo():
    assert call("new_project", "Walk")["ok"]
    assert call("walkthroughs")["walkthroughs"] == []
    r = call("save_walkthrough", "Entrance", json.dumps({"cameras": CAMS, "seconds": 8}))
    assert r["ok"], r
    listed = call("walkthroughs")["walkthroughs"]
    assert [w["name"] for w in listed] == ["Entrance"]
    stored = listed[0]
    assert stored["seconds"] == 8 and stored["fps"] == W.DEFAULTS["fps"] and stored["smooth"] is True
    assert stored["frames"] == 8 * W.DEFAULTS["fps"] + 1
    f = call("walkthrough_frames", "Entrance")
    assert f["ok"] and len(f["frames"]) == stored["frames"]
    assert not call("save_walkthrough", "", json.dumps({"cameras": CAMS}))["ok"]
    assert not call("save_walkthrough", "X", json.dumps({"cameras": CAMS[:1]}))["ok"]
    assert not call("save_walkthrough", "X", json.dumps({"cameras": CAMS, "fps": 500}))["ok"]
    assert not call("walkthrough_frames", "Nope")["ok"]
    assert not call("set_project_settings", json.dumps({"walkthroughs": {"Y": {"cameras": "no"}}}))["ok"]
    assert call("undo")["ok"]
    assert call("walkthroughs")["walkthroughs"] == []
    assert call("redo")["ok"]
    assert call("delete_walkthrough", "Entrance")["ok"]
    assert call("walkthroughs")["walkthroughs"] == []
    assert not call("delete_walkthrough", "Entrance")["ok"]


def test_video_settings_are_checked():
    assert W.video_error({"size": [1280, 720]}) is None
    assert W.video_error({"size": [1281, 720]})  # H.264 needs even sizes
    assert W.video_error({"size": [64, 64]})
    assert W.codec_args("a.mp4")[0:2] == ["-c:v", "libx264"]
    assert W.codec_args("a.webm")[0:2] == ["-c:v", "libvpx-vp9"]
    with pytest.raises(ValueError):
        W.codec_args("a.avi")


def test_encoding_without_ffmpeg_reports_it(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "find_ffmpeg", lambda: None)
    (tmp_path / "frame-00000.png").write_bytes(b"")
    assert not call("encode_walkthrough_video", str(tmp_path / "empty"), 25, str(tmp_path / "out.mp4"))["ok"]
    r = call("encode_walkthrough_video", str(tmp_path), 25, str(tmp_path / "out.mp4"))
    assert not r["ok"] and "ffmpeg" in r["error"] and r["frames_kept"] is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_frames_encode_to_an_mp4(tmp_path):
    import subprocess

    subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x48:rate=5", "-frames:v", "5", str(tmp_path / "frame-%05d.png")], check=True)
    assert len(list(tmp_path.glob("frame-*.png"))) == 5
    out = tmp_path / "walk.mp4"
    r = call("encode_walkthrough_video", str(tmp_path), 5, str(out))
    assert r["ok"], r
    assert out.is_file() and out.stat().st_size > 0
    assert pathlib.Path(r["path"]) == out
