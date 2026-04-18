# Changelog

All notable changes to `hermes-plugin-sync` will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches 1.0; pre-1.0 minor versions may include breaking changes.

## [Unreleased]

### Added
- Initial package scaffold: `pyproject.toml` (hatchling, src layout, Python
  ≥3.10), `__version__`, MIT license, README stub, `.gitignore`,
  `tests/conftest.py` placeholder, and a minimal `cli.py` stub that responds
  to `--version`.
- Core migrator extracted from `scripts/plugin_sync.py` into testable modules
  (`manifest`, `frontmatter`, `tools`, `git`, `core`). Every public function
  takes `hermes_home: Path` explicitly — no module-level path constants.
- Public API exports `sync_plugin`, `load_manifest`, `save_manifest` from the
  top-level `hermes_plugin_sync` package for future upstream embedding.
- 50-test pytest suite covering manifest round-trip, frontmatter parsing,
  tool translation (list/comma-string/None/unknown/dropped/dedup),
  skill+agent migration, idempotency, user-modification preservation, and
  upstream-removal pruning.
- Byte-for-byte parity test against a frozen snapshot of the source script
  at `tests/fixtures/legacy_plugin_sync_v0.py`. Future drift from upstream
  is now a deliberate compatibility decision, not silent.
- `dev` extras group with `mypy>=1.10` + `types-PyYAML>=6`. `mypy --strict`
  passes clean across `src/hermes_plugin_sync/`.
