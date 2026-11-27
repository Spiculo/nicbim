# SPDX-License-Identifier: GPL-3.0-or-later
"""Git remotes for NicBim projects (R4 follow-up).

The project is already a standard Git repository, so the app only needs the network commands:
remotes, fetch, push, pull, clone and the small helpers around them. HTTPS remotes authenticate with a
NicGit personal access token kept in the operating system credential store (never in
`preferences.json` or `.git/config`); SSH remotes use the user's SSH agent.

The token is handed to Git through a credential helper that reads environment variables, so it never
appears on a command line or in a file. `GIT_TERMINAL_PROMPT=0` keeps a missing token from opening a
terminal prompt the desktop app cannot show.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import urllib.parse

# The helper is a POSIX shell fragment, which Git for Windows also runs. It prints the credentials for
# a "get" request and nothing for "store" or "erase". The values come from the child process's
# environment, not from the command line.
_HELPER = ('!f() { if [ "$1" = get ]; then printf "username=%s\\npassword=%s\\n" '
           '"${NICBIM_GIT_USERNAME:-token}" "$NICBIM_GIT_TOKEN"; fi; }; f')


class GitError(Exception):
    pass


def host_of(url: str) -> str:
    """The server a URL belongs to, lowercased: `https://Host:443/a/b.git` -> `host:443`.

    A local path or a `file://` URL has no server and returns "".
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("file://"):
        return ""
    if "://" in url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https", "ssh", "git"):
            return ""
        host = (parsed.hostname or "").lower()
        port = parsed.port
        default = (parsed.scheme == "http" and port == 80) or \
                  (parsed.scheme == "https" and port == 443)
        if port and not default:
            host = f"{host}:{port}"
        return host
    # scp-like syntax: git@host:owner/project.git
    if ":" in url and "@" in url.split(":", 1)[0]:
        return url.split("@", 1)[1].split(":", 1)[0].lower()
    return ""  # a local path


def is_https(url: str) -> bool:
    return (url or "").strip().lower().startswith(("http://", "https://"))


def _credentials():
    # Imported lazily: kimbim.agent loads the tool catalogue, which imports the project module.
    from .agent import credentials

    return credentials


def token_for(url: str, token: str = "") -> str:
    return (token or "").strip() or _credentials().get_git_token(host_of(url))


def clean_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for an external `git`.

    The launcher exports DYLD_LIBRARY_PATH on macOS and LD_LIBRARY_PATH on Linux so OCCT and Qt find
    the pixi libraries. A system git started with those variables can load the pixi libiconv instead
    of its own and die with a missing symbol, so the library paths are removed for the child process.
    A conda-forge git finds its libraries through its own rpath.
    """
    env = dict(os.environ if base is None else base)
    if sys.platform == "darwin":
        env.pop("DYLD_LIBRARY_PATH", None)
        env.pop("DYLD_INSERT_LIBRARIES", None)
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def _auth_args(url: str, username: str, token: str) -> tuple[list[str], dict[str, str]]:
    """The `git -c` arguments and environment entries for one HTTPS operation."""
    token = token_for(url, token)
    if not token or not is_https(url):
        return [], {}
    env = {"NICBIM_GIT_USERNAME": (username or "token").strip() or "token",
           "NICBIM_GIT_TOKEN": token}
    # An empty credential.helper resets the list, so a system helper cannot answer first with a stale
    # password; ours then reads the environment.
    return ["-c", "credential.helper=", "-c", f"credential.helper={_HELPER}"], env


def _friendly(stderr: str, url: str) -> str:
    text = (stderr or "").strip()
    if any(s in text for s in ("Authentication failed", "could not read Username",
                               "HTTP Basic: Access denied", "The requested URL returned error: 401",
                               "The requested URL returned error: 403")):
        host = host_of(url)
        where = f" for {host}" if host else ""
        return (f"authentication failed{where}: create a personal access token in NicGit "
                f"(Settings > Access) and save it for this server")
    return text.splitlines()[-1] if text else "git failed"


def run(args: list[str], *, git_dir: str | pathlib.Path | None = None, url: str = "",
        username: str = "", token: str = "", proxy: str = "", cwd: str | pathlib.Path | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    """Run one git command. `git_dir` makes it operate on a project store without a working tree."""
    cmd = ["git"]
    if git_dir is not None:
        cmd.append(f"--git-dir={pathlib.Path(git_dir)}")
    auth, extra = _auth_args(url, username, token)
    cmd += auth
    cmd += args
    env = {**clean_env(), "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", **extra}
    if proxy.strip():
        for key in ("https_proxy", "http_proxy", "all_proxy"):
            env[key] = proxy.strip()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                cwd=str(cwd) if cwd is not None else None)
    except OSError as ex:
        raise GitError(f"could not run git: {ex}") from None
    if check and result.returncode != 0:
        raise GitError(_friendly(result.stderr or result.stdout, url))
    return result


def out(args: list[str], **kwargs) -> str:
    return run(args, **kwargs).stdout.strip()


def rev_parse(git_dir, rev: str) -> str:
    result = run(["rev-parse", "--verify", "--quiet", rev], git_dir=git_dir, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def is_ancestor(git_dir, ancestor: str, descendant: str) -> bool:
    return run(["merge-base", "--is-ancestor", ancestor, descendant], git_dir=git_dir, check=False).returncode == 0


def commit_info(git_dir, rev: str) -> dict:
    if not rev:
        return {}
    text = out(["log", "-1", "--format=%H%x00%an%x00%ae%x00%at%x00%s", rev], git_dir=git_dir)
    parts = text.split("\x00")
    if len(parts) < 5:
        return {}
    try:
        stamp = int(parts[3])
    except ValueError:
        stamp = 0
    return {"id": parts[0], "author": parts[1], "email": parts[2], "time": stamp, "message": parts[4]}


def branches(git_dir) -> list[dict]:
    text = out(["for-each-ref", "--format=%(refname:short)%00%(objectname)%00%(authorname)%00"
                "%(authordate:unix)%00%(subject)", "refs/heads"], git_dir=git_dir)
    out_rows = []
    for line in text.splitlines():
        parts = line.split("\x00")
        if len(parts) < 5:
            continue
        try:
            stamp = int(parts[3])
        except ValueError:
            stamp = 0
        out_rows.append({"name": parts[0], "head": parts[1], "author": parts[2], "time": stamp,
                         "message": parts[4]})
    return out_rows


def remote_branches(git_dir, remote: str) -> list[dict]:
    prefix = f"refs/remotes/{remote}"
    text = out(["for-each-ref", "--format=%(refname:short)%00%(objectname)%00%(subject)", prefix],
               git_dir=git_dir)
    rows = []
    for line in text.splitlines():
        parts = line.split("\x00")
        if len(parts) < 3:
            continue
        name = parts[0]
        if name.startswith(f"{remote}/"):
            name = name[len(remote) + 1:]
        if name in ("HEAD", ""):
            continue
        rows.append({"name": name, "head": parts[1], "message": parts[2]})
    return rows


def remote_url(git_dir, name: str) -> str:
    return out(["remote", "get-url", name], git_dir=git_dir)


def set_remote_url(git_dir, name: str, url: str) -> None:
    run(["remote", "set-url", name, url], git_dir=git_dir)


def rename_remote(git_dir, old: str, new: str) -> None:
    run(["remote", "rename", old, new], git_dir=git_dir)


def fetch(git_dir, remote: str, *, username: str = "", token: str = "", proxy: str = "") -> str:
    url = remote_url(git_dir, remote)
    return out(["fetch", "--prune", "--tags", remote, f"+refs/heads/*:refs/remotes/{remote}/*"],
               git_dir=git_dir, url=url, username=username, token=token, proxy=proxy)


def push(git_dir, remote: str, branch: str, *, force: bool = False, tags: bool = False,
         username: str = "", token: str = "", proxy: str = "") -> str:
    url = remote_url(git_dir, remote)
    args = ["push", "--porcelain"]
    if force:
        args.append("--force-with-lease")
    if tags:
        args.append("--follow-tags")
    args += [remote, f"refs/heads/{branch}:refs/heads/{branch}"]
    return out(args, git_dir=git_dir, url=url, username=username, token=token, proxy=proxy)


def push_tags(git_dir, remote: str, *, username: str = "", token: str = "", proxy: str = "") -> str:
    url = remote_url(git_dir, remote)
    return out(["push", "--porcelain", remote, "--tags"], git_dir=git_dir, url=url,
               username=username, token=token, proxy=proxy)


def delete_remote_branch(git_dir, remote: str, branch: str, *, username: str = "", token: str = "",
                         proxy: str = "") -> str:
    url = remote_url(git_dir, remote)
    return out(["push", "--porcelain", remote, "--delete", branch], git_dir=git_dir, url=url,
               username=username, token=token, proxy=proxy)


def status(git_dir, remote: str, branch: str) -> dict:
    """Local head versus its remote-tracking ref, without touching the network."""
    head = rev_parse(git_dir, "HEAD")
    ref = f"refs/remotes/{remote}/{branch}"
    remote_head = rev_parse(git_dir, ref)
    info = commit_info(git_dir, ref) if remote_head else {}
    result = {"remote": remote, "branch": branch, "head": head, "remote_head": remote_head,
              "ahead": 0, "behind": 0, "state": "no_remote", "remote_commit": info}
    if not remote_head:
        return result
    if not head:
        behind = run(["rev-list", "--count", ref], git_dir=git_dir, check=False).stdout.strip()
        result["state"] = "behind"
        try:
            result["behind"] = int(behind)
        except ValueError:
            pass
        return result
    if head == remote_head:
        result["state"] = "up_to_date"
        return result
    counts = run(["rev-list", "--left-right", "--count", f"{head}...{ref}"], git_dir=git_dir,
                 check=False).stdout.split()
    if len(counts) == 2:
        try:
            result["ahead"], result["behind"] = int(counts[0]), int(counts[1])
        except ValueError:
            pass
    if result["ahead"] and result["behind"]:
        result["state"] = "diverged"
    elif result["ahead"]:
        result["state"] = "ahead"
    else:
        result["state"] = "behind"
    return result


def test_remote(url: str, *, username: str = "", token: str = "", proxy: str = "") -> dict:
    """List the remote's branches without changing anything (a connection and auth test)."""
    text = out(["ls-remote", "--heads", url], url=url, username=username, token=token, proxy=proxy)
    names = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            names.append(parts[1][len("refs/heads/"):])
    return {"url": url, "branches": sorted(names), "count": len(names)}


def clone(url: str, folder: str, *, username: str = "", token: str = "", proxy: str = "") -> dict:
    """Clone a project repository without checking records out: the app reads the tree itself."""
    url = (url or "").strip()
    if not url:
        raise GitError("the project address is empty")
    target = pathlib.Path(folder)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise GitError("choose a new or empty folder for the clone")
    target.parent.mkdir(parents=True, exist_ok=True)
    # --no-checkout keeps the records in Git: a NicBim project folder is a store, not a working tree.
    out(["clone", "--no-checkout", "--origin", "origin", url, str(target)],
        url=url, username=username, token=token, proxy=proxy)
    git_dir = target / ".git"
    branch = out(["symbolic-ref", "--short", "HEAD"], git_dir=git_dir, check=False).strip()
    head = rev_parse(git_dir, "HEAD")
    if not head:
        # A bare remote made by `git init --bare` may advertise a HEAD that does not exist (it names
        # master while the project pushed main). Pick the project's main, else its first branch.
        names = [b["name"] for b in remote_branches(git_dir, "origin")]
        pick = "main" if "main" in names else (names[0] if names else "")
        if pick:
            run(["symbolic-ref", "HEAD", f"refs/heads/{pick}"], git_dir=git_dir)
            run(["update-ref", f"refs/heads/{pick}", f"refs/remotes/origin/{pick}"], git_dir=git_dir)
            branch, head = pick, rev_parse(git_dir, "HEAD")
    return {"folder": str(target), "branch": branch, "head": head}


def find_git() -> str:
    return shutil.which("git") or ""
