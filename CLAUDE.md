# custody — Claude Code context

> **Note:** This file is context for the [Claude Code](https://claude.ai/code)
> AI assistant and is not project documentation. It contains development
> context, session continuity notes, and implementation status that helps
> Claude Code understand the project across sessions.
>
> For project documentation see `README.md`, `docs/concept.md`, and
> `docs/architecture.md`.
>
> **Open question:** Whether this file stays in the public repo long-term is
> undecided. Options: keep it (useful for contributors using Claude Code),
> or move to `.gitignore` (purely internal). Decision deferred until the repo
> goes public.

## What is custody?

Partial-ownership manager for config files shared between apps and the user.
See `docs/concept.md` for the full concept and `docs/architecture.md` for
design decisions.

**Goal:** FOSS release on PyPI as `custody`. Name is reserved.
**GitHub:** https://github.com/i21aelbe/custody

## Replaces

`~/code/shell-tools/src/shell_tools/cz_partial_sync.py` — deleted once custody
is production-ready. No code sharing during development; concepts and algorithms
may be ported. Zero further investment in cz_partial_sync.

## Language

All repo artifacts (code, comments, docs, commit messages, CLI text) must be
in English. CLAUDE.md itself will be translated before the repo goes public.

## First concrete use case: Sidebar (macOS)

Sidebar is a Dock replacement that stores its config in a Binary Plist:
`~/Library/Preferences/at.sidebar.Sidebar.plist`

Key constraints (empirically verified):
- Sidebar reads config **only at startup**
- On quit, Sidebar writes its **full in-memory state** back → any external
  changes are overwritten
- No checksum/integrity check
- **Sync window:** after quit (poll ~3s for writes to finish) and before restart
- The Finder Extension process stays alive after quit and writes other keys
  periodically (~every 2 min)

### Plist structure

Most values are JSON-encoded bytes inside the Binary Plist:

| Key | Type | Sync |
|-----|------|------|
| `sidebarStyle` | JSON list (one entry per display) | global + display-specific |
| `applicationConfigurations` | JSON list (139 apps) | global |
| `linkConfigurations` | JSON list | global |
| `smartStackConfigurations` | JSON list | global |
| `stackConfigurations` | JSON list | global |
| `spacerConfigurations` | JSON list | global |
| `launcherConfigurations` | JSON list | global |
| `KeyboardShortcuts_*` | string (JSON) | global |
| `sidebarSettings` | bytes (encrypted, License) | **never touch** |
| `applicationStatistics` | JSON dict | app-owned (runtime) |
| `applicationWindowOrders` | JSON dict | app-owned (runtime) |
| `recentlyClosedApps` | JSON list | app-owned (runtime) |
| `hints` | JSON list | app-owned (runtime) |
| `NSWindow Frame *` | string | app-owned (ui-state) |
| `at.sidebar.Sidebar.tabWindow.size.*` | dict | app-owned (display-specific) |

### sidebarStyle — special case

List of style entries, one per display:
- `displayId: null` → default for all unknown screens
- `displayId: "UUID"` → override for a specific monitor

Each entry has ~110 fields (complete, no inheritance). Display UUIDs come from
macOS IOKit/EDID — stable per physical monitor across machines.

**Open question:** Does `displayId: null` act as a fallback in "Individual"
mode, or do unknown displays get factory defaults? Not empirically verified.

**Universal Control artefact:** The macOS windowserver plist contains display
UUIDs from monitors reachable via UC from other Macs — not a reliable source
for "physically connected displays on this machine".

## Implementation status

Done and tested:
- `segments.py` — PathSegments, parse_pointer, walk, delete_at, to_jsonpath_wildcard
- `merge.py` — smart_merge, merge_by_key
- `expressions.py` — JSON Pointer + JSON Path dispatch via jsonpath-ng
- `ownership.py` — Chain of Responsibility (IgnoredPathsHandler, ManagedDocHandler, SourceKind.RECURSE)
- `engine.py` — Phase 2A (drift), 2B (unknown + dict/list recurse), Phase 1 (additive)
- `config.py` — ConfigTarget.from_dir, find_configs, write_managed, write_ignored (auto JSON Path for array paths), write_pending
- `adapters.py` — Adapter protocol, JsonAdapter, registry
- `hooks.py` — pluggy specs (custody_sync wrapper, after_managed_file_written, after_target_written), make_plugin_manager, load_customize_file, scoped_plugins
- `interactive.py` — adopt dialog: colored diff (target-without → target), 1/2/3/r/s/a menu, dict recurse, list-of-dicts recurse into first element, array-element ignore writes JSON Path
- `cli.py` — `custody sync [name]`, plugin wiring, _SyncCore hookimpl

Not yet implemented:
- `PlistAdapter` — Binary Plist read/write (needed for Sidebar milestone)
- `schema.py` — generate, validate, x-merge-key extraction
- `custody generate-schema`, `custody migrate` CLI commands

## Deployment

Currently installed as editable dev tool:
```sh
uv tool install --editable ~/code/custody   # → custody binary
custody sync
```

Planned dual deployment (see Milestone 1):
- `custody` — stable tagged release
- `custody-dev` — editable, points to repo (requires `custody-dev` entry point in pyproject.toml)

chezmoi trigger optional via `run_onchange_after_custody.sh.tmpl`.

---

## Milestones

### Milestone 1 — cz_partial replacement (next)

`cz_partial_sync.py` currently handles only JSON configs (no Sidebar, no
Plist). custody already covers the same scope. Steps to close this out:

1. **Move test config** from `.config/custody/claude_desktop_config_test/`
   to `.config/custody-dev/` (separate dir for dev instance while stable
   `custody` runs against `.config/custody/`).

2. **Add `custody-dev` entry point** to `pyproject.toml`:
   ```toml
   [project.scripts]
   custody     = "custody.cli:main"
   custody-dev = "custody.cli:main"
   ```
   Then: `uv tool install --editable ~/code/custody` → installs both
   `custody` (dev) and a future stable `custody` can coexist.
   Actually: stable goes to `.config/custody/`, dev to `.config/custody-dev/`
   — so we need a `--config-dir` flag or env var in `cli.py` to support this.

3. **Test chezmoi integration**: run `custody sync` as chezmoi hook
   (`run_onchange_after_custody.sh.tmpl`), verify managed files are written
   back to chezmoi source via ChezmoidPlugin if desired.

4. **Verify `find_configs`** iterates correctly over all dirs in the config
   base dir on real data.

5. **Tag**: `git tag v0.1.0` with message "cz_partial function reached".
   Delete `cz_partial_sync.py` from shell-tools.

### Milestone 2 — Sidebar support

- `PlistAdapter` — Binary Plist + inner JSON-encoded byte values
- Sidebar config subdir setup (`~/.config/custody/sidebar/`)
- SidebarPlugin via `customize.py` (example already in `docs/examples/plugins/`)
- Tag: `v0.2.0`

---

## Bootstrap prompt for next session

> Read `CLAUDE.md`, `docs/concept.md`, `docs/architecture.md`, and skim
> `src/custody/` to get oriented. We are starting **Milestone 1** today:
> cz_partial replacement. The concrete first step is probably adding a
> `--config-dir` option to the CLI so that `custody-dev` can point to
> `.config/custody-dev/` while `custody` uses `.config/custody/`. Ask me
> before making any changes — I want to review the plan first.
