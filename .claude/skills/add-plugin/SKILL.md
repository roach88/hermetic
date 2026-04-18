---
name: add-plugin
description: Add a single new Claude Code plugin to a Hermes installation via the `hermetic` CLI. Use when the user asks to add, install, register, or sync a new plugin in a `plugin-sync.yaml`. Produces the YAML diff and STOPS for explicit approval before running `hermetic sync`. Does NOT remove, list, or inspect plugins — for those, the user should invoke the `hermetic` CLI directly.
---

# Add a plugin via hermetic

Walks the user through appending one new plugin entry to an existing
`plugin-sync.yaml`, then running `hermetic sync`. The skill **stops and shows
the diff** before any network or filesystem work — the user must explicitly
approve the YAML change before `hermetic sync` runs.

## Preconditions (verify before anything else)

1. **`hermetic` is installed.** Run `hermetic --version`. If missing, tell
   the user to `uv pip install hermetic-cli` (or `pip install hermetic-cli`)
   and stop.
2. **A `plugin-sync.yaml` exists.** Check, in order:
   - the path the user named in their message
   - `./plugin-sync.yaml` (cwd)

   If neither exists, ask the user where the config lives or should be
   created. Do not guess a path.
3. **Hermes home is resolved.** Priority: `--hermes-home` flag in play >
   `$HERMES_HOME` env var > default `~/.hermes`. Name the resolved path in
   the approval summary so the user can confirm.

## Gather plugin details

Collect (ask only what the user hasn't already told you):

- **Repo URL** — required. Any URL `git clone` accepts (https, ssh, file://).
- **Branch** — default `main`. Don't prompt unless the user mentioned a
  non-default.
- **Monorepo layout?** — many Claude Code plugin repos nest plugins under
  `plugins/<name>/`. See "Monorepo detection" below.
- **Plugin `name`** — the subdirectory created under
  `<hermes_home>/skills/<name>/`. Prefer the user's stated name; otherwise
  use the monorepo `subdir` leaf or the repo's last path segment.

### Monorepo detection

If the user already knows the layout, use what they said. Otherwise, the
cheapest probe is a shallow treeless clone:

```bash
git clone --depth 1 --filter=tree:0 <url> /tmp/hermetic-probe
ls /tmp/hermetic-probe              # skills/ and agents/ at root?
ls /tmp/hermetic-probe/plugins 2>/dev/null  # monorepo layout?
rm -rf /tmp/hermetic-probe
```

- `skills/` and/or `agents/` at the root → no `subdir:` needed.
- `plugins/<name>/` tree → set `subdir: plugins/<name>`.
- Neither obvious → ask the user.

## Produce the diff

Show the user:

1. The exact YAML block being added.
2. Whether the existing file uses the `plugins:` mapping form or the bare
   list form (`cli.py:81-92` accepts either — preserve whichever the file
   already uses; do not mix).
3. The resolved **Hermes home**.
4. The absolute path of the `plugin-sync.yaml` being edited.

Example approval summary:

```
About to append to <absolute path to plugin-sync.yaml>:

  - name: <plugin-name>
    git: <repo URL>
    branch: main
    subdir: <subdir if monorepo, else omit>

Hermes home:  <resolved hermes home>
File format:  <plugins:-mapping | bare-list> (preserving existing form)
```

## STOP — get approval

Do NOT run `hermetic sync` yet. Ask:

> Apply the edit and run `hermetic sync`? (yes / no / modify)

- **yes** → proceed.
- **no** → exit, make no changes.
- **modify** → go back to "Gather plugin details" and iterate.

## Apply + sync (only after explicit yes)

1. Edit the YAML file. Append the new entry in the form the file already
   uses. Read the file back after writing to confirm the change.
2. Run `hermetic sync --config <absolute-path>`. Capture output.
3. Run `hermetic list`. Surface the new plugin's row (skill count, agent
   count, last_synced) so the user sees it landed.

## Common failure modes

- **"Migrated 0 items" warning** after a successful clone. Almost always a
  monorepo with a missing or wrong `subdir:`. Ask the user for the correct
  subdir, update the YAML, re-sync. Do not leave a zero-item entry silently.
- **Git auth failure on private repo.** Surface verbatim. If the URL is
  `https://`, suggest the `git@github.com:…` ssh form. Do not attempt
  credential workarounds.
- **YAML parse error after the edit.** Read the file back, show the line,
  offer to revert from the pre-edit content. `hermetic` is strict about
  form consistency — don't mix bare-list and `plugins:`-mapping inside one
  file.
- **Plugin `name:` already present.** Stop. Tell the user. Offer to replace
  the existing entry (with explicit approval) or pick a different `name`.

## What this skill does NOT do

- Removing plugins — use `hermetic clear <plugin> --yes`.
- Listing or inspecting — use `hermetic list` / `hermetic inspect <plugin>`.
- Creating a fresh `plugin-sync.yaml` from scratch with multiple plugins —
  this skill is single-plugin-append only. Bulk bootstrap is a separate
  workflow.
- Editing the manifest (`.plugin_sync_manifest.json`) directly — always
  go through `hermetic sync` / `hermetic clear`.
