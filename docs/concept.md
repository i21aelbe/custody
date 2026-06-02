# custody — Core Concepts

## The ownership model

Every path in a target config file has exactly one owner:

| Source | Meaning |
|---|---|
| `managed_global.json` | custody-owned, all machines |
| `managed_<hostname>.json` | custody-owned, this machine only |
| `ignored_paths` | app-owned — never modified |
| *(none)* | unknown — user decides interactively |

A path being "owned" means custody takes responsibility for its value. "Ignored"
means custody acknowledges the path exists but will never touch it. "Unknown"
triggers an interactive dialog the first time it is encountered.

## Config subdir structure

One directory per managed config file:

```
~/.config/custody/<name>/
  target              # relative path to the target file (from $HOME)
  managed_global.json # custody-owned subset, all machines
  managed_<host>.json # custody-owned subset, this machine (optional)
  ignored_paths       # one path expression per line; # comments allowed
  adapter             # format: "json", "plist", "yaml", ... (optional, default: json)
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
desired = smart_merge(managed_global, managed_<hostname>)
```

Rules:

| Types | Result |
|---|---|
| dict + dict | recursive merge; local keys win on conflict |
| list + list | union of elements (deduplicated, sorted if possible) |
| anything + scalar | local wins |

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

### Array merge keys

For arrays of objects where elements are matched by identity rather than by
value or position, declare a merge key in `schema.json` via the `x-merge-key`
extension:

```json
{
  "properties": {
    "plugins": {
      "type": "array",
      "x-merge-key": "id"
    }
  }
}
```

With `x-merge-key: "id"`, global and local entries are matched by their `id`
field. Local entries override matching global entries; unmatched entries are
appended. New entries added by the app (unknown `id`) flow through Phase 2B.

Without a merge key, arrays are merged by value (union semantics).

See [docs/architecture.md](architecture.md) for the full schema design and
`x-merge-key` rationale. See [docs/examples/](examples/) for concrete configs.

## The three sync phases

Phases run in a fixed order on every sync.

### Phase 2A — Drift detection

For every path you own, custody compares the *desired* value against the
*current* value in the target. If they differ, custody overwrites the target
and records the drift for reporting.

Drift typically happens when:
- The value was changed on another machine and synced.
- The app modified a path it shouldn't have touched.

### Phase 2B — Unknown paths

custody walks the target and finds every path that is neither owned nor
ignored. For each one it calls the *adopt callback* (interactive by default):

| Option | Effect |
|---|---|
| Adopt globally | written to `managed_global` |
| Adopt locally | written to `managed_<hostname>` |
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
| `$` | JSON Path (RFC 9535) | `$.plugins[?(@.isBuiltin)]` |

Both syntaxes have *subtree semantics*: owning `/preferences` means owning
`/preferences` and all sub-paths beneath it.

JSON Path expressions are evaluated against the actual target document, enabling
filter expressions that select specific array elements by value.

## Schema

`schema.json` is a standard JSON Schema with one custody-specific extension:
`x-merge-key` on array properties. It is entirely optional.

### Schema roles

| Check | When | What it catches |
|---|---|---|
| Validate target | before sync | app changed its format unexpectedly |
| Validate result | after sync | bug in custody's own merge logic |
| Validate managed docs | before sync | typo in a path in managed_global |
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
generated one and proposes concrete changes to managed docs and `ignored_paths`.

## Hooks

`pre_sync.sh` and `post_sync.sh` are executable shell scripts placed in the
config subdir. They run before and after the sync respectively.

Typical use case: apps that read config only at startup and write their full
in-memory state back on quit. The pre hook quits the app; the post hook
restarts it.

```sh
# pre_sync.sh
your-app --quit && sleep 2

# post_sync.sh
open -a YourApp
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
