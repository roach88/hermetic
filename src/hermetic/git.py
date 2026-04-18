"""Thin wrapper around ``git clone`` / ``git fetch`` for plugin repos.

Behavior matches the source script: shallow clone on first run, shallow
fetch + hard reset on subsequent runs. If a non-git directory exists at the
destination it is removed before the clone so we never silently merge into
unrelated state.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def clone_or_update(url: str, branch: str, dest: Path) -> None:
    """Clone ``url@branch`` to ``dest``, or update an existing clone in place.

    Raises ``subprocess.CalledProcessError`` on git failure - callers are
    expected to translate that into a per-plugin error and continue with the
    next plugin, matching the original script's behavior.
    """
    if dest.exists() and (dest / ".git").exists():
        logger.info("Updating plugin repo at %s", dest)
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth=1", "origin", branch],
            check=True,
        )
        # Reset against FETCH_HEAD rather than origin/<branch>: a
        # single-branch shallow clone only tracks the original branch's
        # remote-tracking ref, so ``origin/<new_branch>`` does not exist
        # after fetching a different branch. FETCH_HEAD is always written
        # by the fetch above and points to whatever we just pulled.
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", "FETCH_HEAD"],
            check=True,
        )
        return
    if dest.exists():
        logger.info("Removing non-git dir at %s before clone", dest)
        shutil.rmtree(dest)
    logger.info("Cloning %s@%s -> %s", url, branch, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", branch, url, str(dest)],
        check=True,
    )
