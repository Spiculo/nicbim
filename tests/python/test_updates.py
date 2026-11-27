# SPDX-License-Identifier: GPL-3.0-or-later
"""The optional update check and the Preferences folders."""
import json

from kimbim import documents, updates


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_off_never_calls_the_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no network request when the channel is off")

    monkeypatch.setattr(updates.urllib.request, "urlopen", fail)
    out = json.loads(updates.check_for_updates("0.1.0", "off"))
    assert out["ok"] and out["channel"] == "off" and not out["update"]


def test_stable_skips_prereleases_and_reports_a_newer_version(monkeypatch):
    releases = [
        {"tag_name": "v0.3.0-beta.1", "prerelease": True, "draft": False, "html_url": "b"},
        {"tag_name": "v0.2.0", "name": "0.2.0", "prerelease": False, "draft": False, "html_url": "u"},
        {"tag_name": "v0.1.9", "prerelease": False, "draft": False, "html_url": "old"},
        {"tag_name": "v9.0.0", "draft": True, "html_url": "draft"},
    ]
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda request, timeout: _Response(releases))
    out = json.loads(updates.check_for_updates("0.1.0", "stable"))
    assert out["ok"] and out["latest"] == "0.2.0" and out["update"] is True
    assert out["url"] == "u"


def test_beta_can_see_a_prerelease(monkeypatch):
    releases = [{"tag_name": "v0.2.0-beta.1", "prerelease": True, "draft": False, "html_url": "u"}]
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda request, timeout: _Response(releases))
    out = json.loads(updates.check_for_updates("0.1.0", "beta"))
    assert out["latest"] == "0.2.0-beta.1" and out["update"] is True and out["prerelease"] is True


def test_the_same_or_older_release_is_not_an_update(monkeypatch):
    releases = [{"tag_name": "v0.1.0", "prerelease": False, "draft": False, "html_url": "u"}]
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda request, timeout: _Response(releases))
    out = json.loads(updates.check_for_updates("0.1.0", "stable"))
    assert out["update"] is False


def test_a_network_error_is_reported(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    out = json.loads(updates.check_for_updates("0.1.0", "stable"))
    assert out["ok"] is False and "offline" in out["error"]


def test_preferences_folders_reach_documents_and_plugins(tmp_path):
    from kimbim import plugins

    recovery, tmp, plugin = tmp_path / "recovery", tmp_path / "tmp", tmp_path / "plugins"
    out = json.loads(documents.set_app_folders(str(recovery), str(tmp), str(plugin)))
    assert out["ok"]
    assert documents.recovery_root() == recovery
    assert documents.tmp_dir() == tmp
    assert plugins.folder() == plugin
    # Empty values go back to the app data folder.
    documents.set_app_folders("", "", "")
    assert documents.recovery_root() == documents.data_dir() / "recovery"
    assert documents.tmp_dir() == documents.data_dir() / "tmp"
