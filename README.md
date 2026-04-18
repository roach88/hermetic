# hermetic

Sync [Claude Code](https://docs.claude.com/en/docs/claude-code) plugins into
[Hermes](https://github.com/NousResearch/hermes-agent) as native skills and
delegation skills.

- **PyPI**: [`hermetic-cli`](https://pypi.org/project/hermetic-cli/)
- **CLI**: `hermetic`
- **GitHub**: [roach88/hermetic](https://github.com/roach88/hermetic)

> 🚧 **v0.1 — alpha.** API shape and manifest schema are stable for what's
> shipped; the tool is still small and close to its source script.

## What it does

Claude Code plugins ship skills (`SKILL.md` trees) and agents (persona `.md`
files). Hermes wants both as first-class skills: skills copy as-is, agents
become **delegation skills** — a `SKILL.md` that tells Hermes "when this
matches, invoke `delegate_task` with this persona and these toolsets."

`hermetic` handles the translation + idempotent re-sync + prune-on-remove, so
you can keep a `plugin-sync.yaml` under version control and re-run it safely.

## Install

```bash
pip install hermetic-cli
# or
uv pip install hermetic-cli
# or, no install, one-off:
uvx --from hermetic-cli hermetic --help
```

## Quickstart

```bash
# 1. Write a config pointing at one or more plugin repos.
cat > plugin-sync.yaml <<'YAML'
- name: compound-engineering
  git: https://github.com/EveryInc/compound-engineering-plugin.git
  branch: main
  subdir: plugins/compound-engineering   # see "Monorepos" below
YAML

# 2. Sync into a scratch Hermes home (defaults to ~/.hermes if you omit --hermes-home).
hermetic --hermes-home /tmp/hermes-scratch sync --config plugin-sync.yaml

# 3. See what landed.
hermetic --hermes-home /tmp/hermes-scratch list
hermetic --hermes-home /tmp/hermes-scratch inspect compound-engineering --json | jq

# 4. Remove a plugin when done.
hermetic --hermes-home /tmp/hermes-scratch clear compound-engineering --yes
```

## Config file format

`plugin-sync.yaml` is a **list** of plugin entries. Each entry:

```yaml
- name: compound-engineering        # required — used as the subdir under <hermes_home>/skills/
  git: https://github.com/...       # required — any URL git clone accepts (https, ssh, file://)
  branch: main                      # optional — defaults to 'main'
  subdir: plugins/compound-engineering   # optional — see "Monorepos"
```

### Monorepos

Many Claude Code plugin repos are monorepos: one git repo that holds several
plugins under `plugins/<name>/`. Without `subdir:`, `hermetic` looks for
`skills/` and `agents/` at the **repo root** and silently migrates zero items
(it logs a WARNING so you notice). Set `subdir:` to point at the actual
plugin tree:

```yaml
- name: compound-engineering
  git: https://github.com/EveryInc/compound-engineering-plugin.git
  subdir: plugins/compound-engineering
```

## CLI reference

Global flags (work before or after the subcommand):

| Flag | Default | Purpose |
|---|---|---|
| `--hermes-home PATH` | `$HERMES_HOME` or `~/.hermes` | Hermes install root |
| `--log-level LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `--version` | — | Print version and exit |

### `sync --config <path>`

Clone/update each plugin in the YAML and migrate skills + agents. Continues
past per-plugin failures; exits `1` if any failed, `0` if all succeeded.

### `list [--json]`

Table of installed plugins with skill count, agent count, and last synced.
`--json` emits a sorted array per plugin:

```json
[
  {"name": "compound-engineering", "git": "https://...", "branch": "main",
   "skill_count": 43, "agent_count": 50,
   "last_synced": "2026-04-18T13:43:12.957316+00:00"}
]
```

### `inspect <plugin> [--json]`

All manifest entries for one plugin. Unknown plugin → exits non-zero.
`--json` emits `{name, git, branch, last_synced, entries: [...]}`.

### `clear <plugin> [--yes]`

Remove `<hermes_home>/skills/<plugin>/` and drop the plugin's `_plugins`
metadata. Idempotent. Without `--yes`, prompts for confirmation.

## How it works

### Skills → skills (straight copy)

Every `<repo>/<subdir>/skills/<name>/` with a `SKILL.md` is copied to
`<hermes_home>/skills/<plugin>/<name>/`. Re-syncs are content-hashed:
an unchanged upstream doesn't touch the file (mtime preserved).
User edits to local `SKILL.md` are detected and preserved with a
`SKIP (user-modified)` warning — upstream updates won't clobber local work.

### Agents → delegation skills

Every `<repo>/<subdir>/agents/**/<name>.md` becomes
`<hermes_home>/skills/<plugin>/agents/<name>/SKILL.md`. The translation:

- **Name**: `<plugin>/agent/<name>`
- **Toolsets**: Claude Code `tools:` list is mapped to Hermes toolsets
  (`Read/Edit/Write/Glob/Grep → file`, `Bash → terminal`, etc.);
  unmapped tools are surfaced as a warning block in the body
- **Body**: a delegation header ("invoke `delegate_task` with …")
  followed by the original persona verbatim under `## Persona`

### Manifest

`<hermes_home>/skills/.plugin_sync_manifest.json` tracks origin hashes and
per-plugin metadata. Safe to commit if you want your Hermes skills pinned;
safe to delete if you want a full re-sync.

Schema:

```json
{
  "<plugin>/<skill-name>": {
    "plugin": "compound-engineering",
    "kind": "skill",
    "source_path": "/…/plugins/compound-engineering/skills/...",
    "origin_hash": "sha256 hex"
  },
  "_plugins": {
    "<plugin-name>": {
      "git": "https://...",
      "branch": "main",
      "last_synced": "2026-04-18T13:43:12.957316+00:00"
    }
  }
}
```

## Related work

- [`rule-migration-agent`](https://pypi.org/project/rule-migration-agent/) —
  bidirectional converter between Claude Skills and Cursor rules. Different
  target (Cursor); complementary, not competing.

## Upstream contribution

The core (`hermetic.core`) is designed to be importable. The eventual goal is
upstream integration into `hermes-agent` as a built-in
`hermes plugins import-claude-code` subcommand. If you're working on that —
please open an issue before duplicating effort.

## Development

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[test,dev]"

uv run pytest                        # 84+ tests, ~2s
uv run ty check src/hermetic          # type-check
uv run ruff check src tests           # lint
uv run ruff format src tests          # format
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for PR + commit conventions.

## License

MIT. See [`LICENSE`](LICENSE).
