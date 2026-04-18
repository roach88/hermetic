"""Unit-ish tests for ``clone_or_update`` against a file:// remote.

These sit under ``tests/integration/`` because they need a real bare git
repo to exercise the shallow-clone + fetch code path. They isolate the
git layer from the migrator core so a regression in clone/reset logic
surfaces directly here rather than as a confusing end-to-end failure.

The load-bearing scenario is branch-swap: an initial clone pinned to
``main`` must successfully fetch + check out ``experimental`` on a
subsequent call. Earlier versions reset against ``origin/<branch>``,
which does not exist after a single-branch shallow clone — FETCH_HEAD
is used instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hermetic.git import clone_or_update

from .conftest import GitRemote

pytestmark = pytest.mark.integration


def _write(remote: GitRemote, rel: str, contents: str) -> None:
    path = remote.worktree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)


def test_initial_clone_creates_git_dir(
    tmp_git_remote: Any,
    tmp_path: Path,
) -> None:
    remote: GitRemote = tmp_git_remote()
    _write(remote, "README.md", "hello")
    remote.commit(branch="main")

    dest = tmp_path / "clone"
    clone_or_update(remote.url, "main", dest)

    assert (dest / ".git").is_dir()
    assert (dest / "README.md").read_text() == "hello"


def test_resync_same_branch_pulls_latest(
    tmp_git_remote: Any,
    tmp_path: Path,
) -> None:
    remote: GitRemote = tmp_git_remote()
    _write(remote, "README.md", "v1")
    remote.commit(branch="main", message="v1")

    dest = tmp_path / "clone"
    clone_or_update(remote.url, "main", dest)
    assert (dest / "README.md").read_text() == "v1"

    # New commit on the same branch.
    _write(remote, "README.md", "v2")
    remote.commit(branch="main", message="v2")

    clone_or_update(remote.url, "main", dest)
    assert (dest / "README.md").read_text() == "v2"


def test_resync_different_branch_swaps_tree(
    tmp_git_remote: Any,
    tmp_path: Path,
) -> None:
    """Regression test for the branch-swap bug.

    The first sync pins ``main``; a second sync with ``experimental`` must
    successfully switch the clone's worktree to the experimental tip. A
    previous implementation reset against ``origin/experimental``, which
    does not exist after a single-branch shallow clone of ``main``.
    """
    remote: GitRemote = tmp_git_remote()

    # main branch carries file ``only_main.txt``.
    _write(remote, "only_main.txt", "main")
    remote.commit(branch="main", message="main tip")

    # experimental branch replaces that file with ``only_experimental.txt``.
    # Wipe the worktree so the branch's tree is exactly one file.
    from .conftest import clear_worktree

    clear_worktree(remote.worktree)
    _write(remote, "only_experimental.txt", "experimental")
    remote.commit(branch="experimental", message="experimental tip")

    dest = tmp_path / "clone"
    clone_or_update(remote.url, "main", dest)
    assert (dest / "only_main.txt").is_file()
    assert not (dest / "only_experimental.txt").exists()

    clone_or_update(remote.url, "experimental", dest)
    assert (dest / "only_experimental.txt").is_file()
    assert not (dest / "only_main.txt").exists()


def test_non_git_dest_is_removed_before_clone(
    tmp_git_remote: Any,
    tmp_path: Path,
) -> None:
    """A dest that exists but isn't a git repo is wiped and re-cloned."""
    remote: GitRemote = tmp_git_remote()
    _write(remote, "README.md", "hello")
    remote.commit(branch="main")

    dest = tmp_path / "clone"
    dest.mkdir()
    (dest / "stray.txt").write_text("should be gone after clone")

    clone_or_update(remote.url, "main", dest)

    assert (dest / ".git").is_dir()
    assert not (dest / "stray.txt").exists()
    assert (dest / "README.md").read_text() == "hello"
