# custody — Claude Code context

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
- `segments.py` — PathSegments, parse_pointer, walk (arrays atomic)
- `merge.py` — smart_merge, merge_by_key (with None-identity sentinel fix)
- `expressions.py` — JSON Pointer + JSON Path dispatch via jsonpath-ng
- `ownership.py` — Chain of Responsibility (IgnoredPathsHandler, ManagedDocHandler)
- `engine.py` — Phase 2A (drift), 2B (unknown), Phase 1 (additive)

Planned next:
- `config.py` — read a custody config subdir from disk
- `adapters/` — JSON adapter, Binary Plist adapter
- `schema.py` — generate, validate, x-merge-key extraction
- `cli.py` — `custody sync`, `custody init`, `custody migrate`

## Deployment

```sh
uv tool install custody   # installs binary into system
custody sync              # runs sync for all configured targets
```

No symlink deployment. chezmoi trigger optional via
`run_onchange_after_custody.sh.tmpl`.
