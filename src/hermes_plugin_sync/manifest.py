"""Manifest persistence for plugin sync.

The manifest tracks every skill/agent the migrator has written to disk, keyed
by destination path relative to ``<hermes_home>/skills``. It is the source of
truth for idempotency and user-modification detection.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
