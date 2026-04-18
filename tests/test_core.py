"""Tests for ``hermetic.core``."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from hermetic import core
from hermetic.core import (
    build_delegation_skill,
    migrate_agent,
    migrate_skill,
    prune_removed,
    sync_plugin,
)
from hermetic.frontmatter import parse_frontmatter, sha256_file


def _no_op_clone(*args: object, **kwargs: object) -> None:
    """Replacement for clone_or_update - the fixture is already on disk."""
    return None


# ---------------------------------------------------------------------------
# build_delegation_skill
# ---------------------------------------------------------------------------


def test_build_delegation_skill_shape() -> None:
    cc_fm = {
        "name": "refactorer",
        "description": "Safe refactor persona.",
        "tools": ["Read", "Edit", "Bash"],
    }
    body = "You are a senior engineer."
    out = build_delegation_skill("sample-plugin", "refactorer", cc_fm, body)

    fm, rendered_body = parse_frontmatter(out)
    assert fm["name"] == "sample-plugin/agent/refactorer"
    assert fm["description"] == "Safe refactor persona."
    assert fm["version"] == "1.0.0"
    assert fm["metadata"]["hermes"]["source"] == "sample-plugin"
    assert fm["metadata"]["hermes"]["source_kind"] == "agent"
    assert fm["metadata"]["hermes"]["upstream_name"] == "refactorer"
    assert fm["metadata"]["hermes"]["toolsets"] == ["file", "terminal"]

    assert "Delegation skill" in rendered_body
    assert "## Persona" in rendered_body
    assert "You are a senior engineer." in rendered_body
    # Toolsets line in the body matches the metadata.
    assert "['file', 'terminal']" in rendered_body


def test_build_delegation_skill_default_description_when_missing() -> None:
    out = build_delegation_skill("p", "anon", {}, "body")
    fm, _ = parse_frontmatter(out)
    assert fm["description"] == "Delegate to the anon sub-agent persona."


def test_build_delegation_skill_unknown_tools_warning_in_body() -> None:
    cc_fm = {"name": "x", "description": "d", "tools": "Read, Frobnicate"}
    out = build_delegation_skill("p", "x", cc_fm, "body")
    assert "Frobnicate" in out
    assert "not mapped" in out


# ---------------------------------------------------------------------------
# migrate_skill
# ---------------------------------------------------------------------------


def test_migrate_skill_first_run_copies_tree(hermes_home: Path, sample_plugin_src: Path) -> None:
    src = sample_plugin_src / "skills" / "hello-skill"
    dest = hermes_home / "skills" / "sample-plugin" / "hello-skill"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)

    assert (dest / "SKILL.md").exists()
    assert (dest / "references" / "greetings.md").exists()
    key = "sample-plugin/hello-skill"
    assert key in manifest
    assert manifest[key]["plugin"] == "sample-plugin"
    assert manifest[key]["kind"] == "skill"
    assert manifest[key]["origin_hash"] == sha256_file(src / "SKILL.md")


def test_migrate_skill_idempotent_second_run_does_not_rewrite(
    hermes_home: Path, sample_plugin_src: Path
) -> None:
    src = sample_plugin_src / "skills" / "standalone-skill"
    dest = hermes_home / "skills" / "sample-plugin" / "standalone-skill"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)
    mtime_before = (dest / "SKILL.md").stat().st_mtime_ns

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)
    mtime_after = (dest / "SKILL.md").stat().st_mtime_ns

    assert mtime_after == mtime_before


def test_migrate_skill_upstream_change_overwrites(
    hermes_home: Path, sample_plugin_src: Path, tmp_path: Path
) -> None:
    # Stage a writable copy of the source so we can simulate upstream edits.
    src = tmp_path / "src_skill"
    shutil.copytree(sample_plugin_src / "skills" / "standalone-skill", src)
    dest = hermes_home / "skills" / "sample-plugin" / "standalone-skill"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)
    first_hash = manifest["sample-plugin/standalone-skill"]["origin_hash"]

    # Upstream changes - bump the description.
    md = src / "SKILL.md"
    md.write_text(md.read_text().replace("0.1.0", "0.2.0"))

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)
    second_hash = manifest["sample-plugin/standalone-skill"]["origin_hash"]
    assert second_hash != first_hash
    assert "0.2.0" in (dest / "SKILL.md").read_text()


def test_migrate_skill_user_modified_is_preserved(
    hermes_home: Path, sample_plugin_src: Path, tmp_path: Path, caplog
) -> None:
    src = tmp_path / "src_skill"
    shutil.copytree(sample_plugin_src / "skills" / "standalone-skill", src)
    dest = hermes_home / "skills" / "sample-plugin" / "standalone-skill"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)

    # User edits the local file.
    user_text = "USER LOCAL EDIT\n"
    (dest / "SKILL.md").write_text(user_text)

    # Upstream also changes.
    md = src / "SKILL.md"
    md.write_text(md.read_text().replace("0.1.0", "0.3.0"))

    with caplog.at_level(logging.WARNING, logger="hermetic.core"):
        migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)

    assert (dest / "SKILL.md").read_text() == user_text
    assert any("user-modified" in rec.message.lower() for rec in caplog.records)


def test_migrate_skill_missing_skill_md_skips(hermes_home: Path, tmp_path: Path) -> None:
    src = tmp_path / "no_skill_md"
    src.mkdir()
    (src / "stray.txt").write_text("hi")
    dest = hermes_home / "skills" / "sample-plugin" / "no_skill"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_skill(src, dest, manifest, "sample-plugin", hermes_home)

    assert manifest == {}
    assert not dest.exists()


# ---------------------------------------------------------------------------
# migrate_agent
# ---------------------------------------------------------------------------


def test_migrate_agent_translates_to_delegation_skill(
    hermes_home: Path, sample_plugin_src: Path
) -> None:
    src = sample_plugin_src / "agents" / "code" / "refactorer.md"
    dest = hermes_home / "skills" / "sample-plugin" / "agents" / "refactorer"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_agent(src, dest, manifest, "sample-plugin", hermes_home)

    assert (dest / "SKILL.md").exists()
    fm, body = parse_frontmatter((dest / "SKILL.md").read_text())
    assert fm["name"] == "sample-plugin/agent/refactorer"
    assert "Delegation skill" in body
    key = "sample-plugin/agents/refactorer"
    assert key in manifest
    assert manifest[key]["kind"] == "agent"


def test_migrate_agent_idempotent(hermes_home: Path, sample_plugin_src: Path) -> None:
    src = sample_plugin_src / "agents" / "code" / "refactorer.md"
    dest = hermes_home / "skills" / "sample-plugin" / "agents" / "refactorer"
    dest.parent.mkdir(parents=True)
    manifest: dict[str, dict] = {}

    migrate_agent(src, dest, manifest, "sample-plugin", hermes_home)
    first_hash = manifest["sample-plugin/agents/refactorer"]["origin_hash"]
    mtime_before = (dest / "SKILL.md").stat().st_mtime_ns

    migrate_agent(src, dest, manifest, "sample-plugin", hermes_home)
    assert manifest["sample-plugin/agents/refactorer"]["origin_hash"] == first_hash
    assert (dest / "SKILL.md").stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# sync_plugin (integration)
# ---------------------------------------------------------------------------


def test_sync_plugin_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)

    manifest: dict[str, dict] = {}
    sync_plugin(plugin_cfg, hermes_home, manifest)

    skills_dir = hermes_home / "skills"
    assert (skills_dir / "sample-plugin" / "hello-skill" / "SKILL.md").exists()
    assert (skills_dir / "sample-plugin" / "hello-skill" / "references" / "greetings.md").exists()
    assert (skills_dir / "sample-plugin" / "standalone-skill" / "SKILL.md").exists()
    assert (skills_dir / "sample-plugin" / "agents" / "refactorer" / "SKILL.md").exists()
    assert (skills_dir / "sample-plugin" / "agents" / "literature-scout" / "SKILL.md").exists()

    # Manifest entries cover both skills + both agents.
    assert "sample-plugin/hello-skill" in manifest
    assert "sample-plugin/standalone-skill" in manifest
    assert "sample-plugin/agents/refactorer" in manifest
    assert "sample-plugin/agents/literature-scout" in manifest


def test_sync_plugin_idempotent_no_mtime_change(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}

    sync_plugin(plugin_cfg, hermes_home, manifest)
    skill_md = hermes_home / "skills" / "sample-plugin" / "hello-skill" / "SKILL.md"
    agent_md = hermes_home / "skills" / "sample-plugin" / "agents" / "refactorer" / "SKILL.md"
    skill_mtime = skill_md.stat().st_mtime_ns
    agent_mtime = agent_md.stat().st_mtime_ns

    sync_plugin(plugin_cfg, hermes_home, manifest)
    assert skill_md.stat().st_mtime_ns == skill_mtime
    assert agent_md.stat().st_mtime_ns == agent_mtime


def test_prune_removed_drops_upstream_deletions(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}

    sync_plugin(plugin_cfg, hermes_home, manifest)
    assert "sample-plugin/standalone-skill" in manifest

    # Simulate upstream removing standalone-skill.
    shutil.rmtree(cloned_plugin / "skills" / "standalone-skill")
    sync_plugin(plugin_cfg, hermes_home, manifest)

    assert "sample-plugin/standalone-skill" not in manifest
    assert not (hermes_home / "skills" / "sample-plugin" / "standalone-skill").exists()


def test_prune_removed_preserves_user_modified(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
    caplog,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}

    sync_plugin(plugin_cfg, hermes_home, manifest)

    # User edits the standalone skill in the destination.
    dest_md = hermes_home / "skills" / "sample-plugin" / "standalone-skill" / "SKILL.md"
    dest_md.write_text("USER MODIFIED\n")

    # Upstream removes the skill.
    shutil.rmtree(cloned_plugin / "skills" / "standalone-skill")

    with caplog.at_level(logging.WARNING, logger="hermetic.core"):
        sync_plugin(plugin_cfg, hermes_home, manifest)

    assert dest_md.exists()
    assert dest_md.read_text() == "USER MODIFIED\n"
    assert any(
        "user-modified" in rec.message.lower() and "removed" in rec.message.lower()
        for rec in caplog.records
    )


def test_prune_removed_with_no_dest_dir_just_drops_manifest_entry(
    hermes_home: Path,
) -> None:
    # If the manifest references a key whose dest dir was already deleted,
    # prune_removed should still drop the manifest entry without crashing.
    manifest = {
        "sample-plugin/ghost": {
            "plugin": "sample-plugin",
            "kind": "skill",
            "source_path": "/dev/null",
            "origin_hash": "ffff",
        }
    }
    prune_removed("sample-plugin", set(), manifest, hermes_home)
    assert manifest == {}


def test_sync_plugin_records_plugin_metadata(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    # Unit-3 schema extension: after a successful sync the manifest carries
    # a `_plugins[<name>]` block with git/branch/last_synced.
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}

    sync_plugin(plugin_cfg, hermes_home, manifest)

    assert "_plugins" in manifest
    meta = manifest["_plugins"]["sample-plugin"]
    assert meta["git"] == plugin_cfg["git"]
    assert meta["branch"] == "main"
    # ISO-8601 UTC string ends with `+00:00` for `datetime.now(timezone.utc)`.
    assert meta["last_synced"].endswith("+00:00")


def test_sync_plugin_does_not_record_metadata_on_clone_failure(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    plugin_cfg: dict,
) -> None:
    # If clone_or_update raises, the per-plugin run did not complete and the
    # `_plugins` metadata must NOT be written - timestamps must reflect real
    # successful syncs only.
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("clone exploded")

    monkeypatch.setattr(core, "clone_or_update", boom)
    manifest: dict[str, dict] = {}

    with pytest.raises(RuntimeError):
        sync_plugin(plugin_cfg, hermes_home, manifest)

    assert "_plugins" not in manifest


def test_sync_plugin_with_subdir(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    sample_plugin_src: Path,
) -> None:
    # Gap coverage: plugin_cfg with a non-empty `subdir` field. Stage the
    # fixture under <repo>/<subdir>/ to confirm the subdir is honored.
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)

    repo = hermes_home / "plugins" / "subdir-plugin"
    nested = repo / "nested" / "path"
    nested.parent.mkdir(parents=True)
    shutil.copytree(sample_plugin_src, nested)
    (repo / ".git").mkdir()

    cfg = {
        "name": "subdir-plugin",
        "git": "https://example.invalid/x.git",
        "branch": "main",
        "subdir": "nested/path",
    }
    manifest: dict[str, dict] = {}
    sync_plugin(cfg, hermes_home, manifest)

    assert (hermes_home / "skills" / "subdir-plugin" / "hello-skill" / "SKILL.md").exists()


def test_sync_plugin_warns_on_zero_migrations(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A plugin with no skills/ or agents/ at the configured root must WARN.

    This is the ``subdir:`` misconfiguration footgun: silently succeeding
    with zero migrations looks like a successful sync but leaves the user
    staring at an empty tree wondering why. Surface it as a warning, with
    the searched paths included so the fix is obvious.
    """
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)

    # Stage a repo that looks superficially like a plugin but has no
    # skills/ or agents/ at its root — e.g. a monorepo where the real
    # plugin tree lives under plugins/<name>/.
    repo = hermes_home / "plugins" / "empty-root"
    (repo / "plugins" / "empty-root").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("monorepo, see plugins/")

    cfg = {
        "name": "empty-root",
        "git": "https://example.invalid/x.git",
        "branch": "main",
    }
    manifest: dict[str, dict] = {}
    with caplog.at_level(logging.WARNING, logger="hermetic.core"):
        sync_plugin(cfg, hermes_home, manifest)

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("migrated 0 skills/agents" in m and "subdir" in m for m in messages), (
        f"expected zero-migration warning, got: {messages}"
    )
