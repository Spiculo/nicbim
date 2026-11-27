# SPDX-License-Identifier: GPL-3.0-or-later
"""Push and pull to a Git remote (thin wrappers over git; the storage is already Git)."""
import pathlib
import subprocess

import pytest

from kimbim.project import KimbimError, Project
from kimbim.testing import build_model


def make_project(tmp_path, name="project"):
    model = build_model(walls=2)
    first = tmp_path / f"{name}.ifc"
    model.write(str(first))
    project = Project.init(tmp_path / name)
    project.commit(first, "Initial import")
    return project, model, first


def bare_remote(tmp_path):
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return path


def test_push_and_pull_fast_forward(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    assert project.remotes() == [{"name": "origin", "url": str(remote)}]

    pushed = project.push()
    assert pushed["branch"] == "main" and pushed["remote"] == "origin"
    head = project.head_commit()
    assert subprocess.run(["git", f"--git-dir={remote}", "rev-parse", "main"], check=True,
                          capture_output=True, text=True).stdout.strip() == head

    model.by_type("IfcWall")[0].Name = "Second"
    second = tmp_path / "second.ifc"
    model.write(str(second))
    project.commit(second, "Second version")
    project.push()

    # A fresh project pulls the branch: the first pull creates it, the second is up to date.
    clone = Project.init(tmp_path / "clone")
    clone.add_remote("origin", str(remote))
    out = clone.pull()
    assert out["status"] == "fast_forward" and out["head"] == project.head_commit()
    assert clone.head_commit() == project.head_commit()
    assert clone.diff("HEAD~1", "HEAD").modified

    model.by_type("IfcWall")[1].Name = "Third"
    third = tmp_path / "third.ifc"
    model.write(str(third))
    project.commit(third, "Third version")
    project.push()
    assert clone.pull()["head"] == project.head_commit()

    with pytest.raises(KimbimError):
        project.pull("nope")


def test_diverged_branches_are_refused(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    clone = Project.init(tmp_path / "clone")
    clone.add_remote("origin", str(remote))
    clone.pull()
    # Both sides start from the same version and then make a different one.
    other = Project.init(tmp_path / "other")
    other.add_remote("origin", str(remote))
    other.pull()

    model.by_type("IfcWall")[0].Name = "From source"
    changed = tmp_path / "source.ifc"
    model.write(str(changed))
    project.commit(changed, "Source change")
    project.push()

    other_model = Project.open(tmp_path / "other").export(tmp_path / "other-base.ifc")
    import ifcopenshell
    f = ifcopenshell.open(str(other_model))
    f.by_type("IfcWall")[0].Name = "From other"
    changed = tmp_path / "other.ifc"
    f.write(str(changed))
    other.commit(changed, "Other change")
    with pytest.raises(KimbimError, match="diverged"):
        other.pull()


def test_diverged_pull_can_merge_with_kimbim_records(tmp_path):
    import ifcopenshell

    project, model, _first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    other = Project.init(tmp_path / "other")
    other.add_remote("origin", str(remote))
    other.pull()

    # The remote changes one wall; the local option changes the other: a clean record merge.
    walls = model.by_type("IfcWall")
    remote_wall, local_wall = walls[0], walls[1]
    remote_wall.Name = "From source"
    changed = tmp_path / "source.ifc"
    model.write(str(changed))
    project.commit(changed, "Source change")
    project.push()

    base = other.export(tmp_path / "other-base.ifc")
    f = ifcopenshell.open(str(base))
    f.by_guid(local_wall.GlobalId).Name = "From other"
    changed = tmp_path / "other.ifc"
    f.write(str(changed))
    other.commit(changed, "Other change")

    out = other.pull(merge=True)
    assert out["status"] == "merged", out
    assert out["head"] == other.head_commit()
    merge = other.log(limit=1)[0]
    assert len(merge.parents) == 2  # a NicBim merge commit, not git's text merge

    merged = ifcopenshell.open(str(other.export(tmp_path / "merged.ifc")))
    names = sorted(w.Name for w in merged.by_type("IfcWall"))
    assert names == ["From other", "From source"]


def test_remote_management(tmp_path):
    project, _, _ = make_project(tmp_path)
    assert project.remotes() == []
    project.add_remote("origin", "https://example.invalid/repo.git")
    assert [r["name"] for r in project.remotes()] == ["origin"]
    project.remove_remote("origin")
    assert project.remotes() == []
    with pytest.raises(KimbimError):
        project.add_remote("", "x")


def test_fetch_status_and_remote_branches(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    model.by_type("IfcWall")[0].Name = "Second"
    second = tmp_path / "second.ifc"
    model.write(str(second))
    project.commit(second, "Second version")
    project.push()

    other = Project.init(tmp_path / "other")
    other.add_remote("origin", str(remote))
    assert other.remote_status()["state"] == "no_remote"
    assert other.fetch()["branches"][0]["name"] == "main"
    assert other.remote_status()["state"] == "behind"
    assert other.remote_status()["behind"] == 2
    assert [b["name"] for b in other.remote_branches()] == ["main"]
    assert Project.test_remote(str(remote))["branches"] == ["main"]

    other.pull()
    assert other.remote_status()["state"] == "up_to_date"
    assert other.remote_branches()[0]["message"] == "Second version"


def test_tags_milestones_and_remote_branch_deletion(tmp_path):
    project, _, _ = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.tag("permit-set", "Permit set")
    project.push()
    project.push_tags()

    tags = subprocess.run(["git", f"--git-dir={remote}", "tag"], check=True, capture_output=True,
                          text=True).stdout.split()
    assert tags == ["permit-set"]

    project.create_branch("option-b")
    project.push(branch="option-b")
    assert sorted(b["name"] for b in project.remote_branches()) == ["main", "option-b"]
    project.delete_remote_branch("origin", "option-b")
    assert [b["name"] for b in project.remote_branches()] == ["main"]


def test_clone_reads_the_tree_without_checking_records_out(tmp_path):
    project, model, _ = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    folder = tmp_path / "cloned"
    clone = Project.clone(str(remote), str(folder))
    assert clone.head_commit() == project.head_commit()
    assert clone.current_branch() == project.current_branch()
    # A NicBim project is a store: the records stay in Git, not in a working tree.
    assert not (folder / "records").exists()
    assert clone.export(tmp_path / "cloned.ifc").exists()

    with pytest.raises(KimbimError):
        Project.clone(str(remote), str(folder))  # not empty
    with pytest.raises(KimbimError):
        Project.clone(str(tmp_path / "gone.git"), str(tmp_path / "nowhere"))


def test_a_diverged_pull_can_force_either_side(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    other = Project.init(tmp_path / "other")
    other.add_remote("origin", str(remote))
    other.pull()

    model.by_type("IfcWall")[0].Name = "From source"
    changed = tmp_path / "source.ifc"
    model.write(str(changed))
    project.commit(changed, "Source change")
    project.push()

    other.head_commit()
    import ifcopenshell
    base = other.export(tmp_path / "other-base.ifc")
    f = ifcopenshell.open(str(base))
    f.by_type("IfcWall")[0].Name = "From other"
    local = tmp_path / "other.ifc"
    f.write(str(local))
    other.commit(local, "Other change")
    out = other.pull(mode="force_remote")
    assert out["status"] == "forced_remote"
    assert other.head_commit() == project.head_commit()

    # Diverge again: one version on each side. force_local pushes the local one over the remote.
    import ifcopenshell
    base = other.export(tmp_path / "other-base-2.ifc")
    f = ifcopenshell.open(str(base))
    f.by_type("IfcWall")[0].Name = "Other again"
    local = tmp_path / "other-2.ifc"
    f.write(str(local))
    other.commit(local, "Other again")
    local_head = other.head_commit()

    f = ifcopenshell.open(str(project.export(tmp_path / "source-2.ifc")))
    f.by_type("IfcWall")[0].Name = "Source again"
    source = tmp_path / "source-2.ifc"
    f.write(str(source))
    project.commit(source, "Source again")
    project.push()

    out = other.pull(mode="force_local")
    assert out["status"] == "forced_local"
    assert out["head"] == local_head
    remote_head = subprocess.run(["git", f"--git-dir={remote}", "rev-parse", "main"], check=True,
                                 capture_output=True, text=True).stdout.strip()
    assert remote_head == local_head


def test_https_token_auth_arguments_never_reach_the_command_line(tmp_path, monkeypatch):
    from kimbim import gitremote

    monkeypatch.setattr(gitremote, "_credentials",
                        lambda: type("C", (), {"get_git_token": staticmethod(lambda host: "secret")})())
    args, env = gitremote._auth_args("https://nicgit.example.com/o/p.git", "ana", "")
    text = " ".join(args)
    assert "secret" not in text
    assert env["NICBIM_GIT_TOKEN"] == "secret"
    assert env["NICBIM_GIT_USERNAME"] == "ana"
    assert "credential.helper=" in args
    assert gitremote.host_of("https://NicGit.Example.com/o/p.git") == "nicgit.example.com"
    assert gitremote.host_of("git@example.com:o/p.git") == "example.com"
    assert gitremote.host_of(str(tmp_path / "local.git")) == ""
    assert gitremote._auth_args("git@example.com:o/p.git", "ana", "secret") == ([], {})


def test_the_git_child_does_not_inherit_the_launcher_library_path(monkeypatch):
    import sys
    from kimbim import gitremote

    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/tmp/pixi/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/pixi/lib")
    env = gitremote.clean_env()
    if sys.platform == "darwin":
        assert "DYLD_LIBRARY_PATH" not in env
    else:
        assert "LD_LIBRARY_PATH" not in env
