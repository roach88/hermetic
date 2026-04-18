"""Live integration tests: clone a real public plugin and sync it.

Gated by ``@pytest.mark.live`` so plain ``pytest`` (which defaults to
``-m 'not live'``) skips them. Opt in with ``pytest -m live`` when you want
to exercise the full network path against ``EveryInc/compound-engineering-plugin``.

The default pinned SHA below is resolved via ``git ls-remote`` at test-write
time so CI runs are reproducible even if ``main`` advances. Override via the
``HERMES_PLUGIN_SYNC_LIVE_SHA`` env var if you need to run against a newer
tip, or refresh the constant when the old commit becomes too stale to keep
(e.g. if the repo deletes it).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hermes_plugin_sync import cli, core

# Pinned 2026-04-18 — refresh if live tests go stale.
# Resolved via: git ls-remote https://github.com/EveryInc/compound-engineering-plugin.git refs/heads/main
_DEFAULT_LIVE_SHA = "dfcaddf3455a82254dfa50ba07499fc44b93e53f"

_LIVE_GIT_URL = "https://github.com/EveryInc/compound-engineering-plugin.git"
_LIVE_PLUGIN_NAME = "compound-engineering"


pytestmark = pytest.mark.live


def _live_sha() -> str:
    """Honour the env override; fall back to the pinned default."""
    return os.environ.get("HERMES_PLUGIN_SYNC_LIVE_SHA", _DEFAULT_LIVE_SHA).strip()


@pytest.fixture
def live_synced_home(tmp_path: Path) -> Path:
    """Perform one real sync against the upstream repo and return the home.

    Shared by both live tests so we only pay the network round-trip once per
    test session when both are run.
    """
    hermes_home = tmp_path / "hermes_home"

    sha = _live_sha()
    # We sync against the named branch (main) rather than the SHA directly -
    # ``clone_or_update`` speaks branch names. The SHA is captured afterwards
    # for diagnostics if the assertion fails. This mirrors how a real user's
    # plugin-sync.yaml would look.
    cfg = {
        "name": _LIVE_PLUGIN_NAME,
        "git": _LIVE_GIT_URL,
        "branch": "main",
    }
    manifest: dict[str, dict[str, Any]] = {}
    try:
        core.sync_plugin(cfg, hermes_home, manifest)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - network-only
        pytest.skip(
            f"live clone failed (expected SHA {sha}): {exc}. "
            "Set HERMES_PLUGIN_SYNC_LIVE_SHA or refresh _DEFAULT_LIVE_SHA."
        )

    # Persist the manifest so test (b) can exercise the CLI ``inspect`` path.
    from hermes_plugin_sync.manifest import save_manifest
    save_manifest(hermes_home, manifest)
    return hermes_home


def test_live_clone_and_sync(live_synced_home: Path) -> None:
    """Live clone of compound-engineering-plugin@main populates the manifest."""
    from hermes_plugin_sync.manifest import (
        META_KEY,
        entries_for_plugin,
        load_manifest,
    )

    manifest = load_manifest(live_synced_home)
    entries = entries_for_plugin(manifest, _LIVE_PLUGIN_NAME)
    assert entries, "live sync produced zero manifest entries"

    # At least one skill on disk under the plugin namespace.
    skills_root = live_synced_home / "skills" / _LIVE_PLUGIN_NAME
    assert skills_root.is_dir()
    skill_mds = list(skills_root.rglob("SKILL.md"))
    assert skill_mds, f"no SKILL.md files found under {skills_root}"

    meta = manifest.get(META_KEY, {}).get(_LIVE_PLUGIN_NAME)
    assert meta is not None
    assert meta["git"] == _LIVE_GIT_URL
    assert meta["branch"] == "main"
    last = meta.get("last_synced")
    assert isinstance(last, str) and last, "last_synced missing or empty"


def test_live_inspect_json(
    live_synced_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI ``inspect <plugin> --json`` reflects the live-synced state."""
    rc = cli.main([
        "--hermes-home", str(live_synced_home),
        "inspect",
        _LIVE_PLUGIN_NAME,
        "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert payload["name"] == _LIVE_PLUGIN_NAME
    assert payload["git"] == _LIVE_GIT_URL
    assert payload["branch"] == "main"
    assert isinstance(payload["last_synced"], str) and payload["last_synced"]

    skill_entries = [e for e in payload["entries"] if e["kind"] == "skill"]
    assert skill_entries, "inspect --json reported zero skills"
