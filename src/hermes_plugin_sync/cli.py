"""Command-line interface for hermes-plugin-sync.

Thin wrapper over ``core.sync_plugin`` plus three read/maintenance commands
(``list``, ``inspect``, ``clear``). The CLI owns:

* Path resolution: ``--hermes-home`` flag > ``HERMES_HOME`` env >
  ``~/.hermes``. Resolved once in ``main`` and passed down explicitly.
* Logging setup: a single ``logging.basicConfig`` call, here. Library code
  (``core``, ``manifest``, ``git``) never touches root logger config.
* Exit semantics (continue-on-error): ``sync`` runs every plugin even if some
  fail; final exit code is 1 if any failed, 0 otherwise. The end-of-run
  summary line documents the count.
* Manifest schema awareness: reads ``manifest[META_KEY]`` for plugin
  metadata; treats absence as "not recorded" (for forward-compat with
  pre-Unit-3 manifests).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from . import core
from .manifest import (
    META_KEY,
    entries_for_plugin,
    load_manifest,
    manifest_path,
    save_manifest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_hermes_home(flag_value: str | None) -> Path:
    """Resolve hermes_home from CLI flag, env var, or default.

    Precedence: ``--hermes-home`` (highest) > ``HERMES_HOME`` env >
    ``~/.hermes`` (default). We do NOT validate existence here so commands
    like ``list`` against a fresh path can succeed by reporting "no plugins".
    """
    if flag_value:
        return Path(flag_value).expanduser()
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".hermes"


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def _cmd_sync(args: argparse.Namespace, hermes_home: Path) -> int:
    """Loop over configured plugins. Continue-on-error per plugin (D2=A)."""
    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"error: config file not found: {config_path}", file=sys.stderr)
        return 2
    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        print(f"error: failed to parse {config_path}: {exc}", file=sys.stderr)
        return 2

    if raw is None:
        plugins: list[dict[str, Any]] = []
    elif isinstance(raw, list):
        plugins = raw
    elif isinstance(raw, dict) and isinstance(raw.get("plugins"), list):
        plugins = raw["plugins"]
    else:
        print(
            f"error: {config_path}: expected a list of plugins or a mapping "
            "with a 'plugins' key",
            file=sys.stderr,
        )
        return 2

    manifest = load_manifest(hermes_home)
    total = len(plugins)
    errors = 0
    for cfg in plugins:
        name = cfg.get("name", "<unnamed>") if isinstance(cfg, dict) else "<invalid>"
        try:
            if not isinstance(cfg, dict) or "name" not in cfg or "git" not in cfg:
                raise ValueError(
                    f"plugin entry missing required 'name' or 'git' field: {cfg!r}"
                )
            logger.info("Syncing plugin: %s", name)
            core.sync_plugin(cfg, hermes_home, manifest)
        except Exception as exc:
            errors += 1
            logger.error("Plugin %s failed: %s", name, exc)

    save_manifest(hermes_home, manifest)
    succeeded = total - errors
    logger.info(
        "Synced %d/%d plugins (%d errors); manifest at %s",
        succeeded,
        total,
        errors,
        manifest_path(hermes_home),
    )
    return 1 if errors else 0


def _aggregate_plugin_view(
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the per-plugin view used by ``list`` (text + JSON).

    Combines counts derived from per-entry rows with metadata from the
    ``META_KEY`` block. Plugins that appear in entries but have no metadata
    (legacy manifest) get null git/branch/last_synced. Plugins that appear in
    metadata but have no entries (e.g. all skills user-deleted) still show up
    with zero counts so the operator can see them.
    """
    counts: dict[str, dict[str, int]] = {}
    for key, value in manifest.items():
        if key == META_KEY or not isinstance(value, dict):
            continue
        plugin = value.get("plugin")
        kind = value.get("kind")
        if not isinstance(plugin, str):
            continue
        bucket = counts.setdefault(plugin, {"skill": 0, "agent": 0})
        if kind in bucket:
            bucket[kind] += 1

    meta_block = manifest.get(META_KEY) if isinstance(manifest.get(META_KEY), dict) else {}
    all_names = sorted(set(counts) | set(meta_block or {}))
    rows: list[dict[str, Any]] = []
    for name in all_names:
        c = counts.get(name, {"skill": 0, "agent": 0})
        meta = (meta_block or {}).get(name) or {}
        rows.append({
            "name": name,
            "skill_count": c["skill"],
            "agent_count": c["agent"],
            "last_synced": meta.get("last_synced"),
            "git": meta.get("git"),
            "branch": meta.get("branch"),
        })
    return rows


def _cmd_list(args: argparse.Namespace, hermes_home: Path) -> int:
    manifest = load_manifest(hermes_home)
    rows = _aggregate_plugin_view(manifest)

    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if not rows:
        print("No plugins installed.")
        return 0

    # Simple aligned table - no third-party deps.
    headers = ("PLUGIN", "SKILLS", "AGENTS", "LAST SYNCED")
    body = [
        (
            r["name"],
            str(r["skill_count"]),
            str(r["agent_count"]),
            r["last_synced"] or "-",
        )
        for r in rows
    ]
    widths = [max(len(h), *(len(row[i]) for row in body)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for row in body:
        print(fmt.format(*row))
    return 0


def _cmd_inspect(args: argparse.Namespace, hermes_home: Path) -> int:
    manifest = load_manifest(hermes_home)
    plugin = args.plugin

    entries = entries_for_plugin(manifest, plugin)
    meta_block = manifest.get(META_KEY) if isinstance(manifest.get(META_KEY), dict) else {}
    meta = (meta_block or {}).get(plugin)

    if not entries and not meta:
        installed_set: set[str] = set()
        for k, v in manifest.items():
            if k == META_KEY or not isinstance(v, dict):
                continue
            p = v.get("plugin")
            if isinstance(p, str):
                installed_set.add(p)
        if isinstance(meta_block, dict):
            installed_set.update(str(name) for name in meta_block)
        installed = sorted(installed_set)
        if args.json:
            # JSON-on-stdout-with-nonzero-exit (documented choice): keeps the
            # stdout stream parseable even on errors, matching how most JSON
            # CLIs behave (e.g. `gh ... --json`).
            print(json.dumps(
                {"error": "plugin not found", "installed": installed},
                indent=2,
                sort_keys=True,
            ))
        else:
            print(f"error: plugin not found: {plugin}", file=sys.stderr)
            if installed:
                print(f"installed: {', '.join(installed)}", file=sys.stderr)
            else:
                print("no plugins installed", file=sys.stderr)
        return 1

    skills_dir = hermes_home / "skills"
    entry_list = []
    for key in sorted(entries):
        e = entries[key]
        entry_list.append({
            "key": key,
            "kind": e.get("kind"),
            "origin_hash": e.get("origin_hash"),
            "source_path": e.get("source_path"),
            "dest_path": str(skills_dir / key),
        })

    payload = {
        "name": plugin,
        "git": (meta or {}).get("git"),
        "branch": (meta or {}).get("branch"),
        "last_synced": (meta or {}).get("last_synced"),
        "entries": entry_list,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Plugin: {plugin}")
    print(f"  git:          {payload['git'] or '-'}")
    print(f"  branch:       {payload['branch'] or '-'}")
    print(f"  last_synced:  {payload['last_synced'] or '-'}")
    print(f"  entries:      {len(entry_list)}")
    for e in entry_list:
        print(f"    - [{e['kind']}] {e['key']}")
        print(f"        origin_hash: {e['origin_hash']}")
        print(f"        source:      {e['source_path']}")
        print(f"        dest:        {e['dest_path']}")
    return 0


def _cmd_clear(args: argparse.Namespace, hermes_home: Path) -> int:
    plugin = args.plugin
    manifest = load_manifest(hermes_home)
    entries = entries_for_plugin(manifest, plugin)
    meta_block = manifest.get(META_KEY) if isinstance(manifest.get(META_KEY), dict) else {}
    has_meta = isinstance(meta_block, dict) and plugin in meta_block

    if not entries and not has_meta:
        # Idempotent: clearing an already-clean plugin is fine.
        print(f"Plugin {plugin!r} is not installed; nothing to do.")
        return 0

    if not args.yes:
        prompt = (
            f"Remove {len(entries)} entries and the skills tree under "
            f"{hermes_home / 'skills' / plugin}? [y/N]: "
        )
        try:
            answer = input(prompt)
        except EOFError:
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            print("Aborted; no changes.")
            return 0

    plugin_skills_dir = hermes_home / "skills" / plugin
    if plugin_skills_dir.exists():
        shutil.rmtree(plugin_skills_dir)

    for key in list(entries):
        manifest.pop(key, None)
    if isinstance(meta_block, dict):
        meta_block.pop(plugin, None)

    save_manifest(hermes_home, manifest)
    print(f"Cleared plugin {plugin!r}.")
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    # Global flags live on a parent parser so they work BOTH before and after
    # the subcommand (e.g. `--hermes-home X list` and `list --hermes-home X`).
    # `default=SUPPRESS` is critical: without it, the subparser's parsed copy
    # would overwrite a value the top-level parser already captured, because
    # both namespaces merge and the subparser writes last. With SUPPRESS, an
    # unspecified flag is omitted entirely - the top-level value wins by
    # being there first. We use `set_defaults` on the top parser to seed the
    # baseline values once.
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--hermes-home",
        default=argparse.SUPPRESS,
        help="Hermes home directory. Overrides $HERMES_HOME (default: ~/.hermes).",
    )
    parent.add_argument(
        "--log-level",
        default=argparse.SUPPRESS,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO).",
    )

    parser = argparse.ArgumentParser(
        prog="hermes-plugin-sync",
        description="Sync Claude Code plugins into Hermes.",
        parents=[parent],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="cmd", metavar="{sync,list,inspect,clear}")
    sub.required = True

    p_sync = sub.add_parser(
        "sync",
        parents=[parent],
        help="Clone/update plugins and sync into Hermes.",
    )
    p_sync.add_argument(
        "--config",
        required=True,
        help="Path to plugin-sync.yaml.",
    )
    p_sync.set_defaults(func=_cmd_sync)

    p_list = sub.add_parser(
        "list",
        parents=[parent],
        help="List installed plugins.",
    )
    p_list.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    p_list.set_defaults(func=_cmd_list)

    p_inspect = sub.add_parser(
        "inspect",
        parents=[parent],
        help="Show details for one plugin.",
    )
    p_inspect.add_argument("plugin", help="Plugin name.")
    p_inspect.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    p_inspect.set_defaults(func=_cmd_inspect)

    p_clear = sub.add_parser(
        "clear",
        parents=[parent],
        help="Remove a plugin's skills + manifest entries.",
    )
    p_clear.add_argument("plugin", help="Plugin name.")
    p_clear.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    p_clear.set_defaults(func=_cmd_clear)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # We use argparse.SUPPRESS on the global flags so they don't get clobbered
    # when both the top-level and subparser see them, which means the attr is
    # absent (not None) when unset. getattr with a default handles both.
    log_level = getattr(args, "log_level", "INFO")
    hermes_home_flag = getattr(args, "hermes_home", None)

    # Single basicConfig call lives here, never in library code.
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    hermes_home = _resolve_hermes_home(hermes_home_flag)
    func = args.func
    return int(func(args, hermes_home))
