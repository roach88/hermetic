---
title: Extract hermes-plugin-sync as a standalone pip package
type: feat
status: active
date: 2026-04-17
target_repo: NEW — to be created as a separate GitHub repository (e.g., tyler/hermes-plugin-sync)
---

# Extract hermes-plugin-sync as a standalone pip package

## Overview

Extract the Claude Code → Hermes plugin migrator — currently a bespoke script at `scripts/plugin_sync.py` in this deployment repo — into a standalone Python package published on PyPI. The goal is to make the tool usable by any Hermes operator (local Mac, Docker, Fly, VPS, NAS) and to create a clean foundation for eventual upstream contribution to Nous Research's `hermes-agent` as a built-in `hermes plugins import-claude-code` subcommand.

This is "Layer 1" of a larger three-layer generalization vision (pip package → Fly deployment template → operator skill pack). Layer 1 is the highest-leverage unit because it works for any Hermes install, carries no deployment opinions, and is the most likely candidate for upstream adoption.

## Problem Frame

Today the migrator solves a real problem (Claude Code plugin format ≠ Hermes plugin format; skill and agent files need translation + manifest-based idempotency) but it's trapped inside a single deployment. Key friction points:

1. **Not reusable** — Every new Hermes deployment would have to copy the script by hand, adjust paths, and maintain it independently.
2. **No versioning** — Bug fixes or format updates require manual propagation across copies.
3. **No CI** — The only way to know the script still works is to redeploy and observe.
4. **Not discoverable** — Someone googling "migrate Claude Code plugin to Hermes" finds nothing.
5. **No path to upstream** — Contributing to `hermes-agent` requires the code to be factored into testable modules with a clear interface, not a single-file script.

The current script at `scripts/plugin_sync.py` (~320 lines) is structurally sound — it already has clear separation between config loading, git ops, skill migration, agent translation, and manifest management. The packaging work is primarily scaffolding + decomposition, not a rewrite.

## Requirements Trace

- **R1.** Installable via `pip install hermes-plugin-sync` from PyPI. Also works with `pipx install hermes-plugin-sync` for isolated install.
- **R2.** Provides a CLI binary `hermes-plugin-sync` with at least these subcommands: `sync`, `list`, `inspect`, `clear`.
- **R3.** Reads the same `plugin-sync.yaml` schema currently used (no breaking changes for existing users).
- **R4.** Preserves current migration behavior verbatim: SKILL.md files copied, Claude Code agents translated to Hermes delegation-skill pattern, manifest-based idempotency with user-modification preservation and upstream-deletion cleanup.
- **R5.** Hermes home directory configurable via `--hermes-home PATH` flag or `HERMES_HOME` env var, defaulting to `~/.hermes/`.
- **R6a.** Test coverage ≥ 80% line + branch across the `src/hermes_plugin_sync/` modules.
- **R6b.** CI enforces the R6a coverage threshold on every PR (fails below 80%).
- **R7.** CI green on Python 3.10, 3.11, 3.12, 3.13, 3.14; Ubuntu and macOS runners.
- **R8.** Published to PyPI via Trusted Publishers (OIDC) — no long-lived API tokens stored anywhere.
- **R9.** Minimal documentation: README with quickstart + CLI reference + config schema, CHANGELOG in Keep-a-Changelog format, MIT LICENSE.
- **R10.** Code organized so that the core migration logic is importable as a library (`from hermes_plugin_sync import sync_plugin`) for future embedding in `hermes-agent` as a subcommand.

## Scope Boundaries

- No deployment infrastructure (Fly.toml, Dockerfile, entrypoint scripts — those are Layer 2).
- No operator skills (the `add-claude-code-plugin` Hermes skill — that's Layer 3).
- No non-Claude-Code migration adapters (Cursor, Codex, OpenCode, etc. — the source format we support is Claude Code plugins only).
- No web UI, dashboard, or daemon mode — CLI only for v1.
- No automatic plugin discovery (crawling GitHub, plugin marketplaces) — users declare plugins in YAML explicitly.
- No cron scheduling inside the package — users invoke the CLI from their own cron / systemd / launchd as appropriate.

### Deferred to Separate Tasks

- **Upstream contribution PR** to `hermes-agent`: separate task after v0.1 is stable and exercised by at least one external user.
- **Fly deployment template (Layer 2)**: separate repo + plan.
- **Operator skill pack (Layer 3)**: separate repo + plan.
- **Additional source-format adapters** (Cursor, OpenCode): considered only after Claude Code path is battle-tested.
- **`--dry-run` flag**: nice-to-have, defer to v0.2 unless user demand surfaces during alpha.

## Context & Research

### Relevant Code and Patterns

- **`scripts/plugin_sync.py`** — existing 320-line script, source of truth for migration logic. Well-factored into functional sections (manifest, frontmatter, git, migrate_skill, translate_tools/build_delegation_skill, migrate_agent, prune_removed, sync_plugin, main). Extraction is mechanical, not a rewrite.
- **`plugin-sync.yaml`** — existing config schema (list of `{name, git, branch, subdir}`). Preserve exactly.
- **`skills/hermes-ops/add-claude-code-plugin/SKILL.md`** — operator skill that references `plugin-sync.yaml`; after extraction it will continue pointing at the (now-pip-installed) command rather than a script path.
- **Hermes's own `hermes_cli/` package structure** (in the upstream image at `/opt/hermes/hermes_cli/`) — reference for how to organize subcommand dispatch so eventual upstream integration slots cleanly into `hermes_cli/plugins_cmd.py` pattern.

### Institutional Learnings

From this deployment's setup process (per `.claude/projects/-Users-tyler-Dev-hermes/memory/`):
- **IaC over volume edits**: the CLI should emit YAML for users to commit, not write to arbitrary paths. This is already how the migrator works.
- **System cron over agent cron for deterministic ops**: the CLI shouldn't try to schedule itself; let the operator choose (cron / systemd / launchd / hermes cron).
- **Category-prefix plugin skills** for namespacing: current behavior preserved (skills land at `<hermes_home>/skills/<plugin>/<skill>/`).

### External References

- **Related work: `rule-migration-agent`** (PyPI) — bidirectional converter between Claude Skills (`.claude/skills`) and Cursor rules (`.cursor/rules`). Different target (Cursor), complementary not competing. Cite in README as "other tools in this ecosystem."
- **Python packaging 2026** — converged standards: `pyproject.toml` only (no `setup.py`), `src/` layout, PEP 621 project metadata. `hatchling` is a proven build backend; `uv` (Astral) is the emerging default for install + CI speed.
- **PyPI Trusted Publishers** — OIDC-based authentication from GitHub Actions to PyPI, no stored tokens. Requires `id-token: write` permission in the workflow + one-time trust setup in PyPI project settings.
- **PyPA `packaging.python.org`** — canonical reference for `pyproject.toml`, `[project.scripts]` entry points, metadata conventions.

## Key Technical Decisions

1. **Package name: `hermes-plugin-sync`**. No PyPI collision found. Descriptive, searchable, not overly long. Rationale: short enough for `pip install` muscle memory; "hermes" anchors it to the framework; "plugin-sync" describes action without framework-specific jargon.
2. **Build backend: `hatchling`**. Simpler than setuptools for pure-Python packages, widely supported, fast. Avoids the full Hatch tool — we just want the backend.
3. **Layout: `src/`**. PyPA-recommended; prevents accidental "works because of CWD" test failures; forces clean installed-package testing.
4. **CLI framework: `argparse` (stdlib only)**. Keeps dependencies minimal for a tool users install into their Hermes host. The current script already uses argparse; migration is a no-op. Alternatives (click, typer) would add 1–2 deps for minor UX gain.
5. **Python minimum: 3.10**. Matches modern typing (`X | Y` unions, `list[T]`), covers all supported platforms at time of writing, matches Hermes's own baseline.
6. **Test framework: `pytest` + `pytest-mock`**. Industry standard. `tmp_path` fixture handles filesystem isolation cleanly.
7. **Install speed in CI: `uv`**. Drop-in replacement for pip, 10–100× faster, ideal for matrix runs across four Python versions and two OSes.
8. **PyPI publishing: Trusted Publishers (OIDC)**. No stored `PYPI_API_TOKEN` — GitHub Actions identity verified directly by PyPI. Setup: `id-token: write` permission in publish workflow + one-time trust config in PyPI project settings (done post-first-release).
9. **License: MIT**. Matches Hermes upstream and the majority of the Python ecosystem. No copyleft friction for downstream use.
10. **Config parsing: `PyYAML`**. One dep, but justified — YAML is the config format, and reimplementing a YAML parser is not on the table. Hermes already depends on PyYAML, so co-installed users incur zero extra cost.
11. **Manifest location: configurable, defaults to `<hermes_home>/skills/.plugin_sync_manifest.json`**. Same location as current script — existing users migrating from script → pip have zero state drift.
12. **Public API surface: keep it small**. Export `sync_plugin(plugin_cfg, hermes_home, manifest)`, `load_manifest(hermes_home)`, `save_manifest(hermes_home, manifest)`. Everything else is internal. Small surface = easy upstream integration later.

## Open Questions

### Resolved During Planning

- **Package name**: `hermes-plugin-sync` (see Decision 1).
- **Python version support**: 3.10+ (see Decision 5).
- **CLI framework**: argparse (see Decision 4).
- **Upstream integration path**: keep core logic in `hermes_plugin_sync.core` as pure functions with no argparse dependency, so upstream can import them into `hermes_cli/plugins_cmd.py` directly (see Decision 12).

### Deferred to Implementation

- **Whether `TOOL_MAP` should be extensible via config**: current mapping covers Claude Code's standard tools. If Claude Code introduces new tools or users want custom mappings, we'd add a `--tool-map-overrides FILE` flag or config section. Defer until real-world use reveals demand.
- **Exact CHANGELOG entry format for auto-generated releases**: deferred; hand-edited for v0.1, consider automation (release-please, changesets) only if release cadence picks up.
- **Whether to mirror skill directories or symlink them**: current script copies. If users want to preserve a single source of truth (edit in the plugin repo, have Hermes use the edits), symlinks would fit. Defer — copy is safer and handles user-modified-local-copy detection cleanly.

## Output Structure

The new package repo will have this initial layout:

```
hermes-plugin-sync/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                # pytest matrix, mypy, ruff
│   │   └── publish.yml            # PyPI Trusted Publisher on tag
│   └── dependabot.yml
├── src/
│   └── hermes_plugin_sync/
│       ├── __init__.py            # version + top-level imports
│       ├── cli.py                 # argparse parser + main()
│       ├── core.py                # sync_plugin, migrate_skill, migrate_agent
│       ├── frontmatter.py         # parse/render helpers
│       ├── git.py                 # clone_or_update subprocess wrapper
│       ├── manifest.py            # load/save/prune manifest
│       └── tools.py               # TOOL_MAP + translate_tools
├── tests/
│   ├── conftest.py                # shared fixtures
│   ├── fixtures/
│   │   ├── plugin-sync.sample.yaml
│   │   └── sample_plugin/         # mock Claude Code plugin tree
│   ├── test_cli.py
│   ├── test_core.py
│   ├── test_frontmatter.py
│   ├── test_manifest.py
│   ├── test_tools.py
│   └── integration/
│       └── test_sync_end_to_end.py
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── pyproject.toml
└── .gitignore
```

This is the expected shape; the implementer may adjust if decomposition reveals a cleaner cut.

## Implementation Units

- [ ] **Unit 1: Project scaffolding + build config**

**Goal:** Set up the new repo with modern Python packaging baseline. Verify that `pip install -e .` works and the CLI entry point resolves before any migration logic is ported.

**Requirements:** R1, R9

**Dependencies:** None (new repo).

**Files:**
- Create: `pyproject.toml`
- Create: `src/hermes_plugin_sync/__init__.py`
- Create: `LICENSE` (MIT, copyright current year, holder = repo owner)
- Create: `README.md` (stub; unit 6 fills in)
- Create: `.gitignore` (Python standard: `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `dist/`, `build/`, `.venv/`)
- Create: `CHANGELOG.md` (stub with `## [Unreleased]` section)
- Create: `tests/conftest.py` (empty; placeholder for later fixtures)

**Approach:**
- `pyproject.toml`: `[build-system]` points at `hatchling`. `[project]` contains name (`hermes-plugin-sync`), dynamic version (from `__init__.py`), Python requires `>=3.10`, MIT license, dependencies (`pyyaml>=6`), and `[project.scripts]` with `hermes-plugin-sync = "hermes_plugin_sync.cli:main"`.
- `src/hermes_plugin_sync/__init__.py` declares `__version__ = "0.1.0"` only; no other imports at this stage.
- Verify locally with `python -m venv .venv && source .venv/bin/activate && pip install -e . && hermes-plugin-sync --version` before moving on.

**Patterns to follow:**
- PyPA's `writing-pyproject-toml` guide for the project metadata section.
- Modern `src/` layout as documented at realpython.com and PyPA.

**Test scenarios:**
- Test expectation: none — scaffolding unit; no behavior to test. Behavior tests start in Unit 2.

**Verification:**
- `pip install -e .` succeeds without errors.
- `hermes-plugin-sync --version` returns `0.1.0`.
- `python -c "import hermes_plugin_sync; print(hermes_plugin_sync.__version__)"` returns `0.1.0`.
- (Build verification — `python -m build` producing wheel+sdist — is exercised in Unit 5 where build tooling is configured, not here.)

---

- [ ] **Unit 2: Extract and decompose core migrator**

**Goal:** Port the existing `scripts/plugin_sync.py` logic into the new package, decomposed into testable modules with the same behavior.

**Requirements:** R3, R4, R5, R10

**Dependencies:** Unit 1.

**Files:**
- Create: `src/hermes_plugin_sync/manifest.py` — `load_manifest(hermes_home)`, `save_manifest(hermes_home, manifest)`, `manifest_path(hermes_home)`.
- Create: `src/hermes_plugin_sync/frontmatter.py` — `parse_frontmatter(text) -> (dict, str)`, `render_frontmatter(fm, body) -> str`.
- Create: `src/hermes_plugin_sync/tools.py` — `TOOL_MAP`, `TOOL_DROP`, `translate_tools(cc_tools) -> (toolsets, unknown_names)`.
- Create: `src/hermes_plugin_sync/git.py` — `clone_or_update(url, branch, dest)` wrapping `subprocess.run`.
- Create: `src/hermes_plugin_sync/core.py` — `sync_plugin(cfg, hermes_home, manifest, logger)`, `migrate_skill(...)`, `migrate_agent(...)`, `build_delegation_skill(...)`, `prune_removed(...)`.
- Create: `src/hermes_plugin_sync/__init__.py` update — export `sync_plugin`, `load_manifest`, `save_manifest`, `__version__`.
- Test: `tests/test_manifest.py`, `tests/test_frontmatter.py`, `tests/test_tools.py`, `tests/test_core.py`.
- Test fixtures: `tests/fixtures/sample_plugin/skills/...`, `tests/fixtures/sample_plugin/agents/...`.

**Approach:**
- Take `hermes_home: Path` as an explicit argument everywhere the current script uses the `SKILLS_DIR` / `PLUGINS_DIR` module constants. This is the primary shape change — it enables running the tool against any Hermes install, not just the Fly one.
- Replace module-level `logger = logging.getLogger("plugin_sync")` with an injectable logger parameter (or default to `logging.getLogger(__name__)` per module). Library code shouldn't call `logging.basicConfig`; only the CLI layer (Unit 3) does that.
- Preserve the exact manifest format so existing on-disk state remains valid.
- Preserve the exact delegation-skill template emitted for agents (the "🤖 Delegation skill" header + toolsets + persona body).
- Keep function signatures stable across `core.py` — this is the eventual upstream-integration surface.

**Patterns to follow:**
- Current `scripts/plugin_sync.py` — structure is already good; just split file boundaries and parameterize.

**Test scenarios:**
- **Happy path: manifest round-trip** — Empty-manifest roundtrip: `save_manifest` then `load_manifest` returns `{}`. Populated-manifest roundtrip: save a dict with two entries, load returns identical dict.
- **Edge case: corrupt manifest** — `load_manifest` on a file with invalid JSON returns `{}` and logs a warning (current behavior).
- **Happy path: parse_frontmatter** — Valid SKILL.md with `---\nname: x\ndescription: y\n---\nbody text` returns `({'name': 'x', 'description': 'y'}, 'body text')`.
- **Edge case: no frontmatter** — Raw markdown without `---` fences returns `({}, original_text)`.
- **Edge case: malformed YAML in frontmatter** — `({}, body)` (doesn't raise).
- **Happy path: translate_tools** — `"Read, Grep, Glob, Bash"` → `(["file", "terminal"], [])`.
- **Edge case: translate_tools with unknown tool** — `"Read, Frobnicate"` → `(["file"], ["Frobnicate"])`.
- **Edge case: translate_tools with empty/None** — `None` or `""` → `(["file", "web"], [])` (default).
- **Edge case: translate_tools with dropped tool** — `"Task, Read"` → `(["file"], [])`. `Task` is silently dropped (not unknown).
- **Happy path: build_delegation_skill output** — Passing a known agent frontmatter + body produces a SKILL.md string that (a) has correct `name: <plugin>/agent/<name>`, (b) includes the delegation header with the right toolsets, (c) embeds the original body verbatim below the `## Persona` heading.
- **Happy path: migrate_skill first run** — Given a fixture plugin skill dir, migrate_skill copies SKILL.md (and references/ if present) to the target, updates manifest with origin_hash.
- **Idempotency: migrate_skill second run same content** — No file write, manifest unchanged. (Verify via mtime or an instrumented logger.)
- **Update: migrate_skill after upstream change** — Origin hash differs, local hash matches previous origin hash → file is overwritten, manifest's origin_hash updated.
- **User-modification preservation** — If local file's hash differs from both previous origin and new origin, file is NOT overwritten and a warning is logged.
- **Error path: migrate_skill with missing SKILL.md in source dir** — Skipped gracefully, no crash, no manifest entry written.
- **Integration scenario: sync_plugin end-to-end** — Given a tmp hermes_home and a mock plugin already cloned at a tmp path (skip git), sync_plugin migrates all skills, translates all agents, and writes manifest. Verify: (a) correct file tree, (b) manifest has expected entries, (c) rerun is idempotent (no file mtime changes).
- **Integration scenario: prune_removed** — Between two sync_plugin calls, remove a skill from the mock plugin's source. Second call should delete the dest dir and update manifest (only if local wasn't user-modified).
- **Integration scenario: prune_removed preserves user-modified** — If user edited the dest SKILL.md between syncs, upstream removal does NOT delete it; a warning is logged.

**Verification:**
- All behavior from the original `scripts/plugin_sync.py` is reproduced by the new modules, confirmed by a diff-in-behavior test: run the old script on a fixture, then run the new package on the same fixture, compare output trees byte-for-byte.
- `pytest` passes all scenarios above.
- `mypy --strict src/hermes_plugin_sync` passes (or documented justified ignores).

---

- [ ] **Unit 3: CLI interface**

**Goal:** Add the `hermes-plugin-sync` CLI with the four subcommands (`sync`, `list`, `inspect`, `clear`). CLI is a thin wrapper over `core.py`.

**Requirements:** R2, R5

**Dependencies:** Unit 2.

**Files:**
- Create: `src/hermes_plugin_sync/cli.py` — `main(argv: list[str] | None = None) -> int`, argparse subparsers for `sync`, `list`, `inspect`, `clear`.
- Test: `tests/test_cli.py`.

**Approach:**
- Argparse top-level parser gets global flags: `--hermes-home PATH` (overrides env, which overrides default `~/.hermes/`), `--log-level`, `--version`.
- Subcommands:
  - `sync --config plugin-sync.yaml` — current behavior. Loops over configured plugins, calls `sync_plugin` for each, saves manifest at end.
  - `list` — reads manifest, prints a table of `(plugin, skill_count, agent_count, last_synced)`.
  - `inspect <plugin>` — reads manifest, prints details for one plugin: source URL, branch, last-sync timestamp, every skill/agent with its origin_hash and dest path.
  - `clear <plugin>` — removes all skills/agents for one plugin from `<hermes_home>/skills/<plugin>/` and drops the plugin's entries from the manifest. Prompts for confirmation unless `--yes` is passed.
- Resolve `hermes_home` once at parser entry (CLI flag > `HERMES_HOME` env > `Path.home() / ".hermes"`), then pass it down to `core` functions.
- Exit code: 0 on success; 1 on any plugin sync error (per plugin, log the error but continue; nonzero exit at end if any failed).

**Patterns to follow:**
- Current `scripts/plugin_sync.py:main()` — extend, don't replace.
- `hermes_cli`'s subcommand style (for eventual upstream fit).

**Test scenarios:**
- **Happy path: `--version`** — Exits 0, stdout contains `0.1.0`.
- **Happy path: `--help`** — Exits 0, stdout lists the four subcommands.
- **Happy path: `sync --config`** — Given a tmp hermes_home and a minimal plugin-sync.yaml pointing at a prepared local git repo fixture, CLI exits 0 and skills land at the expected path. (Use local file:// git URL to avoid network in unit tests.)
- **Error path: `sync` with missing config** — Exits nonzero, stderr has a helpful "config file not found" message.
- **Error path: `sync` with malformed YAML** — Exits nonzero, helpful parse error.
- **Happy path: `list` on empty hermes_home** — Exits 0, prints "No plugins installed."
- **Happy path: `list` with one synced plugin** — Prints a one-row table with correct counts.
- **Happy path: `inspect <plugin>`** — Prints details for the plugin.
- **Error path: `inspect <unknown-plugin>`** — Exits nonzero with "plugin not found; installed: [...]".
- **Happy path: `clear <plugin> --yes`** — Skills/agents dir removed, manifest updated. Second `list` no longer shows the plugin.
- **Safety: `clear <plugin>` without `--yes`** — Prompts via stdin; refusing aborts without changes.
- **Integration: `HERMES_HOME` env override** — Setting `HERMES_HOME=/tmp/foo` before invoking CLI makes it write to `/tmp/foo/skills/`.
- **Integration: `--hermes-home` flag wins over env** — Flag takes precedence.

**Verification:**
- All above pass.
- Manual end-to-end: `hermes-plugin-sync sync --config plugin-sync.yaml --hermes-home /tmp/test-hermes-home` produces the same output tree as running the original script with an equivalent setup.

---

- [ ] **Unit 4: Integration test against real public plugin**

**Goal:** Give the package a smoke test that exercises the full workflow against an actual upstream Claude Code plugin, confirming real-world compatibility.

**Requirements:** R4, R6a

**Dependencies:** Units 2, 3.

**Files:**
- Create: `tests/integration/test_sync_end_to_end.py`.
- Modify: `.github/workflows/ci.yml` — add an `integration` job that runs these tests separately (opt-in via marker; required on main branch, optional on PRs from forks).
- Create: `tests/integration/conftest.py` — fixture that creates a temp `hermes_home` and points `plugin-sync.yaml` at a small known-good public Claude Code plugin.

**Approach:**
- Pick one small, stable, public Claude Code plugin as the integration fixture (candidate: a small official example plugin, or a minimal test plugin we publish under a throwaway org). Avoid `compound-engineering-plugin` directly in integration tests — too large, slow, and its dependencies might shift — but we can include a "smoke" that it at least clones and starts migrating.
- Mark integration tests with `@pytest.mark.integration`; configure `pyproject.toml` so `pytest` doesn't run them by default (`addopts = "-m 'not integration'"`), but CI runs both.
- Allow overriding the plugin URL via env var (`HERMES_PLUGIN_SYNC_TEST_URL`) so maintainers can swap if the default fixture disappears.

**Patterns to follow:**
- pytest `tmp_path` + `monkeypatch` for isolation.
- pytest markers for opt-in slow/network tests.

**Test scenarios:**
- **Happy path: clone and sync a tiny public CC plugin** — End-to-end: CLI succeeds, at least N skills appear in dest, manifest has entries matching the plugin's contents.
- **Idempotency: second `sync` invocation** — No file mtime changes, no manifest changes. Test by recording mtimes before and after.
- **Upstream-change simulation: swap branch** — Point the YAML at a different branch that has a known-different skill set. Verify skills removed on first branch are pruned.

**Verification:**
- Integration tests pass locally and in CI's integration job.
- No flakiness across three consecutive CI runs.

---

- [ ] **Unit 5: CI + publishing**

**Goal:** Automated quality gates on every PR; automated publish to PyPI on tagged releases.

**Requirements:** R6b, R7, R8

**Dependencies:** Units 1–4.

**Files:**
- Create: `.github/workflows/ci.yml` — lint + typecheck + pytest matrix (Python 3.10–3.13, Ubuntu + macOS). Use `astral-sh/setup-uv` for fast installs.
- Create: `.github/workflows/publish.yml` — triggers on tag `v*.*.*`; builds wheel + sdist; uploads to PyPI via Trusted Publisher (OIDC, `id-token: write`).
- Create: `.github/dependabot.yml` — weekly dep updates, grouped minor/patch.
- Modify: `pyproject.toml` — add `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]` sections with opinionated-but-boring defaults.

**Approach:**
- CI jobs: `lint` (ruff check + ruff format --check), `typecheck` (mypy --strict), `test` (pytest with coverage, fail if < 80%), `integration` (opt-in on fork PRs, required on main).
- Matrix: Python `['3.10', '3.11', '3.12', '3.13', '3.14']` × OS `['ubuntu-latest', 'macos-latest']`. Can trim if CI time becomes painful (see "CI matrix proportionality" finding in the review — trimmed-matrix-for-v0.1 is a reasonable scope decision to consider before Unit 5 lands).
- Use `uv` to install: `uv pip install -e ".[test]"`. Define test extras in pyproject.toml.
- Publish workflow: runs on `workflow_dispatch` (manual) and on git tag push matching `v*`. Uses official `pypa/gh-action-pypi-publish@release/v1` action.
- **One-time manual step (not in code):** on PyPI project settings page, configure trusted publisher (GitHub owner / repo / workflow filename `publish.yml` / environment `release`). This happens AFTER first upload — the first upload has to use a one-time API token, then convert to trusted publisher.

**Patterns to follow:**
- `pypa/gh-action-pypi-publish` README for the OIDC step.
- `astral-sh/setup-uv` for pinning `uv` version in CI.

**Test scenarios:**
- Test expectation: none for CI config itself — verification is that the workflows run and produce the expected artifacts.

**Verification:**
- First PR (or an empty PR) triggers all CI jobs; all green.
- Cutting v0.1.0 tag triggers publish workflow; package appears on PyPI under `hermes-plugin-sync`.
- `pip install hermes-plugin-sync==0.1.0` from a fresh venv succeeds; `hermes-plugin-sync --version` reports `0.1.0`.

---

- [ ] **Unit 6: Documentation**

**Goal:** Make the package discoverable and usable without reading source code. Set the table for future upstream contribution.

**Requirements:** R9, R10

**Dependencies:** Units 1–5 (you need actual working code and CLI to document accurately).

**Files:**
- Modify: `README.md` — full quickstart, CLI reference, config schema, examples, troubleshooting, "contributing upstream" note, related-work pointer (rule-migration-agent).
- Modify: `CHANGELOG.md` — promote `[Unreleased]` to `[0.1.0] - YYYY-MM-DD` and populate with notes on initial feature set; add a new empty `[Unreleased]` header above it.
- Create: `CONTRIBUTING.md` — basic PR guidelines, dev setup (`uv venv && uv pip install -e ".[test,dev]"`), commit message style, code-of-conduct pointer.

**Approach:**
- README structure: Why → Quickstart → Config file format → CLI reference → Manifest details → How it works → Contributing → License.
- Quickstart shows the full end-to-end: install, write YAML, run, verify. Single-page, no hand-offs to other docs.
- "How it works" section briefly explains skill migration vs agent translation, referencing the delegation-skill pattern (this is the conceptually novel part; users will want to understand it).
- Related work: cite `rule-migration-agent` (Claude Skills ↔ Cursor rules) as a complementary tool and note the delta (we target Hermes, not Cursor).
- Contributing note: explicitly state that the core (`hermes_plugin_sync.core`) is designed to be importable for eventual upstream integration into `hermes-agent`. Invite upstream contributors to reach out before duplicating effort.

**Patterns to follow:**
- `rule-migration-agent` PyPI page + README — good model for a focused migration-tool README.
- Keep-a-Changelog format for CHANGELOG.

**Test scenarios:**
- Test expectation: none — documentation quality is validated by review + spot-check that commands in README actually work.

**Verification:**
- Copy-paste each command in the README quickstart into a fresh shell; each works exactly as documented.
- README renders correctly on GitHub and PyPI (check the rendered Markdown after publish).
- `rst-lint` or `markdownlint` passes if we configure it (optional).

## System-Wide Impact

- **Interaction graph**: New isolated repo/package; no direct interaction with existing deployment code during v0.1. Hermes deployment (this repo) continues using `scripts/plugin_sync.py` until we cut over — cutover is a *separate* task, not part of this plan.
- **Error propagation**: CLI exits nonzero on any plugin sync failure (preserving current script's behavior). Library functions raise or return error markers — no silent drops.
- **State lifecycle risks**: Manifest format preserved exactly; existing on-disk state is forward-compatible. A user on the old script could `pip install hermes-plugin-sync`, point it at the same `plugin-sync.yaml`, and it would see the existing manifest as valid (no re-migration).
- **API surface parity**: CLI behavior parity with the current script is explicit requirement (R4). Verified by the behavior-diff test in Unit 2 verification.
- **Integration coverage**: Unit 4 integration test exercises the full flow against a real public plugin — the key path that unit tests can't fully cover (because the interesting edge cases live in real-world plugin variance).
- **Unchanged invariants**: Claude Code plugin format interpretation, Hermes skill/agent target layout, delegation-skill template shape, manifest JSON schema — all preserved exactly.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `hermes-plugin-sync` name taken on PyPI by the time we publish | Check at start of Unit 1; fallback names in order of preference: `hermes-cc-sync`, `hermes-plugin-bridge`, `hermes-claude-plugin-sync`. Document chosen name in Decision 1. |
| Hermes changes its skill-directory conventions (`~/.hermes/skills/` path or subdirectory structure) | Make the target layout configurable via CLI flag (not just HERMES_HOME). Add version-detection or Hermes-version-aware paths in a future minor version if needed. |
| Claude Code plugin format evolves (new manifest fields, new tool names, renamed directories) | Version our own manifest; on schema mismatch, log a loud warning and skip affected plugins. Add a `doctor` subcommand in a future version that audits installed state against the current parser. |
| Upstream `hermes-agent` adds its own built-in plugin import feature that conflicts | Track upstream releases. If they ship something equivalent, pivot this package to explicitly be the "lightweight alternative for users who don't want to upgrade Hermes yet" — still valuable for downlevel compatibility. Best case: our code gets contributed upstream and this package becomes a thin shim. |
| Integration test's reference plugin gets renamed, deleted, or restructured | Make fixture URL overridable via env var; consider pinning to a specific git SHA rather than branch; as a backup, vendor a minimal fixture plugin in `tests/fixtures/` to decouple from any external dep. |
| Users on Python 3.9 want to use the tool | 3.10 minimum is a deliberate choice. Document it. If demand is loud we can lower in v0.2 at the cost of losing some modern typing syntax. Don't negotiate in v0.1. |
| PyPI Trusted Publisher setup fumbled → first publish fails | First publish uses a one-time scoped API token (standard practice). After it succeeds on PyPI, configure Trusted Publisher for all subsequent releases. Document this in `CONTRIBUTING.md`. |

## Documentation / Operational Notes

- **Release cadence**: v0.1.0 (alpha) after Units 1–6 complete. v0.2.0 bumps when the first material feature request lands (likely `--dry-run` or tool-map config). v1.0.0 when the tool has been exercised by ≥3 external users for ≥1 month without breaking bugs.
- **Deprecation policy for v0.x**: breaking changes allowed with a CHANGELOG note. v1.0 onwards follows semver strictly.
- **Announcement surface**: Hermes Discord (if exists), /r/LocalLLaMA (if relevant), this repo's README pointing at the new package. Not a primary marketing push — the tool should be discoverable by anyone searching "migrate Claude Code plugin to Hermes."
- **Upstream contribution plan**: after v0.1 has been stable for ~2 weeks and real users have exercised it, open a discussion issue on `NousResearch/hermes-agent` offering to contribute the migration logic as `hermes plugins import-claude-code`. If accepted, this package becomes a thin compatibility shim; if rejected or deferred, it continues standalone.
- **Migration path for this Hermes deployment**: once v0.1 is on PyPI, update this repo's `Dockerfile` to `pip install hermes-plugin-sync==0.1.0` instead of `COPY scripts/plugin_sync.py`. Update the `crontab` to call `hermes-plugin-sync sync --config ...` instead of the script path. This cutover is a separate small task — keeping the script around as a backup until the package is proven in production.

## Sources & References

- Current implementation: `scripts/plugin_sync.py`, `plugin-sync.yaml`, `skills/hermes-ops/add-claude-code-plugin/SKILL.md`.
- Hermes upstream: https://github.com/NousResearch/hermes-agent
- PyPA packaging guide: https://packaging.python.org/en/latest/tutorials/packaging-projects/
- `pyproject.toml` reference: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- PyPI Trusted Publishers: https://docs.pypi.org/trusted-publishers/
- `hatchling` build backend: https://hatch.pypa.io/latest/history/hatchling/
- `uv` (Astral): https://docs.astral.sh/uv/
- Related work — `rule-migration-agent`: https://pypi.org/project/rule-migration-agent/
- 2026 packaging survey (external): https://cuttlesoft.com/blog/2026/01/27/python-dependency-management-in-2026/
