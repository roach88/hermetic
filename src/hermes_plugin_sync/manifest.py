"""Manifest persistence for plugin sync.

The manifest tracks every skill/agent the migrator has written to disk, keyed
by destination path relative to ``<hermes_home>/skills``. It is the source of
truth for idempotency and user-modification detection.

Per-entry shape: ``{"plugin": str, "kind": "skill" | "agent",
"source_path": str, "origin_hash": str}``.

In addition to the per-entry rows the manifest carries one reserved top-level
key, ``META_KEY`` (``"_plugins"``), whose value is a dict mapping plugin name
to ``{"git": str, "branch": str, "last_synced": ISO8601-UTC-str}``. This is
written by ``core.sync_plugin`` at the end of a successful per-plugin run and
read by the CLI for ``list`` / ``inspect``. Old manifests that pre-date this
key still load fine - missing metadata is treated as "not recorded".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Reserved top-level manifest key for per-plugin metadata. Documented here so
# anyone hunting for the schema lands in one obvious place.
META_KEY = "_plugins"


def entries_for_plugin(
    manifest: dict[str, Any],
    plugin_name: str,
) -> dict[str, dict[str, Any]]:
    """Return the per-skill/per-agent entries belonging to ``plugin_name``.

    Filters out the reserved ``META_KEY`` row and ignores any other entries
    whose ``plugin`` field doesn't match. Returned dict is a fresh copy -
    callers can mutate without disturbing the manifest.
    """
    return {
        key: dict(value)
        for key, value in manifest.items()
        if key != META_KEY
        and isinstance(value, dict)
        and value.get("plugin") == plugin_name
    }


def manifest_path(hermes_home: Path) -> Path:
    """Return the canonical manifest location for a given Hermes home."""
    return hermes_home / "skills" / ".plugin_sync_manifest.json"


def load_manifest(hermes_home: Path) -> dict[str, dict[str, Any]]:
    """Load the manifest, returning ``{}`` if missing or corrupt.

    Corrupt JSON is logged at WARNING level and treated as an empty manifest
    so a single bad write does not block subsequent syncs from rebuilding state.
    """
    path = manifest_path(hermes_home)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Manifest at %s is corrupt - treating as empty", path)
        return {}
    if not isinstance(data, dict):
        logger.warning("Manifest at %s is not a JSON object - treating as empty", path)
        return {}
    return data


def save_manifest(hermes_home: Path, manifest: dict[str, dict[str, Any]]) -> None:
    """Write the manifest to disk, creating parent directories as needed."""
    path = manifest_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
