"""Shared pytest fixtures for hermes-plugin-sync tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_plugin_src() -> Path:
    """Path to the checked-in sample plugin tree."""
    return FIXTURES / "sample_plugin"


@pytest.fixture
def hermes_home(tmp_path: Path) -> Path:
    """A throw-away Hermes home directory rooted in tmp_path."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    return home


@pytest.fixture
def cloned_plugin(hermes_home: Path, sample_plugin_src: Path) -> Path:
    """Pre-stage the sample plugin where ``sync_plugin`` expects a cloned repo.

    Tests use this to exercise the post-clone code paths without touching git.
    """
    dest = hermes_home / "plugins" / "sample-plugin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(sample_plugin_src, dest)
    # Drop a marker .git so clone_or_update would treat it as an existing repo
    # if anyone forgot to monkeypatch it. Tests still monkeypatch to be safe.
    (dest / ".git").mkdir()
    return dest


@pytest.fixture
def plugin_cfg() -> dict:
    return {
        "name": "sample-plugin",
        "git": "https://example.invalid/sample-plugin.git",
        "branch": "main",
    }
