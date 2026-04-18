"""Fixtures shared by the local integration tests.

These tests exercise the real clone -> migrate -> manifest path by pointing
``sync_plugin`` at a ``file://`` URL for a bare git repo created under
``tmp_path``. That keeps the tests fast (<100ms each) and deterministic while
still covering the code that would otherwise only run against the network.

The ``tmp_git_remote`` factory builds a bare repo plus a working clone rooted
at ``tmp_path``. Callers populate the worktree with skills/agents, then call
``.commit(branch=...)`` to publish one or more branches. The bare repo's
filesystem path is exposed as ``.url`` in ``file://<path>`` form, ready to
drop into a plugin config's ``git`` field.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Git helpers (isolated from user gitconfig)
# ---------------------------------------------------------------------------


def _isolated_git_env(tmp_home: Path) -> dict[str, str]:
    """Return an env that insulates git from the user's global config.

    Setting HOME + XDG_CONFIG_HOME away from the real user dir avoids picking
    up ``~/.gitconfig`` hooks, signing keys, etc. Author/committer identity
    is pinned so commits are reproducible.
    """
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["XDG_CONFIG_HOME"] = str(tmp_home / ".config")
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.invalid"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    # Defensive: some CI envs set GIT_CONFIG_NOSYSTEM=0; force it on.
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # Prevent git from pulling in commit templates or GPG signing.
    env.pop("GIT_CONFIG_GLOBAL", None)
    return env


def _run_git(args: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True)


# ---------------------------------------------------------------------------
# GitRemote — the object returned by the factory
# ---------------------------------------------------------------------------


@dataclass
class GitRemote:
    """A bare git repo plus a working clone, both rooted under tmp_path.

    Callers mutate ``worktree`` (copy files, delete things, etc.) and then
    call ``commit(branch=...)`` to publish the current state to the named
    branch on the bare repo. Branch switching inside the worktree is handled
    automatically so repeated calls with different branch names produce
    sibling branches, not a linear history.
    """

    bare: Path
    worktree: Path
    env: dict[str, str]
    _branches_seen: set[str] = field(default_factory=set)

    @property
    def url(self) -> str:
        # ``file://`` plus absolute path is what ``git clone`` expects.
        return f"file://{self.bare}"

    def commit(self, branch: str = "main", message: str = "snapshot") -> None:
        """Stage everything in the worktree and push as ``branch`` to ``bare``."""
        if branch in self._branches_seen:
            # Subsequent commits on an existing branch: just check it out.
            _run_git(["checkout", branch], self.worktree, self.env)
        elif self._branches_seen:
            # A new branch in an already-initialised repo: branch off HEAD.
            _run_git(["checkout", "-b", branch], self.worktree, self.env)
        else:
            # First commit ever: rename initial branch to the requested name.
            # ``git init -b`` was used at creation time, but if the caller
            # asked for something other than ``main`` we switch here.
            _run_git(["checkout", "-B", branch], self.worktree, self.env)

        _run_git(["add", "-A"], self.worktree, self.env)
        # Allow empty commits so callers can make a branch that only differs
        # in tree state after deletions without having to touch an untracked
        # file just to have something to stage.
        _run_git(
            ["commit", "--allow-empty", "-m", message],
            self.worktree,
            self.env,
        )
        _run_git(["push", "--force", "origin", branch], self.worktree, self.env)
        self._branches_seen.add(branch)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hermes_home(tmp_path: Path) -> Path:
    """Tmp Hermes home used as ``--hermes-home`` / ``sync_plugin`` target.

    Shadows the top-level ``tests/conftest.py`` fixture on purpose — the
    integration tests want a fresh path per test and don't need the pre-made
    ``hermes_home`` directory (sync_plugin will mkdir as needed).
    """
    return tmp_path / "hermes_home"


@pytest.fixture
def tmp_git_remote(
    tmp_path: Path,
) -> Callable[..., GitRemote]:
    """Factory: build a bare git repo + working clone rooted in ``tmp_path``.

    Usage::

        remote = tmp_git_remote()                      # empty
        remote = tmp_git_remote(src=sample_plugin_src) # pre-populated

    Returned ``GitRemote`` exposes ``.url`` (``file://...``) and ``.commit()``.
    """
    created: list[GitRemote] = []

    def _factory(src: Path | None = None, branch: str = "main") -> GitRemote:
        # Unique subdirs per invocation so one test can build multiple remotes.
        idx = len(created)
        root = tmp_path / f"git_remote_{idx}"
        bare = root / "bare.git"
        worktree = root / "worktree"
        fake_home = root / "fake_home"
        fake_home.mkdir(parents=True, exist_ok=True)
        bare.mkdir(parents=True)
        worktree.mkdir(parents=True)

        env = _isolated_git_env(fake_home)

        # Bare repo. ``-b main`` pins the initial branch so we're not at the
        # mercy of the user's ``init.defaultBranch``.
        _run_git(["init", "--bare", "-b", "main", "."], bare, env)
        # Working clone points at the bare repo via its filesystem path.
        _run_git(["init", "-b", "main", "."], worktree, env)
        _run_git(["remote", "add", "origin", str(bare)], worktree, env)

        remote = GitRemote(bare=bare, worktree=worktree, env=env)

        if src is not None:
            _copy_tree_into(src, worktree)
            remote.commit(branch=branch, message="initial import")

        created.append(remote)
        return remote

    return _factory


@pytest.fixture
def config_yaml(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write a plugin-sync.yaml pointing at a list of plugin configs.

    Returns the path to the written YAML file so tests can pass it to the
    CLI via ``--config``.
    """
    counter = {"n": 0}

    def _factory(plugins: list[dict[str, Any]]) -> Path:
        counter["n"] += 1
        path = tmp_path / f"plugin-sync-{counter['n']}.yaml"
        path.write_text(yaml.safe_dump(plugins))
        return path

    return _factory


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _copy_tree_into(src: Path, dest: Path) -> None:
    """Copy the contents of ``src/*`` into ``dest``, merging with what's there.

    ``shutil.copytree`` refuses an existing destination; we want the worktree
    to retain ``.git``, so copy per top-level child instead.
    """
    for child in src.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def clear_worktree(worktree: Path) -> None:
    """Delete every tracked entry in ``worktree`` except ``.git``.

    Integration tests that swap branches between two disjoint trees call this
    to avoid one branch's files leaking into the next commit.
    """
    for child in worktree.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
