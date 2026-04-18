"""Local integration tests: drive ``sync_plugin`` against file:// remotes.

These tests cover the full clone -> migrate -> manifest pipeline without
touching the network. Each test builds a throw-away bare git repo under
``tmp_path``, points a plugin config at it via ``file://``, and asserts on
the resulting Hermes tree + manifest.

Scope (three scenarios, matching the Unit 4 plan):
  * happy_path — one-shot sync populates skills/agents + manifest metadata.
  * idempotent_resync — running twice leaves SKILL.md mtimes untouched.
  * branch_swap_prune — switching branches prunes removed entries, adds
    new ones, and leaves common entries byte-identical on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from hermes_plugin_sync import core
from hermes_plugin_sync.manifest import (
    META_KEY,
    entries_for_plugin,
    load_manifest,
    save_manifest,
)

from .conftest import GitRemote, clear_worktree

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers for constructing inline skill/agent trees
# ---------------------------------------------------------------------------

def _write_skill(worktree: Path, name: str, body: str = "body") -> None:
    skill_dir = worktree / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}.\nversion: 1.0.0\n---\n\n{body}\n"
    )


def _write_agent(worktree: Path, category: str, name: str) -> None:
    agent_dir = worktree / "agents" / category
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Test agent {name}.\ntools:\n  - Read\n  - Bash\n---\n\n"
        f"You are {name}.\n"
    )


# ---------------------------------------------------------------------------
# (a) happy path
# ---------------------------------------------------------------------------

def test_happy_path_populates_skills_agents_and_manifest(
    tmp_git_remote: Any,
    sample_plugin_src: Path,
    hermes_home: Path,
) -> None:
    """A first-time sync against a file:// remote populates everything."""
    remote: GitRemote = tmp_git_remote(src=sample_plugin_src)

    cfg = {
        "name": "sample-plugin",
        "git": remote.url,
        "branch": "main",
    }
    manifest: dict[str, dict[str, Any]] = {}
    core.sync_plugin(cfg, hermes_home, manifest)

    # Skills copied under skills/<plugin>/<name>/SKILL.md
    skills_root = hermes_home / "skills" / "sample-plugin"
    assert (skills_root / "hello-skill" / "SKILL.md").is_file()
    assert (skills_root / "standalone-skill" / "SKILL.md").is_file()
    # Non-SKILL.md file preserved inside the skill tree.
    assert (skills_root / "hello-skill" / "references" / "greetings.md").is_file()

    # Agents translated into delegation skills at skills/<plugin>/agents/<name>/SKILL.md
    agents_root = skills_root / "agents"
    assert (agents_root / "refactorer" / "SKILL.md").is_file()
    assert (agents_root / "literature-scout" / "SKILL.md").is_file()

    # Manifest has per-entry rows for each of the four items.
    entries = entries_for_plugin(manifest, "sample-plugin")
    assert len(entries) == 4
    kinds = {e["kind"] for e in entries.values()}
    assert kinds == {"skill", "agent"}

    # _plugins metadata populated with last_synced ISO-8601 string.
    meta = manifest[META_KEY]["sample-plugin"]
    assert meta["git"] == remote.url
    assert meta["branch"] == "main"
    assert isinstance(meta["last_synced"], str) and meta["last_synced"]


# ---------------------------------------------------------------------------
# (b) idempotency: second sync is a no-op on disk
# ---------------------------------------------------------------------------

def test_resync_is_idempotent_mtimes_unchanged(
    tmp_git_remote: Any,
    sample_plugin_src: Path,
    hermes_home: Path,
) -> None:
    """Running sync twice leaves SKILL.md files bit-identical and untouched.

    The migrator is supposed to detect ``local_hash == origin_hash`` and
    return without rewriting the destination. We verify that by capturing
    the mtime of one skill's SKILL.md and asserting it survives a second
    sync call.
    """
    remote: GitRemote = tmp_git_remote(src=sample_plugin_src)
    cfg = {"name": "sample-plugin", "git": remote.url, "branch": "main"}

    manifest: dict[str, dict[str, Any]] = {}
    core.sync_plugin(cfg, hermes_home, manifest)
    # Persist + reload the manifest the way the CLI would, so we're testing
    # the real "restart + re-run" path rather than a hot in-memory object.
    save_manifest(hermes_home, manifest)

    skill_md = hermes_home / "skills" / "sample-plugin" / "hello-skill" / "SKILL.md"
    agent_md = hermes_home / "skills" / "sample-plugin" / "agents" / "refactorer" / "SKILL.md"
    first_skill_mtime = skill_md.stat().st_mtime_ns
    first_agent_mtime = agent_md.stat().st_mtime_ns
    first_manifest = load_manifest(hermes_home)

    manifest2 = load_manifest(hermes_home)
    core.sync_plugin(cfg, hermes_home, manifest2)
    save_manifest(hermes_home, manifest2)

    assert skill_md.stat().st_mtime_ns == first_skill_mtime, \
        "skill SKILL.md was rewritten on a no-op resync"
    assert agent_md.stat().st_mtime_ns == first_agent_mtime, \
        "agent SKILL.md was rewritten on a no-op resync"

    # Per-entry rows are byte-identical. _plugins.last_synced is allowed to
    # move forward (it's rewritten on every successful run by design), so
    # we compare everything except that field.
    def _without_last_synced(m: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in m.items() if k != META_KEY}
        meta = dict(m.get(META_KEY, {}))
        for name, block in list(meta.items()):
            meta[name] = {k: v for k, v in block.items() if k != "last_synced"}
        out[META_KEY] = meta
        return out

    second_manifest = load_manifest(hermes_home)
    assert _without_last_synced(first_manifest) == _without_last_synced(second_manifest)


# ---------------------------------------------------------------------------
# (c) branch swap — prune removed, add new, preserve common
# ---------------------------------------------------------------------------

def test_branch_swap_prunes_and_preserves_common_entries(
    tmp_git_remote: Any,
    hermes_home: Path,
) -> None:
    """Swap the configured branch and verify prune/add/unchanged semantics.

    main branch:         skills=[alpha, beta] agents=[foo]
    experimental branch: skills=[beta, gamma] agents=[bar]

    After syncing ``main`` then re-syncing ``experimental`` we expect:
      * alpha + foo are removed (pruned from both disk and manifest)
      * gamma + bar appear on disk with fresh manifest entries
      * beta is byte-identical on both branches, so its SKILL.md must NOT
        be rewritten — we pin that with an mtime check.
    """
    remote: GitRemote = tmp_git_remote()

    # --- main: alpha + beta skills, foo agent ---
    _write_skill(remote.worktree, "alpha", body="alpha body")
    _write_skill(remote.worktree, "beta", body="beta body — shared verbatim")
    _write_agent(remote.worktree, "primary", "foo")
    remote.commit(branch="main", message="main: alpha, beta, foo")

    # --- experimental: beta (identical content) + gamma, bar agent ---
    # Wipe the worktree first so stale files don't ride along into the new
    # branch's tree.
    clear_worktree(remote.worktree)
    _write_skill(remote.worktree, "beta", body="beta body — shared verbatim")
    _write_skill(remote.worktree, "gamma", body="gamma body")
    _write_agent(remote.worktree, "primary", "bar")
    remote.commit(branch="experimental", message="experimental: beta, gamma, bar")

    plugin = "swap-plugin"
    skills_root = hermes_home / "skills" / plugin
    agents_root = skills_root / "agents"

    # --- first sync: main ---
    manifest: dict[str, dict[str, Any]] = {}
    core.sync_plugin(
        {"name": plugin, "git": remote.url, "branch": "main"},
        hermes_home,
        manifest,
    )

    assert (skills_root / "alpha" / "SKILL.md").is_file()
    assert (skills_root / "beta" / "SKILL.md").is_file()
    assert (agents_root / "foo" / "SKILL.md").is_file()
    assert not (skills_root / "gamma").exists()
    assert not (agents_root / "bar").exists()

    beta_path = skills_root / "beta" / "SKILL.md"
    beta_mtime_before = beta_path.stat().st_mtime_ns

    # --- second sync: experimental ---
    core.sync_plugin(
        {"name": plugin, "git": remote.url, "branch": "experimental"},
        hermes_home,
        manifest,
    )

    # Pruned.
    assert not (skills_root / "alpha").exists(), "alpha should be pruned after branch swap"
    assert not (agents_root / "foo").exists(), "foo agent should be pruned after branch swap"
    # Added.
    assert (skills_root / "gamma" / "SKILL.md").is_file()
    assert (agents_root / "bar" / "SKILL.md").is_file()
    # Common + identical: beta kept in place, mtime unchanged.
    assert beta_path.is_file()
    assert beta_path.stat().st_mtime_ns == beta_mtime_before, \
        "beta SKILL.md was rewritten even though content is identical across branches"

    # Manifest bookkeeping matches disk.
    entries = entries_for_plugin(manifest, plugin)
    keys = set(entries.keys())
    assert f"{plugin}/beta" in keys
    assert f"{plugin}/gamma" in keys
    assert f"{plugin}/agents/bar" in keys
    assert f"{plugin}/alpha" not in keys
    assert f"{plugin}/agents/foo" not in keys

    meta = manifest[META_KEY][plugin]
    assert meta["branch"] == "experimental"
    assert meta["git"] == remote.url
