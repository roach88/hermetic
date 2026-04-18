"""Tests for ``hermetic.manifest``."""

from __future__ import annotations

from pathlib import Path

from hermetic.manifest import (
    load_manifest,
    manifest_path,
    save_manifest,
)


def test_manifest_path_is_under_skills(hermes_home: Path) -> None:
    p = manifest_path(hermes_home)
    assert p == hermes_home / "skills" / ".plugin_sync_manifest.json"


def test_load_missing_manifest_returns_empty(hermes_home: Path) -> None:
    assert load_manifest(hermes_home) == {}


def test_empty_manifest_roundtrip(hermes_home: Path) -> None:
    save_manifest(hermes_home, {})
    assert load_manifest(hermes_home) == {}


def test_populated_manifest_roundtrip(hermes_home: Path) -> None:
    payload = {
        "sample-plugin/foo": {
            "plugin": "sample-plugin",
            "kind": "skill",
            "source_path": "/tmp/x",
            "origin_hash": "abc123",
        },
        "sample-plugin/agents/bar": {
            "plugin": "sample-plugin",
            "kind": "agent",
            "source_path": "/tmp/y",
            "origin_hash": "def456",
        },
    }
    save_manifest(hermes_home, payload)
    assert load_manifest(hermes_home) == payload


def test_corrupt_manifest_returns_empty_and_warns(hermes_home: Path, caplog) -> None:
    path = manifest_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    import logging

    with caplog.at_level(logging.WARNING, logger="hermetic.manifest"):
        result = load_manifest(hermes_home)
    assert result == {}
    assert any("corrupt" in rec.message.lower() for rec in caplog.records)


def test_non_object_manifest_returns_empty(hermes_home: Path) -> None:
    # Gap coverage: a JSON value that parses but isn't a dict (e.g. a list)
    # should be rejected, not crash callers that index into it.
    path = manifest_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]")
    assert load_manifest(hermes_home) == {}


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    home = tmp_path / "deeply" / "nested" / "home"
    save_manifest(home, {"x": {"plugin": "p", "kind": "skill"}})
    assert manifest_path(home).exists()
