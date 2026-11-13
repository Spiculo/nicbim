# SPDX-License-Identifier: GPL-3.0-or-later
"""D249: walkthrough agent tools on the sample house. The render test needs the app binary and ffmpeg."""
import shutil
from pathlib import Path

import pytest

from kimbim.agent.catalogue import TOOLS

from test_agent_snapshot import needs_app, run, s  # noqa: F401  # the sample-house session fixture

CAMS = [{"eye": [-6, -6, 1.7], "target": [4, 3, 1.5]},
        {"eye": [14, -6, 1.7], "target": [4, 3, 1.5], "fov": 50},
        {"eye": [14, 12, 4], "target": [4, 3, 1.5]}]


def test_walkthrough_tools_are_registered():
    assert {"walkthrough.list", "walkthrough.save", "walkthrough.delete", "walkthrough.render"} <= set(TOOLS)
    assert TOOLS["walkthrough.save"].writes and not TOOLS["walkthrough.render"].writes


def test_save_list_and_delete(s):  # noqa: F811
    assert run(s, "walkthrough.list")["result"]["walkthroughs"] == []
    r = run(s, "walkthrough.save", name="Around", cameras=CAMS, seconds=2, fps=10, closed=True)
    assert r["ok"], r
    assert r["result"]["frames"] == 20 and r["result"]["closed"] is True
    listed = run(s, "walkthrough.list")["result"]
    assert listed["unit"] == "m" and [w["name"] for w in listed["walkthroughs"]] == ["Around"]
    assert listed["walkthroughs"][0]["cameras"][1]["fov"] == 50
    bad = run(s, "walkthrough.save", name="One", cameras=CAMS[:1])
    assert not bad["ok"]
    bad = run(s, "walkthrough.save", name="Odd", cameras=CAMS, size=[641, 480])
    assert not bad["ok"]
    assert run(s, "walkthrough.delete", name="Around")["ok"]
    assert run(s, "walkthrough.list")["result"]["walkthroughs"] == []
    assert not run(s, "walkthrough.render", name="Around")["ok"]


@pytest.mark.app
@needs_app
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_render_a_walkthrough_video(s, tmp_path):  # noqa: F811
    assert run(s, "walkthrough.save", name="Short", cameras=CAMS, seconds=0.4, fps=10, size=[320, 240])["ok"]
    out = tmp_path / "walk.mp4"
    r = run(s, "walkthrough.render", name="Short", out=str(out), keep_frames=True)
    assert r["ok"], r
    res = r["result"]
    assert res["path"] == str(out) and out.stat().st_size > 0
    assert res["frames"] == 5 and len(list(Path(res["frames_folder"]).glob("frame-*.png"))) == 5
