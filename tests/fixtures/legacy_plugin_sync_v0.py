# Snapshot of /Users/tyler/Dev/hermes/scripts/plugin_sync.py as of 2026-04-17 - future upstream changes are deliberate compatibility decisions, not silent drift.
#!/usr/bin/env python3
"""
Claude Code → Hermes plugin migrator.

Reads plugin-sync.yaml, clones each plugin's git repo, then translates its
skills and agents into Hermes's native layout under /opt/data/skills/<plugin>/.

Idempotent via a manifest at /opt/data/skills/.plugin_sync_manifest.json.

First run (no manifest): blows away any existing /opt/data/skills/<plugin>/
directories matching the configured plugin names, then rebuilds from scratch.

Subsequent runs: compares per-skill origin hashes to decide update/skip/remove.
User-modified skills (local hash differs from last known origin hash) are
preserved; a warning is logged.
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SKILLS_DIR = Path("/opt/data/skills")
PLUGINS_DIR = Path("/opt/data/plugins")
MANIFEST = SKILLS_DIR / ".plugin_sync_manifest.json"

# Claude Code tool → Hermes toolset. Covers the common CC tools; unknowns
# are logged and dropped. Extend as plugins reveal new tools.
TOOL_MAP: Dict[str, str] = {
    "Read": "file",
    "Grep": "file",
    "Glob": "file",
    "Edit": "file",
    "Write": "file",
    "NotebookEdit": "file",
    "Bash": "terminal",
    "WebFetch": "web",
    "WebSearch": "web",
}

# Tools that map to nothing actionable in Hermes — log and skip.
TOOL_DROP = {
    "Task",  # Hermes sub-agents cannot delegate further.
}

logger = logging.getLogger("plugin_sync")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest() -> Dict[str, Dict[str, Any]]:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text())
    except json.JSONDecodeError:
        logger.warning("Manifest at %s is corrupt — treating as empty", MANIFEST)
        return {}


def save_manifest(manifest: Dict[str, Dict[str, Any]]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Hashing + frontmatter
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def render_frontmatter(fm: Dict[str, Any], body: str) -> str:
    fm_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
    return f"---\n{fm_yaml}\n---\n\n{body.lstrip()}"


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def clone_or_update(url: str, branch: str, dest: Path) -> None:
    if dest.exists() and (dest / ".git").exists():
        logger.info("Updating plugin repo at %s", dest)
        subprocess.run(["git", "-C", str(dest), "fetch", "--depth=1", "origin", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "reset", "--hard", f"origin/{branch}"], check=True)
        return
    if dest.exists():
        logger.info("Removing non-git dir at %s before clone", dest)
        shutil.rmtree(dest)
    logger.info("Cloning %s@%s → %s", url, branch, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", branch, url, str(dest)],
        check=True,
    )


# ---------------------------------------------------------------------------
# Skill migration
# ---------------------------------------------------------------------------

def migrate_skill(
    src_skill_dir: Path,
    dest_skill_dir: Path,
    manifest: Dict[str, Dict[str, Any]],
    plugin: str,
) -> None:
    src_md = src_skill_dir / "SKILL.md"
    if not src_md.exists():
        logger.debug("No SKILL.md in %s — skipping", src_skill_dir)
        return

    key = str(dest_skill_dir.relative_to(SKILLS_DIR))
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

def translate_tools(cc_tools: Any) -> Tuple[List[str], List[str]]:
    """Return (hermes_toolsets, unknown_tool_names)."""
    if not cc_tools:
        return ["file", "web"], []  # sensible default

    if isinstance(cc_tools, str):
        names = [t.strip() for t in cc_tools.split(",") if t.strip()]
    elif isinstance(cc_tools, list):
        names = [str(t).strip() for t in cc_tools]
    else:
        return ["file", "web"], []

    toolsets: List[str] = []
    unknown: List[str] = []
    for name in names:
        if name in TOOL_DROP:
            continue
        mapped = TOOL_MAP.get(name)
        if mapped:
            if mapped not in toolsets:
                toolsets.append(mapped)
        else:
            unknown.append(name)
    if not toolsets:
        toolsets = ["file", "web"]
    return toolsets, unknown


def build_delegation_skill(
    plugin: str,
    agent_name: str,
    cc_fm: Dict[str, Any],
    cc_body: str,
) -> str:
    description = cc_fm.get("description", "").strip()
    toolsets, unknown_tools = translate_tools(cc_fm.get("tools"))

    new_fm = {
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
            f"\n> ⚠️ Upstream tools not mapped to Hermes toolsets: "
            f"{', '.join(unknown_tools)}\n"
        )

    body = (
        "> 🤖 **Delegation skill** — translated from a Claude Code agent.\n"
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
    manifest: Dict[str, Dict[str, Any]],
    plugin: str,
) -> None:
    content = src_agent_md.read_text()
    cc_fm, cc_body = parse_frontmatter(content)
    agent_name = cc_fm.get("name") or src_agent_md.stem

    new_content = build_delegation_skill(plugin, agent_name, cc_fm, cc_body)

    key = str(dest_skill_dir.relative_to(SKILLS_DIR))
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
    seen_keys: set,
    manifest: Dict[str, Dict[str, Any]],
) -> None:
    """Remove dest dirs for skills no longer in upstream, if unmodified."""
    stale = [
        k for k, v in manifest.items()
        if v.get("plugin") == plugin and k not in seen_keys
    ]
    for key in stale:
        entry = manifest[key]
        dest_md = SKILLS_DIR / key / "SKILL.md"
        if dest_md.exists():
            local_hash = sha256_file(dest_md)
            if local_hash != entry["origin_hash"]:
                logger.warning("KEEP (user-modified, upstream removed): %s", key)
                continue
            dest_dir = SKILLS_DIR / key
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            logger.info("REMOVE (upstream deleted): %s", key)
        manifest.pop(key, None)


# ---------------------------------------------------------------------------
# Plugin processing
# ---------------------------------------------------------------------------

def sync_plugin(plugin_cfg: Dict[str, Any], manifest: Dict[str, Dict[str, Any]]) -> None:
    plugin = plugin_cfg["name"]
    repo_dir = PLUGINS_DIR / plugin
    clone_or_update(plugin_cfg["git"], plugin_cfg.get("branch", "main"), repo_dir)

    # Plugin's skills/agents live at <repo>/<subdir>/skills and <repo>/<subdir>/agents
    plugin_root = repo_dir / plugin_cfg.get("subdir", "")
    skills_src = plugin_root / "skills"
    agents_src = plugin_root / "agents"

    plugin_dest = SKILLS_DIR / plugin
    plugin_dest.mkdir(parents=True, exist_ok=True)

    seen_keys: set = set()

    # Skills: skills/<name>/SKILL.md → /opt/data/skills/<plugin>/<name>/SKILL.md
    if skills_src.is_dir():
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue
            dest = plugin_dest / skill_dir.name
            migrate_skill(skill_dir, dest, manifest, plugin)
            seen_keys.add(str(dest.relative_to(SKILLS_DIR)))

    # Agents: agents/<category>/<agent>.md → /opt/data/skills/<plugin>/agents/<agent>/SKILL.md
    if agents_src.is_dir():
        agents_dest_root = plugin_dest / "agents"
        agents_dest_root.mkdir(parents=True, exist_ok=True)
        for agent_md in sorted(agents_src.rglob("*.md")):
            agent_name = agent_md.stem
            dest = agents_dest_root / agent_name
            migrate_agent(agent_md, dest, manifest, plugin)
            seen_keys.add(str(dest.relative_to(SKILLS_DIR)))

    prune_removed(plugin, seen_keys, manifest)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Code plugin → Hermes skill migrator")
    parser.add_argument("--config", type=Path, required=True, help="Path to plugin-sync.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = yaml.safe_load(args.config.read_text()) or {}
    plugins = cfg.get("plugins") or []
    if not plugins:
        logger.info("No plugins configured — nothing to do")
        return 0

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    first_run = not MANIFEST.exists()
    if first_run:
        logger.info("First run detected (no manifest) — blowing away existing plugin skill dirs")
        for p in plugins:
            target = SKILLS_DIR / p["name"]
            if target.exists():
                shutil.rmtree(target)
                logger.info("WIPE: %s", target)

    manifest = load_manifest()
    for plugin_cfg in plugins:
        try:
            sync_plugin(plugin_cfg, manifest)
        except subprocess.CalledProcessError as exc:
            logger.error("Git failure for plugin %s: %s", plugin_cfg.get("name"), exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected failure for plugin %s: %s", plugin_cfg.get("name"), exc)

    save_manifest(manifest)
    logger.info("Sync complete — manifest at %s (%d entries)", MANIFEST, len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
