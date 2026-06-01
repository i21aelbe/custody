# custody — Core Concepts

## The ownership model

Every path in a target config file has exactly one owner:

| Source | Meaning |
|---|---|
| `managed_global.json` | custody-owned, all machines |
| `managed_<hostname>.json` | custody-owned, this machine only |
| `ignored_paths` | app-owned — never modified |
| *(none)* | unknown — user decides interactively |

A path being "owned" means custody takes responsibility for its value. "Ignored" means custody acknowledges the path exists but will never touch it. "Unknown" triggers an interactive dialog the first time it is encountered.

## Config subdir structure

One directory per managed config file:

```
~/.config/custody/<name>/
  target              # relative path to the target file (from $HOME)
  managed_global.json # custody-owned JSON subset, all machines
  managed_<host>.json # custody-owned JSON subset, this machine (optional)
  ignored_paths       # one path expression per line; # comments allowed
  adapter             # "plist" or "json" (optional, default: json)
  pre_sync.sh         # hook executed before sync (optional, executable)
  post_sync.sh        # hook executed after sync (optional, executable)
  schema.json         # JSON Schema for the target (optional, generated)
  .pending            # deferred unknown paths (runtime, not committed)
```

Convention over configuration: every piece of metadata is a plain file.
`cat "$HOME/$(cat target)"` gives you the target file directly from the shell.

## Merge semantics

The *desired* state is computed by merging global and local managed docs:

```
desired = smart_merge(managed_global.json, managed_<hostname>.json)
```

Rules:

| Types | Result |
|---|---|
| dict + dict | recursive merge; local keys win on conflict |
| list + list | union of elements (deduplicated, sorted if possible) |
| anything + scalar | local wins |

For arrays containing objects where individual elements need to be merged by
identity (not by value), a *merge key* must be declared in `schema.json` via
the `x-merge-key` extension (see [Schema](#schema) below). Without a merge key,
arrays are treated atomically.

**Example — two machines, one shared list:**

`managed_global.json`:
```json
{ "allowedDirectories": ["/Music"] }
```

`managed_memac.json`:
```json
{ "allowedDirectories": ["/work/projects"] }
```

Result: `{ "allowedDirectories": ["/Music", "/work/projects"] }` (union).

## The three sync phases

Phases run in a fixed order on every sync.

### Phase 2A — Drift detection

For every path you own, custody compares the *desired* value against the
*current* value in the target. If they differ, custody overwrites the target
and records the drift for reporting.

Drift typically happens when:
- Another machine pushed a different value via chezmoi or direct edit.
- The app modified a path it shouldn't have touched.

### Phase 2B — Unknown paths

custody walks the target and finds every path that is neither owned nor
ignored. For each one it calls the *adopt callback* (interactive by default):

| Option | Effect |
|---|---|
| Adopt globally | written to `managed_global.json` |
| Adopt locally | written to `managed_<hostname>.json` |
| Ignore | added to `ignored_paths` |
| Defer | recorded in `.pending`, asked again next run |

Non-interactive runs (no TTY) skip this phase; all unknowns are deferred.

### Phase 1 — Additive sync

Owned paths that are missing from the target are inserted. This phase never
overwrites — it only adds. Phase 2A handles overwriting.

## Path expressions

Path expressions are used in `ignored_paths` and in the schema's `x-merge-key`.
Two syntaxes are supported; the syntax is detected automatically from the string:

| Prefix | Syntax | Example |
|---|---|---|
| `/` or `""` | JSON Pointer (RFC 6901) | `/preferences/theme` |
| `$` | JSON Path (RFC 9535) | `$.applicationConfigurations[?(@.isSystem)]` |

Both syntaxes have *subtree semantics*: owning `/preferences` means owning
`/preferences` and all sub-paths beneath it.

JSON Path expressions are evaluated against the actual target document, so
filter expressions like `[?(@.bundleId == "com.apple.Finder")]` can select
specific array elements by value.

## Schema

`schema.json` is a standard JSON Schema with one custody-specific extension:
`x-merge-key` on array properties.

### x-merge-key

Declares the identity field for array elements, enabling element-level merge
instead of atomic replacement:

```json
{
  "properties": {
    "applicationConfigurations": {
      "type": "array",
      "x-merge-key": "bundleId",
      "items": {
        "required": ["bundleId"]
      }
    },
    "sidebarStyle": {
      "type": "array",
      "x-merge-key": "displayId"
    }
  }
}
```

With `x-merge-key: "bundleId"` on `applicationConfigurations`:
- `managed_global.json` lists the entries you own (identified by `bundleId`).
- When syncing, each entry is matched to the target by `bundleId`, not by index.
- New entries the app adds (unknown `bundleId`) flow through Phase 2B as normal.

### Schema roles

| Check | When | What it catches |
|---|---|---|
| Validate target | before sync | app changed its format unexpectedly |
| Validate result | after sync | bug in custody's own merge logic |
| Validate managed docs | before sync | typo in a path in managed_global.json |
| Validate ignored_paths | before sync | expression references a non-existent path |

### Generating a schema

```sh
custody generate-schema <name>
```

Reads the current target, generates `schema.json`, and interactively proposes
`x-merge-key` candidates (arrays where one field is unique across all elements).

### Schema migration

When an app changes its config format, the pre-sync schema check will fail.
Running `custody migrate <name>` compares the old schema against a freshly
generated one and proposes concrete changes to `managed_global.json`,
`managed_<hostname>.json`, and `ignored_paths`.

## Hooks

`pre_sync.sh` and `post_sync.sh` are executable shell scripts placed in the
config subdir. They are run before and after the sync respectively.

Primary use case: apps that read config only at startup and write their full
in-memory state back on quit. The pre hook quits the app; the post hook
restarts it. The sync happens in the window between.

```sh
# pre_sync.sh — quit Sidebar and wait for it to finish writing
osascript -e 'tell application "Sidebar" to quit'
sleep 3
```

## chezmoi integration (optional)

custody is chezmoi-agnostic. To trigger custody from chezmoi, add a
`run_onchange_after_custody.sh.tmpl` script to your chezmoi source:

```sh
#!/bin/sh
custody sync
```

chezmoi runs this script whenever any tracked file changes, keeping your
managed configs in sync as part of `chezmoi apply`.
