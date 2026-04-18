"""Parity test: old script's outputs == new package's outputs.

The legacy script (frozen at ``tests/fixtures/legacy_plugin_sync_v0.py``) uses
hard-coded ``/opt/data/...`` paths set at import time. We import it via
``importlib`` so each test gets a fresh module, then monkeypatch its module-
level constants to point at a tmp dir. Then we run both implementations
against identical fixture inputs and diff the resulting trees + manifests.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from hermes_plugin_sync import core as new_core
from hermes_plugin_sync import sync_plugin as new_sync_plugin
from hermes_plugin_sync.manifest import load_manifest

LEGACY_PATH = Path(__file__).parent / "fixtures" / "legacy_plugin_sync_v0.py"


def _import_legacy() -> Any:
    """Import the frozen legacy script as a fresh module under a unique name."""
    name = "legacy_plugin_sync_v0_under_test"
    spec = importlib.util.spec_from_file_location(name, LEGACY_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hash_dir(root: Path) -> dict[str, str]:
    """Return a flat ``{relative_posix_path: sha256_hex}`` for every file under ``root``."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _normalize_manifest_paths(
    manifest: dict[str, dict[str, Any]],
    base: Path,
) -> dict[str, dict[str, Any]]:
    """Strip ``base`` prefix from ``source_path`` so old/new manifests can be compared.

    Old and new write the absolute path of the source skill dir into the
    manifest; that path obviously differs between the two test runs (different
    tmp roots), so we rewrite it to be relative to each run's plugins dir.
    """
    base_str = str(base)
    out: dict[str, dict[str, Any]] = {}
    for key, value in manifest.items():
        copy = dict(value)
        sp = copy.get("source_path")
        if isinstance(sp, str) and sp.startswith(base_str):
            copy["source_path"] = sp[len(base_str):].lstrip("/")
        out[key] = copy
    return out


@pytest.fixture
def fixture_plugin(tmp_path: Path) -> Path:
    """Source plugin tree to feed into both old and new implementations."""
    src = Path(__file__).parent / "fixtures" / "sample_plugin"
    staged = tmp_path / "fixture_plugin"
    shutil.copytree(src, staged)
    return staged


def test_outputs_match_old_script_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_plugin: Path,
) -> None:
    plugin_name = "sample-plugin"
    plugin_cfg = {
        "name": plugin_name,
        "git": "https://example.invalid/x.git",
        "branch": "main",
    }

    # ---------- legacy run ----------
    legacy = _import_legacy()
    old_root = tmp_path / "old"
    old_skills = old_root / "skills"
    old_plugins = old_root / "plugins"
    old_skills.mkdir(parents=True)
    old_plugins.mkdir(parents=True)

    monkeypatch.setattr(legacy, "SKILLS_DIR", old_skills)
    monkeypatch.setattr(legacy, "PLUGINS_DIR", old_plugins)
    monkeypatch.setattr(legacy, "MANIFEST", old_skills / ".plugin_sync_manifest.json")
    monkeypatch.setattr(legacy, "clone_or_update", lambda url, branch, dest: None)

    # Stage the plugin where the legacy script expects a clone.
    shutil.copytree(fixture_plugin, old_plugins / plugin_name)
    (old_plugins / plugin_name / ".git").mkdir()

    old_manifest: dict[str, dict[str, Any]] = {}
    legacy.sync_plugin(plugin_cfg, old_manifest)
    legacy.save_manifest(old_manifest)

    # ---------- new run ----------
    new_root = tmp_path / "new"
    new_skills = new_root / "skills"
    new_plugins = new_root / "plugins"
    new_skills.mkdir(parents=True)
    new_plugins.mkdir(parents=True)

    monkeypatch.setattr(new_core, "clone_or_update", lambda url, branch, dest: None)

    shutil.copytree(fixture_plugin, new_plugins / plugin_name)
    (new_plugins / plugin_name / ".git").mkdir()

    new_manifest: dict[str, dict[str, Any]] = {}
    new_sync_plugin(plugin_cfg, new_root, new_manifest)
    from hermes_plugin_sync.manifest import save_manifest

    save_manifest(new_root, new_manifest)

    # ---------- compare ----------
    # Skill tree byte-for-byte, excluding the manifest itself (compared separately).
    def _scan(root: Path) -> dict[str, str]:
        result = _hash_dir(root)
        result.pop(".plugin_sync_manifest.json", None)
        return result

    old_tree = _scan(old_skills)
    new_tree = _scan(new_skills)
    assert old_tree == new_tree, (
        f"Tree diff:\n"
        f"old-only: {sorted(set(old_tree) - set(new_tree))}\n"
        f"new-only: {sorted(set(new_tree) - set(old_tree))}\n"
        f"differing: {[k for k in old_tree if k in new_tree and old_tree[k] != new_tree[k]]}"
    )

    # Manifests equal once absolute paths are normalized.
    norm_old = _normalize_manifest_paths(old_manifest, old_plugins)
    norm_new = _normalize_manifest_paths(load_manifest(new_root), new_plugins)
    assert norm_old == norm_new


def test_legacy_module_constants_are_patchable() -> None:
    # Sanity check the import strategy - if this breaks, the parity test
    # above will fail in confusing ways. Catch it here first.
    legacy = _import_legacy()
    assert hasattr(legacy, "SKILLS_DIR")
    assert hasattr(legacy, "PLUGINS_DIR")
    assert hasattr(legacy, "MANIFEST")
    assert hasattr(legacy, "sync_plugin")
    assert hasattr(legacy, "save_manifest")


def test_legacy_header_warns_on_drift() -> None:
    # The frozen copy must carry the drift-warning header so a future
    # contributor doesn't "fix" it by re-syncing from upstream.
    text = LEGACY_PATH.read_text()
    assert "napshot of /Users/tyler/Dev/hermes/scripts/plugin_sync.py" in text
    assert "deliberate compatibility decisions" in text


def test_manifest_paths_normalized_for_comparison() -> None:
    # Document the normalization helper - if anyone changes its semantics
    # the parity test would silently start hiding drift.
    raw = {
        "k": {
            "source_path": "/tmp/abc/plugins/sample/skills/x",
            "plugin": "sample",
            "kind": "skill",
            "origin_hash": "ff",
        }
    }
    out = _normalize_manifest_paths(raw, Path("/tmp/abc/plugins"))
    assert out["k"]["source_path"] == "sample/skills/x"


def test_parse_frontmatter_parity() -> None:
    # Defensive: parse_frontmatter is the most-trafficked helper. Lock it
    # against the legacy implementation directly.
    legacy = _import_legacy()
    text = (
        "---\nname: x\ndescription: y\ntools:\n  - Read\n  - Bash\n---\n"
        "Body content here."
    )
    legacy_fm, legacy_body = legacy.parse_frontmatter(text)
    from hermes_plugin_sync.frontmatter import parse_frontmatter as new_parse

    new_fm, new_body = new_parse(text)
    assert legacy_fm == new_fm
    assert legacy_body == new_body
