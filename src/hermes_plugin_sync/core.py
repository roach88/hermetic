"""Core sync orchestration: skill copy, agent translation, prune, top-level loop.

Every function takes ``hermes_home: Path`` explicitly. There are no module-
level path constants - this is the primary shape change from the source
script. Callers (CLI, tests, eventual upstream embedder) own path resolution.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    sha256_bytes,
    sha256_file,
)
from .git import clone_or_update
from .tools import translate_tools

logger = logging.getLogger(__name__)


def _skills_dir(hermes_home: Path) -> Path:
    return hermes_home / "skills"


def _plugins_dir(hermes_home: Path) -> Path:
    return hermes_home / "plugins"


# ---------------------------------------------------------------------------
# Skill migration
# ---------------------------------------------------------------------------

def migrate_skill(
    src_skill_dir: Path,
    dest_skill_dir: Path,
    manifest: dict[str, dict[str, Any]],
    plugin: str,
    hermes_home: Path,
) -> None:
    """Copy a single Claude Code skill into the Hermes layout, idempotently.

    Preserves user modifications: if the on-disk SKILL.md hash differs from
    both the recorded origin hash and the new origin hash, the file is left
    untouched and a warning is logged. Matches source script byte-for-byte.
    """
    src_md = src_skill_dir / "SKILL.md"
    if not src_md.exists():
        logger.debug("No SKILL.md in %s - skipping", src_skill_dir)
        return

    skills_dir = _skills_dir(hermes_home)
    key = str(dest_skill_dir.relative_to(skills_dir))
    origin_hash = sha256_file(src_md)
    entry = manifest.get(key)
    dest_md = dest_skill_dir / "SKILL.md"

    if dest_md.exists() and entry:
        local_hash = sha256_file(dest_md)
        if local_hash != entry["origin_hash"] and local_hash != origin_hash:
            logger.warning("SKIP (user-modified): %s", key)
            return
        if local_hash == origin_hash:
            logger.debug("UNCHANGED: %s", key)
            manifest[key] = {
                "plugin": plugin,
                "kind": "skill",
                "source_path": str(src_skill_dir),
                "origin_hash": origin_hash,
            }
            return

    if dest_skill_dir.exists():
        shutil.rmtree(dest_skill_dir)
    shutil.copytree(src_skill_dir, dest_skill_dir)
    manifest[key] = {
        "plugin": plugin,
        "kind": "skill",
        "source_path": str(src_skill_dir),
        "origin_hash": origin_hash,
    }
    logger.info("COPY skill: %s", key)


# ---------------------------------------------------------------------------
# Agent translation (Claude Code agent → Hermes delegation skill)
# ---------------------------------------------------------------------------

def build_delegation_skill(
    plugin: str,
    agent_name: str,
    cc_fm: dict[str, Any],
    cc_body: str,
) -> str:
    """Produce a SKILL.md string that wraps a CC agent as a Hermes delegation.

    The output format must match the source script verbatim - this is the
    public artifact users will edit and that downstream Hermes consumes.
    """
    description = str(cc_fm.get("description", "")).strip()
    toolsets, unknown_tools = translate_tools(cc_fm.get("tools"))

    new_fm: dict[str, Any] = {
        "name": f"{plugin}/agent/{agent_name}",
        "description": description or f"Delegate to the {agent_name} sub-agent persona.",
        "version": "1.0.0",
        "metadata": {
            "hermes": {
                "source": plugin,
                "source_kind": "agent",
                "upstream_name": agent_name,
                "toolsets": toolsets,
            }
        },
    }

    unknown_note = ""
    if unknown_tools:
        unknown_note = (
            f"\n> \u26a0\ufe0f Upstream tools not mapped to Hermes toolsets: "
            f"{', '.join(unknown_tools)}\n"
        )

    body = (
        "> \U0001f916 **Delegation skill** \u2014 translated from a Claude Code agent.\n"
        "> When this skill matches, invoke `delegate_task` with:\n"
        f"> - `toolsets`: {toolsets}\n"
        "> - `context`: the persona text below, verbatim\n"
        "> - `goal`: restate the user's ask from this persona's perspective\n"
        "> - `max_iterations`: 30\n"
        f"{unknown_note}\n"
        "## Persona\n\n"
        f"{cc_body.lstrip()}"
    )
    return render_frontmatter(new_fm, body)


def migrate_agent(
    src_agent_md: Path,
    dest_skill_dir: Path,
    manifest: dict[str, dict[str, Any]],
    plugin: str,
    hermes_home: Path,
) -> None:
    """Translate a CC agent file into a Hermes delegation skill, idempotently."""
    content = src_agent_md.read_text()
    cc_fm, cc_body = parse_frontmatter(content)
    agent_name = cc_fm.get("name") or src_agent_md.stem

    new_content = build_delegation_skill(plugin, agent_name, cc_fm, cc_body)

    skills_dir = _skills_dir(hermes_home)
    key = str(dest_skill_dir.relative_to(skills_dir))
    origin_hash = sha256_bytes(new_content.encode())
    entry = manifest.get(key)
    dest_md = dest_skill_dir / "SKILL.md"

    if dest_md.exists() and entry:
        local_hash = sha256_file(dest_md)
        if local_hash != entry["origin_hash"] and local_hash != origin_hash:
            logger.warning("SKIP (user-modified agent): %s", key)
            return
        if local_hash == origin_hash:
            manifest[key] = {
                "plugin": plugin,
                "kind": "agent",
                "source_path": str(src_agent_md),
                "origin_hash": origin_hash,
            }
            return

    dest_skill_dir.mkdir(parents=True, exist_ok=True)
    dest_md.write_text(new_content)
    manifest[key] = {
        "plugin": plugin,
        "kind": "agent",
        "source_path": str(src_agent_md),
        "origin_hash": origin_hash,
    }
    logger.info("TRANSLATE agent: %s", key)


# ---------------------------------------------------------------------------
# Cleanup (removed-upstream, unmodified-local)
# ---------------------------------------------------------------------------

def prune_removed(
    plugin: str,
    seen_keys: set[str],
    manifest: dict[str, dict[str, Any]],
    hermes_home: Path,
) -> None:
    """Remove dest dirs for skills no longer in upstream, if unmodified.

    User-modified files are kept in place with a warning - upstream deletion
    must not silently destroy local work.
    """
    skills_dir = _skills_dir(hermes_home)
    stale = [
        k for k, v in manifest.items()
        if v.get("plugin") == plugin and k not in seen_keys
    ]
    for key in stale:
        entry = manifest[key]
        dest_md = skills_dir / key / "SKILL.md"
        if dest_md.exists():
            local_hash = sha256_file(dest_md)
            if local_hash != entry["origin_hash"]:
                logger.warning("KEEP (user-modified, upstream removed): %s", key)
                continue
            dest_dir = skills_dir / key
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            logger.info("REMOVE (upstream deleted): %s", key)
        manifest.pop(key, None)


# ---------------------------------------------------------------------------
# Plugin processing
# ---------------------------------------------------------------------------

def sync_plugin(
    plugin_cfg: dict[str, Any],
    hermes_home: Path,
    manifest: dict[str, dict[str, Any]],
) -> None:
    """Sync a single plugin: clone/update, migrate skills + agents, prune.

    Mutates ``manifest`` in place. Persisting it is the caller's job - this
    keeps ``sync_plugin`` cheaply re-runnable across multiple plugins in one
    pass without redundant disk writes between them.
    """
    plugin = plugin_cfg["name"]
    repo_dir = _plugins_dir(hermes_home) / plugin
    clone_or_update(plugin_cfg["git"], plugin_cfg.get("branch", "main"), repo_dir)

    # Plugin's skills/agents live at <repo>/<subdir>/skills and <repo>/<subdir>/agents
    plugin_root = repo_dir / plugin_cfg.get("subdir", "")
    skills_src = plugin_root / "skills"
    agents_src = plugin_root / "agents"

    skills_dir = _skills_dir(hermes_home)
    plugin_dest = skills_dir / plugin
    plugin_dest.mkdir(parents=True, exist_ok=True)

    seen_keys: set[str] = set()

    # Skills: skills/<name>/SKILL.md → <hermes_home>/skills/<plugin>/<name>/SKILL.md
    if skills_src.is_dir():
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue
            dest = plugin_dest / skill_dir.name
            migrate_skill(skill_dir, dest, manifest, plugin, hermes_home)
            seen_keys.add(str(dest.relative_to(skills_dir)))

    # Agents: agents/<category>/<agent>.md → <hermes_home>/skills/<plugin>/agents/<agent>/SKILL.md
    if agents_src.is_dir():
        agents_dest_root = plugin_dest / "agents"
        agents_dest_root.mkdir(parents=True, exist_ok=True)
        for agent_md in sorted(agents_src.rglob("*.md")):
            agent_name = agent_md.stem
            dest = agents_dest_root / agent_name
            migrate_agent(agent_md, dest, manifest, plugin, hermes_home)
            seen_keys.add(str(dest.relative_to(skills_dir)))

    prune_removed(plugin, seen_keys, manifest, hermes_home)
