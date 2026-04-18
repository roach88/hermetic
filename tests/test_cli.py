"""Tests for ``hermes_plugin_sync.cli``.

We exercise ``cli.main(argv)`` directly rather than shelling out so failures
surface as Python tracebacks and ``capsys``/``caplog`` work cleanly.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest

from hermes_plugin_sync import cli, core
from hermes_plugin_sync.manifest import load_manifest, save_manifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(path: Path, plugins: list[dict[str, Any]]) -> Path:
    import yaml

    path.write_text(yaml.safe_dump(plugins))
    return path


def _no_op_clone(*args: object, **kwargs: object) -> None:
    return None


def _seed_manifest(hermes_home: Path, manifest: dict[str, Any]) -> None:
    save_manifest(hermes_home, manifest)


# ---------------------------------------------------------------------------
# --version, --help
# ---------------------------------------------------------------------------


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "0.1.0" in out


def test_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for sub in ("sync", "list", "inspect", "clear"):
        assert sub in out


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def test_sync_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    cfg = _write_config(tmp_path / "plugin-sync.yaml", [plugin_cfg])

    with caplog.at_level(logging.INFO, logger="hermes_plugin_sync.cli"):
        rc = cli.main(["--hermes-home", str(hermes_home), "sync", "--config", str(cfg)])

    assert rc == 0
    assert (hermes_home / "skills" / "sample-plugin" / "hello-skill" / "SKILL.md").exists()
    # End-of-sync summary line is mandatory (D2=A).
    assert any(
        "Synced 1/1 plugins" in rec.message and "errors" in rec.message for rec in caplog.records
    ), [rec.message for rec in caplog.records]


def test_sync_missing_config(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    tmp_path: Path,
) -> None:
    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "sync",
            "--config",
            str(tmp_path / "nope.yaml"),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "config file not found" in err


def test_sync_malformed_yaml(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(":\n  - this is not valid yaml: [")
    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "sync",
            "--config",
            str(bad),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "failed to parse" in err or "expected" in err


def test_sync_continues_on_error_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes_home: Path,
    sample_plugin_src: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Stage two plugins on disk; the first will be made to raise via a
    # selective clone_or_update, the second succeeds. Final exit must be 1
    # but the second plugin's skills must still land + manifest must save.
    for name in ("bad-plugin", "good-plugin"):
        repo = hermes_home / "plugins" / name
        repo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(sample_plugin_src, repo)
        (repo / ".git").mkdir()

    def selective_clone(url: str, branch: str, dest: Path) -> None:
        if dest.name == "bad-plugin":
            raise RuntimeError("simulated clone failure")
        return None

    monkeypatch.setattr(core, "clone_or_update", selective_clone)

    cfg = _write_config(
        tmp_path / "plugin-sync.yaml",
        [
            {"name": "bad-plugin", "git": "https://example.invalid/bad.git", "branch": "main"},
            {"name": "good-plugin", "git": "https://example.invalid/good.git", "branch": "main"},
        ],
    )

    with caplog.at_level(logging.INFO, logger="hermes_plugin_sync.cli"):
        rc = cli.main(["--hermes-home", str(hermes_home), "sync", "--config", str(cfg)])

    assert rc == 1
    # Good plugin completed.
    assert (hermes_home / "skills" / "good-plugin" / "hello-skill" / "SKILL.md").exists()
    # Manifest persisted with good-plugin entries + meta.
    manifest = load_manifest(hermes_home)
    assert "good-plugin/hello-skill" in manifest
    assert "_plugins" in manifest and "good-plugin" in manifest["_plugins"]
    # Summary line shows 1/2 succeeded, 1 error.
    assert any("Synced 1/2 plugins (1 errors)" in r.message for r in caplog.records)


def test_sync_empty_config_yields_zero_total(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes_home: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Gap coverage: empty plugin list - nothing to sync, exit 0, no crash.
    cfg = _write_config(tmp_path / "plugin-sync.yaml", [])
    with caplog.at_level(logging.INFO, logger="hermes_plugin_sync.cli"):
        rc = cli.main(["--hermes-home", str(hermes_home), "sync", "--config", str(cfg)])
    assert rc == 0
    assert any("Synced 0/0 plugins" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
) -> None:
    rc = cli.main(["--hermes-home", str(hermes_home), "list"])
    assert rc == 0
    assert "No plugins installed." in capsys.readouterr().out


def test_list_populated_text_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)

    rc = cli.main(["--hermes-home", str(hermes_home), "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PLUGIN" in out and "SKILLS" in out and "AGENTS" in out
    assert "sample-plugin" in out
    # Two skills, two agents in the fixture.
    assert "2" in out


def test_list_json_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)

    rc = cli.main(["--hermes-home", str(hermes_home), "list", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 1
    row = payload[0]
    assert row["name"] == "sample-plugin"
    assert row["skill_count"] == 2
    assert row["agent_count"] == 2
    assert row["git"] == plugin_cfg["git"]
    assert row["branch"] == "main"
    assert isinstance(row["last_synced"], str)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def test_inspect_happy_path_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)

    rc = cli.main(["--hermes-home", str(hermes_home), "inspect", "sample-plugin"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sample-plugin" in out
    assert "hello-skill" in out
    assert "refactorer" in out
    assert plugin_cfg["git"] in out


def test_inspect_json_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)

    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "inspect",
            "sample-plugin",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "sample-plugin"
    assert payload["git"] == plugin_cfg["git"]
    assert payload["branch"] == "main"
    assert isinstance(payload["last_synced"], str)
    assert isinstance(payload["entries"], list)
    keys = [e["key"] for e in payload["entries"]]
    # Entries sorted by key.
    assert keys == sorted(keys)
    for e in payload["entries"]:
        assert {"key", "kind", "origin_hash", "source_path", "dest_path"} <= set(e)
        assert e["kind"] in {"skill", "agent"}


def test_inspect_unknown_plugin_text(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
) -> None:
    # Manifest is empty; inspecting nonexistent plugin.
    rc = cli.main(["--hermes-home", str(hermes_home), "inspect", "ghost"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "plugin not found" in err
    assert "no plugins installed" in err


def test_inspect_unknown_plugin_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    # Seed one real plugin so `installed` is non-empty.
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)

    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "inspect",
            "ghost",
            "--json",
        ]
    )
    # Documented choice: JSON-on-stdout-with-nonzero-exit.
    assert rc != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "plugin not found"
    assert "sample-plugin" in payload["installed"]


def test_inspect_on_empty_hermes_home_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
) -> None:
    # Gap coverage: inspect against a hermes_home with no manifest at all.
    rc = cli.main(["--hermes-home", str(hermes_home), "inspect", "anything"])
    assert rc != 0


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_with_yes_removes_skills_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)
    plugin_dest = hermes_home / "skills" / "sample-plugin"
    assert plugin_dest.exists()

    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "clear",
            "sample-plugin",
            "--yes",
        ]
    )
    assert rc == 0
    assert not plugin_dest.exists()

    # Manifest entries gone, including the `_plugins` row for this plugin.
    after = load_manifest(hermes_home)
    assert "sample-plugin/hello-skill" not in after
    assert "sample-plugin" not in after.get("_plugins", {})

    # `list` no longer shows it.
    capsys.readouterr()  # drain
    rc = cli.main(["--hermes-home", str(hermes_home), "list"])
    assert rc == 0
    assert "No plugins installed." in capsys.readouterr().out


def test_clear_without_yes_aborts_on_decline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)
    plugin_dest = hermes_home / "skills" / "sample-plugin"

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = cli.main(["--hermes-home", str(hermes_home), "clear", "sample-plugin"])
    assert rc == 0
    assert plugin_dest.exists()  # untouched
    out = capsys.readouterr().out
    assert "Aborted" in out


def test_clear_without_yes_proceeds_on_accept(
    monkeypatch: pytest.MonkeyPatch,
    hermes_home: Path,
    cloned_plugin: Path,
    plugin_cfg: dict,
) -> None:
    monkeypatch.setattr(core, "clone_or_update", _no_op_clone)
    manifest: dict[str, dict] = {}
    core.sync_plugin(plugin_cfg, hermes_home, manifest)
    save_manifest(hermes_home, manifest)
    plugin_dest = hermes_home / "skills" / "sample-plugin"

    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    rc = cli.main(["--hermes-home", str(hermes_home), "clear", "sample-plugin"])
    assert rc == 0
    assert not plugin_dest.exists()


def test_clear_idempotent_for_unknown_plugin(
    capsys: pytest.CaptureFixture[str],
    hermes_home: Path,
) -> None:
    rc = cli.main(
        [
            "--hermes-home",
            str(hermes_home),
            "clear",
            "ghost",
            "--yes",
        ]
    )
    assert rc == 0
    assert "not installed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Hermes home resolution
# ---------------------------------------------------------------------------


def test_env_var_override(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    home = tmp_path / "env-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    rc = cli.main(["list"])
    assert rc == 0
    assert "No plugins installed." in capsys.readouterr().out
    # Resolution helper should mirror the env var.
    assert cli._resolve_hermes_home(None) == home


def test_flag_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_home = tmp_path / "env-home"
    flag_home = tmp_path / "flag-home"
    env_home.mkdir()
    flag_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    assert cli._resolve_hermes_home(str(flag_home)) == flag_home


def test_default_when_no_flag_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert cli._resolve_hermes_home(None) == Path.home() / ".hermes"


def test_list_against_nonexistent_hermes_home(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Gap coverage: --hermes-home pointing at a path that doesn't exist
    # should not crash; `list` should report empty.
    nope = tmp_path / "does-not-exist"
    rc = cli.main(["--hermes-home", str(nope), "list"])
    assert rc == 0
    assert "No plugins installed." in capsys.readouterr().out
