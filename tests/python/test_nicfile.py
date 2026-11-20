# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the .nic container (a zip of the project folder)."""
import json
import os
import zipfile

import pytest

from kimbim import nicfile as K


def project_folder(root):
    (root / ".git" / "objects" / "pack").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "objects" / "pack" / "pack-1.pack").write_bytes(b"PACK" + bytes(100))
    (root / ".kimbim" / "cache").mkdir(parents=True)
    (root / ".kimbim" / "cache" / "big.bin").write_bytes(bytes(1000))
    (root / ".kimbim" / "working.ifc").write_text("ISO-10303-21;\n")
    (root / ".kimbim" / "settings.json").write_text("{}\n")
    (root / ".kimbim" / "lock").write_text("{}")
    return root


def test_pack_and_unpack_round_trip(tmp_path):
    src = project_folder(tmp_path / "src")
    nic = tmp_path / "Casa ñ.nic"
    K.pack(src, nic)
    with zipfile.ZipFile(nic) as z:
        names = set(z.namelist())
        assert z.getinfo(".git/objects/pack/pack-1.pack").compress_type == zipfile.ZIP_STORED
        assert z.getinfo(".kimbim/working.ifc").compress_type == zipfile.ZIP_DEFLATED
    assert ".kimbim/cache/big.bin" not in names and ".kimbim/lock" not in names
    manifest = K.unpack(nic, tmp_path / "out")
    assert manifest["format"] == "nic" and manifest["version"] == 1 and manifest["kind"] == "project"
    assert (tmp_path / "out" / ".kimbim" / "working.ifc").read_text() == "ISO-10303-21;\n"
    assert (tmp_path / "out" / ".git" / "HEAD").exists()
    assert not (tmp_path / "out" / K.MANIFEST).exists()  # the manifest describes the file, not the folder


def test_a_failed_save_leaves_the_old_file(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    nic = tmp_path / "a.nic"
    K.pack(src, nic)
    before = nic.read_bytes()
    (src / ".kimbim" / "working.ifc").write_text("changed")
    monkeypatch.setattr(K, "_write_entries", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(K.NicError, match="No space"):
        K.pack(src, nic)
    assert nic.read_bytes() == before


def test_a_busy_target_is_retried_then_reported(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    nic = tmp_path / "a.nic"
    K.pack(src, nic)
    before = nic.read_bytes()
    calls = []

    def busy(a, b):
        calls.append(1)
        raise PermissionError(13, "in use by another program")

    monkeypatch.setattr(K.os, "replace", busy)
    monkeypatch.setattr(K, "REPLACE_WAIT", 0.0)
    with pytest.raises(K.NicError, match="in use"):
        K.pack(src, nic)
    assert len(calls) == K.REPLACE_TRIES and nic.read_bytes() == before


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "C:/x.txt", ".kimbim/../../evil.txt"])
def test_entries_outside_the_folder_are_refused(tmp_path, name):
    nic = tmp_path / "bad.nic"
    with zipfile.ZipFile(nic, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "nic", "version": 1, "kind": "project"}))
        z.writestr(name, "x")
    with pytest.raises(K.NicError, match="unsafe"):
        K.unpack(nic, tmp_path / "out" / "in")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "evil.txt").exists()


def test_damaged_unknown_and_newer_files_are_refused_untouched(tmp_path):
    junk = tmp_path / "junk.nic"
    junk.write_bytes(b"not a zip")
    with pytest.raises(K.NicError, match="not a NicBim file"):
        K.read_manifest(junk)
    nomani = tmp_path / "nomani.nic"
    with zipfile.ZipFile(nomani, "w") as z:
        z.writestr("x", "y")
    with pytest.raises(K.NicError, match="not a NicBim file"):
        K.read_manifest(nomani)
    newer = tmp_path / "newer.nic"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "nic", "version": 99, "kind": "project"}))
    with pytest.raises(K.NicError, match="newer NicBim"):
        K.unpack(newer, tmp_path / "o")
    assert junk.read_bytes() == b"not a zip"


def test_path_hash_is_stable_and_case_insensitive_on_windows(tmp_path):
    a = K.path_hash(tmp_path / "A.nic")
    assert len(a) == 16 and a == K.path_hash(str(tmp_path / "A.nic"))
    if os.name == "nt":
        assert a == K.path_hash(str(tmp_path / "a.NIC"))


def test_a_free_file_is_locked_and_released(tmp_path):
    lock = K.lock_path(tmp_path / "a.nic")
    assert lock.name == "a.nic.lock"
    assert K.acquire(lock) is None
    held = json.loads(lock.read_text())
    assert held["pid"] == os.getpid() and held["machine"] and held["user"]
    K.release(lock)
    assert not lock.exists()


def test_someone_elses_lock_is_reported(tmp_path):
    lock = tmp_path / "a.nic.lock"
    lock.write_text(json.dumps({"user": "Ana", "machine": "OTHER-PC", "pid": 1, "since": "2026-10-08T10:42"}))
    holder = K.acquire(lock)
    assert holder["user"] == "Ana" and holder["machine"] == "OTHER-PC"
    K.release(lock)  # not ours: left alone
    assert lock.exists()


def test_our_own_lock_from_a_crash_is_taken_over(tmp_path):
    lock = tmp_path / "a.nic.lock"
    dead = 999_999_999
    assert not K.pid_alive(dead)
    lock.write_text(json.dumps({**K.me(), "pid": dead}))
    assert K.acquire(lock) is None
    assert json.loads(lock.read_text())["pid"] == os.getpid()


def test_a_second_window_of_ours_does_not_take_the_lock(tmp_path):
    import subprocess
    import sys

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock = tmp_path / "a.nic.lock"
        lock.write_text(json.dumps({**K.me(), "pid": other.pid}))
        holder = K.acquire(lock)
        assert holder is not None and holder["pid"] == other.pid
    finally:
        other.kill()


def test_a_garbled_lock_counts_as_free(tmp_path):
    lock = tmp_path / "a.nic.lock"
    lock.write_text("{{{")
    assert K.acquire(lock) is None
