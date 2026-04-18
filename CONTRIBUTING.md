# Contributing to hermetic

Thanks for considering a contribution. This is a small, focused tool — the
goal is tight scope, high test coverage, and a clean interface that could
plausibly graduate into `hermes-agent` upstream.

## Dev setup

Requires Python ≥ 3.10 and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/roach88/hermetic.git
cd hermetic
uv venv && source .venv/bin/activate
uv pip install -e ".[test,dev]"
```

## Running the gates

```bash
uv run pytest                        # default run (84+ tests, skips network-live)
uv run pytest -m live                # opt-in: network tests against a real public plugin
uv run pytest --cov=hermetic         # coverage report
uv run ty check src/hermetic         # typecheck (Astral's ty, strict via error-on-warning)
uv run ruff check src tests          # lint
uv run ruff format src tests         # format
```

CI runs all of these plus a matrix across Python 3.10–3.14 on Linux + macOS
bookends. Your PR must pass CI to merge.

## Project structure

```
src/hermetic/
  __init__.py         # version, public exports
  cli.py              # argparse CLI + subcommand dispatch
  core.py             # sync orchestration — takes hermes_home: Path explicitly
  git.py              # shallow clone / fetch wrapper
  manifest.py         # load/save + _plugins metadata schema
  frontmatter.py      # YAML frontmatter parse/render + hashing
  tools.py            # Claude Code tools → Hermes toolsets map

tests/
  test_*.py           # unit tests, one module per topic
  test_parity.py      # byte-for-byte diff against frozen legacy script
  integration/        # file:// and (opt-in) live network tests
  fixtures/           # sample plugin tree + frozen legacy snapshot
```

Every public function in `core.py` / `manifest.py` takes `hermes_home: Path`
explicitly — **do not introduce module-level path constants**. Path
resolution is the caller's job.

## Commit + PR conventions

- **Conventional commits**: `feat:`, `fix:`, `test:`, `ci:`, `docs:`,
  `refactor:`, `chore:`. Include a scope when helpful: `fix(git): ...`.
- **One logical change per commit**. Reformatting mixed with behavior
  changes makes review harder and bisect painful.
- **PR description**: problem, approach, verification steps run. If you
  changed behavior, show a before/after from `list` or `inspect`.
- **Keep PRs small.** Under ~300 LOC is easy; much bigger usually means
  two PRs.

## Parity discipline

`tests/test_parity.py` diffs the new implementation against a frozen
snapshot of the original script at `tests/fixtures/legacy_plugin_sync_v0.py`.
If you intentionally diverge from the legacy behavior:

1. Make the change + explain *why* in the commit message.
2. Update `test_parity.py` to document the deviation (e.g. `_plugins` key
   stripping — see the existing pattern).
3. Do **not** edit `legacy_plugin_sync_v0.py`. It's a frozen snapshot; its
   value is precisely that it doesn't change.

## What's in scope

- Better Hermes integration (toolset mappings, manifest schema extensions)
- Safer git operations (retry on transient failures, sparse-checkout)
- Better error reporting in the CLI
- Additional Claude Code plugin layouts that don't yet work

## What's out of scope (for v0.x)

- Bidirectional sync (Hermes → Claude Code)
- Non-Hermes targets (there's already `rule-migration-agent` for Cursor)
- Webhooks / auto-sync triggers — that's infrastructure, not this tool

## Questions

Open an issue. If it's about upstream integration with `hermes-agent`,
mention that in the title — I want to avoid duplicating work.
