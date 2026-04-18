# Changelog

All notable changes to `hermetic` (published on PyPI as `hermetic-cli`) will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches 1.0; pre-1.0 minor versions may include breaking changes.

## [Unreleased]

## [0.1.0] - 2026-04-18

First public release. Extracts and packages the Claude Code → Hermes plugin
migrator that previously lived as a bespoke script in a deployment repo.

### Added

- **Package scaffold**: `pyproject.toml` with hatchling backend, `src/` layout,
  Python ≥ 3.10, MIT license. Published on PyPI as `hermetic-cli`; CLI is `hermetic`.
- **Core migrator** (`hermetic.core`) decomposed into testable modules
  (`manifest`, `frontmatter`, `tools`, `git`, `core`). Every public function takes
  `hermes_home: Path` explicitly — no module-level path constants.
- **Public API** exports `sync_plugin`, `load_manifest`, `save_manifest` for
  future upstream embedding into `hermes-agent`.
- **CLI** with four subcommands:
  - `sync --config PATH` — clone/update plugins and migrate; continue-on-error
    per plugin with exit 1 on any failure.
  - `list [--json]` — table or JSON array of installed plugins.
  - `inspect <plugin> [--json]` — manifest entries for one plugin.
  - `clear <plugin> [--yes]` — remove skill tree and metadata for one plugin.
  - Global flags: `--hermes-home`, `--log-level`, `--version`. Path resolution
    precedence: `--hermes-home` > `$HERMES_HOME` > `~/.hermes/`.
- **`subdir:` config field** for monorepo plugins (e.g. EveryInc's
  `compound-engineering-plugin`, where the real plugin tree lives under
  `plugins/<name>/`).
- **Zero-migration warning** — `sync` logs a WARNING with the searched paths
  and a `subdir:` suggestion when a plugin produces 0 skills/agents. Silent
  no-op syncs were the #1 real-world UX trap.
- **Manifest metadata**: reserved `_plugins` top-level key in
  `.plugin_sync_manifest.json` records `{git, branch, last_synced}` per plugin.
  Older manifests without this key load gracefully. Helpers
  `manifest.entries_for_plugin` and constant `manifest.META_KEY` make the
  schema explicit.
- **84-test pytest suite**: unit tests + local `file://` integration tests +
  opt-in `@pytest.mark.live` tests against a real public plugin at a pinned
  SHA. Coverage 94%, gated at 80% in CI.
- **Parity test** against a frozen snapshot of the legacy script
  (`tests/fixtures/legacy_plugin_sync_v0.py`). Byte-for-byte diff across
  single-branch and simulated branch-swap scenarios.
- **CI**: GitHub Actions matrix (Python 3.10–3.14 on Ubuntu, 3.10 + 3.14 on
  macOS). Jobs: `lint` (ruff), `typecheck` (ty), `test` (matrix pytest),
  `coverage` (80% gate). Uses `astral-sh/setup-uv@v5`.
- **PyPI publish workflow** — builds wheel + sdist on `v*.*.*` tag push and
  uploads via Trusted Publisher (OIDC, no stored tokens). Gated behind a
  `release` environment.
- **Dependabot** weekly updates for pip + github-actions, grouped per
  ecosystem. Major version bumps are ignored (handled manually).

### Fixed

- **Branch-swap bug in `clone_or_update`**: a shallow single-branch clone
  (`git clone --depth=1 --branch X`) only tracks `origin/X`, so a subsequent
  `git fetch origin Y` + `git reset --hard origin/Y` failed with
  `ambiguous argument 'origin/Y'`. Now resets against `FETCH_HEAD`, which is
  always written by the fetch regardless of refspec. Surfaced by integration
  test coverage; inherited from the legacy script.

### Project tooling

- **Typechecker**: `ty` (Astral, pre-1.0) replacing `mypy`. Strict bar via
  `[tool.ty.terminal] error-on-warning = true`.
- **Formatter/linter**: `ruff` (check + format) with E/F/W/I/B/UP/SIM rule set.
- **Build/install**: `uv` throughout (local dev and CI).

[Unreleased]: https://github.com/roach88/hermetic/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/roach88/hermetic/releases/tag/v0.1.0
