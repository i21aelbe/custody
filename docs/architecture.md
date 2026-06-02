# custody — Architecture & Design Decisions

## Module overview

```
src/custody/
  segments.py      PathSegments type, JSON Pointer parsing, document navigation
  merge.py         smart_merge, merge_by_key
  expressions.py   Path expression dispatch (Pointer → JSON Path)
  ownership.py     Chain of Responsibility: handlers, chain, resolution
  engine.py        The three sync phases
  config.py        Read a custody config subdir                      [planned]
  adapters/        Format adapters: JSON, Binary Plist               [planned]
  schema.py        Generate, validate, x-merge-key extraction        [planned]
  cli.py           CLI entry point                                    [planned]
```

---

## PathSegments — internal path representation

`PathSegments = tuple[str | int, ...]`

All path syntaxes (JSON Pointer, JSON Path) resolve to this type internally.
String elements are dict keys; integer elements are array indices.

**Why a tuple, not a list?**
Tuples are hashable — `PathSegments` can be used as dict keys and in sets,
which is essential for the ownership roots (`set[PathSegments]`) and for
prefix matching.

**Why not use the `jsonpointer` library directly?**
`jsonpointer.resolve()` traverses into arrays (converting `"0"` to `int(0)`
to index the list). custody treats arrays as atomic in the managed-doc context
— managed docs declare ownership at the array level, not at individual element
indices. The library's semantics would be actively misleading here.
`jsonpath-ng` is used instead for JSON Path evaluation, which is where
array-index paths actually appear (in `expressions.py` results).

### Arrays: two layers, two semantics

Arrays are handled differently depending on which layer is involved:

**Path traversal layer (`segments.py`):** `walk()` and `leaf_paths()` stop
at lists and yield them as atomic values. This reflects how managed docs work:
when you include a list in `managed_global.json`, you are declaring ownership
of that entire list. The path traversal layer does not need to look inside.

**Merge layer (`merge.py`):** `merge_by_key()` does recurse into arrays —
matching elements by an identity field (`x-merge-key` from `schema.json`).
This is a separate concern from path traversal: the engine asks "does this
path exist in the managed doc?" (path layer, atomic), and separately "how
do we merge the two array values?" (merge layer, element-aware).

**Expression layer (`expressions.py`):** JSON Path expressions in
`ignored_paths` can return paths with integer array indices
(e.g. `("plugins", 0, "name")`). These paths are valid `PathSegments` and
work correctly with `is_prefix` matching — the path traversal layer's atomic
assumption does not apply here.

The three layers stay decoupled. Adding element-level ownership for a new
array only requires a merge key in `schema.json`, not changes to traversal.

---

## Chain of Responsibility — ownership resolution

`OwnershipChain` is an ordered list of `Handler` objects. Given a path and the
current target document, the chain calls each handler in order; the first one
that returns a `Resolution` wins.

```python
chain.resolve(path, target_doc) → Resolution | None
```

`None` means no handler claimed the path → UNKNOWN.

### Why Chain of Responsibility?

The alternative — an `Owner` enum (GLOBAL / LOCAL / IGNORED / UNKNOWN) — is a
closed set. Every new ownership source (transforms, schema defaults, computed
patches) would require adding a new enum value and a new branch in the engine.

With CoR:
- **Adding a source**: implement `Handler`, insert into chain. Engine unchanged.
- **Changing priority**: reorder the chain.
- **Transformer handlers**: a handler that mutates `PathRequest` and returns
  `None` passes a modified request to downstream handlers — no extra protocol
  needed.

### Handler protocol

```python
class Handler(Protocol):
    name: str
    def handle(self, request: PathRequest) -> Resolution | None: ...
```

`PathRequest` is mutable. A transformer handler may modify `request.path` or
add metadata, then return `None` to let the chain continue.

### Built-in handlers

| Handler | Kind | Claims |
|---|---|---|
| `IgnoredPathsHandler` | PASSTHROUGH | paths matching ignored_paths expressions |
| `ManagedDocHandler` | WRITE | leaf paths present in a managed JSON doc |

### Planned handlers

| Handler | Kind | Note |
|---|---|---|
| `TransformHandler` | WRITE | JSON Path → computed value (env vars, regex replace) |
| `SchemaDefaultsHandler` | WRITE | inject schema-defined defaults for missing paths |

### Standard chain (from_files)

```
priority 0  IgnoredPathsHandler("ignored")
priority 1  ManagedDocHandler("managed_local")
priority 2  ManagedDocHandler("managed_global")
```

Priorities are implicit in the list order — no numeric priority field is used.
The `from_files()` factory wires the standard chain; custom chains can be
built by constructing `OwnershipChain(handlers=[...])` directly.

---

## Path expression dispatch

`expressions.expand(expression, document) → set[PathSegments]`

The syntax is detected from the expression string:

| Prefix | Syntax | Library |
|---|---|---|
| `""` or `"/"` | JSON Pointer (RFC 6901) | custom (10 lines in `segments.py`) |
| `"$"` | JSON Path (RFC 9535 / Goessner) | `jsonpath-ng` (with `.ext` for filters) |

Both return a `set[PathSegments]`. JSON Pointer always returns a singleton set
(one concrete path); JSON Path may return many.

**Why not always JSON Path?**
JSON Pointer is simpler to write for the common case of ignoring a top-level
key or a simple nested path. JSON Path adds value when filter expressions are
needed. Both are supported; users choose per expression.

**Why `jsonpath-ng` and not `jsonpointer`?**
`jsonpath-ng` is required anyway for JSON Path filter expressions
(`[?(@.key == "value")]`). It uses `jsonpointer` as a transitive dependency.
Adding `jsonpointer` directly would be redundant.

---

## Transforms — planned extension

Transforms are a planned ownership source that assigns *computed* values to
paths matched by a JSON Path expression, rather than static values from a
managed doc.

**Motivating example**: 139 app entries in an array each contain an absolute
path with the current machine's home directory as a prefix. Rather than
listing all 139 entries in `managed_local.json`, a transform rule says:
*"for all elements, replace the home directory prefix with `$HOME`"*.

A new file `transforms_<hostname>.json` (or `transforms_global.json`) would
contain rules like:

```json
[
  {
    "path": "$.applicationConfigurations[*].executablePath",
    "transform": { "$replace": { "match": "^/Users/[^/]+", "with": "${HOME}" } }
  }
]
```

### Architectural slot

Transforms integrate as a `TransformHandler` inserted into the `OwnershipChain`
between `IgnoredPathsHandler` and `ManagedDocHandler` (higher priority than
static managed docs):

```
IgnoredPathsHandler
TransformHandler("transforms_local")    ← new
TransformHandler("transforms_global")   ← new
ManagedDocHandler("managed_local")
ManagedDocHandler("managed_global")
```

The engine does not change. `chain.resolve(path, target_doc)` returns a
`Resolution` with `kind=WRITE` and a computed `desired` value.

### Transform types (planned)

| Type | Description |
|---|---|
| `$env` | substitute environment variable: `{"$env": "HOME"}` |
| `$replace` | regex replace on current value |
| *(future)* | shell output, Python expression, etc. |

---

## Schema — three roles

`schema.json` is a JSON Schema (draft 7) stored in the config subdir.
It is entirely optional — custody works without it.

### 1. x-merge-key (merge semantics)

Custom extension on array properties. Replaces the separate `merge_keys` file
that was considered and rejected (same information, two sources of truth).

```json
{ "x-merge-key": "bundleId" }
```

When present, `merge_by_key(base, override, "bundleId")` is used instead of
atomic array replacement.

**Why in the schema?** The merge key is a *uniqueness constraint*: declaring
that `bundleId` is the merge key is equivalent to saying each element has a
unique `bundleId`. JSON Schema has no standard uniqueness-on-field keyword, but
`x-merge-key` encodes exactly this. The schema becomes the single source of
truth for both validation and merge semantics.

### 2. Change detection

Before every sync, the current target is validated against the schema. If
validation fails, custody warns and aborts rather than blindly merging into a
format it no longer understands.

### 3. Config validation

`managed_global.json`, `managed_<hostname>.json`, and `ignored_paths` entries
are validated against the schema before syncing — catching typos in path names
early, before they cause silent failures.

### Schema generation

`custody generate-schema <name>` reverse-engineers a schema from the current
target. It also detects merge-key candidates: array properties where one field
is unique across all elements. These are proposed interactively.

### Schema migration

When a schema check fails after an app update, `custody migrate <name>`:
1. Generates a new schema from the current target.
2. Diffs old schema vs. new schema.
3. Proposes concrete edits to managed docs and `ignored_paths`.

---

## Format adapters — planned

### Engine is format-agnostic

The sync engine (`engine.py`), merge logic (`merge.py`), ownership chain
(`ownership.py`), and path operations (`segments.py`) work exclusively on
Python types (`dict`, `list`, `str`, `int`, `float`, `bool`, `None`). They
make no assumptions about serialisation format. A dict is a dict whether it
was loaded from JSON, YAML, TOML, or a Binary Plist.

This is a deliberate constraint. Adding a new format = adding an adapter.
No engine code changes.

### Adapter protocol

```python
class Adapter(Protocol):
    def load(self, path: Path) -> Any: ...
    def save(self, path: Path, doc: Any) -> None: ...
```

Two `load`/`save` pairs are needed per config subdir:
1. **Target adapter** — loads the app's config file; saves the merged result back
2. **Managed doc adapter** — loads `managed_global.xxx` and `managed_<host>.xxx`

In most cases both use the same adapter (same format). Exception: binary formats
(see below).

### managed_global format matches the target

`managed_global.xxx` is a structural subset of the target — it mirrors the
target's format so values can be copy-pasted directly. If the target is YAML,
`managed_global.yaml` is YAML. If the target is JSON, `managed_global.json`
is JSON.

This keeps the authoring workflow frictionless: inspect the target, copy the
paths you want to own, paste into `managed_global.xxx`. No format translation.

### Comment preservation

Comments in config files have different status depending on the file:

**In the target** — comments were written by the user or the app and must be
preserved. The target adapter's `save()` must round-trip comments.

**In managed_global / managed_local** — comments are written by the custody
user to document ownership decisions (e.g. `# needed for MCP server`).
When Phase 2B adopts a new path and writes it into `managed_global.yaml`,
all existing comments in that file must be preserved. This is a correctness
requirement, not a nice-to-have: losing comments on the first adoption would
make YAML managed files unusable in practice.

Both target and managed file adapters must therefore support comment-preserving
round-trips. For YAML this requires `ruamel.yaml` — `pyyaml` is lossy and
not acceptable for either use.

**Comments are not propagated** from managed files into the target. There is
no "this value came from managed_global" annotation written into the target —
custody writes values only, not provenance metadata.

### Planned adapters

| Adapter | Format | Notes |
|---|---|---|
| `JsonAdapter` | JSON | default |
| `PlistAdapter` | Binary Plist | macOS; inner JSON-encoded byte values decoded |
| `YamlAdapter` | YAML | `ruamel.yaml` required (pyyaml is lossy — drops comments) |
| `TomlAdapter` | TOML | future |

### Binary formats: managed files stay human-writable

For binary formats (Plist, SQLite, etc.), `managed_global.xxx` cannot mirror
the binary format — it would be uneditable. Instead, managed files use JSON
(the logical structure after decoding). The PlistAdapter decodes the binary
plist and its inner JSON-encoded byte values into a plain Python dict; the
engine and managed files see only that dict.

Example: Sidebar's Binary Plist contains keys whose values are JSON-encoded
bytes. The PlistAdapter decodes these transparently. `managed_global.json`
contains the decoded structure. On save, the adapter re-encodes to Binary Plist.

---

## Plugin system

### Why pluggy

custody uses [pluggy](https://pluggy.readthedocs.io/) — the same hook framework
that powers pytest, tox, and devpi. It is small (~1k lines, no dependencies)
and provides exactly what is needed: hook specifications with multiple
implementations, wrapper hooks for setup/teardown, and ordered execution via
`tryfirst`/`trylast`.

**Rejected alternatives:**
- Shell scripts (`pre_sync.sh` / `post_sync.sh`) — cannot pass Python objects,
  cannot participate in the adoption lifecycle, no ordering guarantees across
  multiple scripts.
- String-based plugin declarations (`plugins` text file, one name per line) —
  cannot express constructor arguments (e.g. `ChezmoidPlugin.from_chezmoi_data()`),
  requires a separate plugin registry mechanism. Python code is sufficient.
- Numeric priority integers — pluggy's `tryfirst`/`trylast` combined with
  registration order covers all practical cases. A numeric system would add
  complexity without solving a real problem.

### Hook specifications

```python
custody_sync(config_name, target_path)          # wrapper — app lifecycle
after_managed_file_written(config_name, file_path, scope)  # write-back
after_target_written(config_name, target_path)  # post-write notification
```

`custody_sync` is a wrapper hook: the core sync logic is itself a hookimpl, so
plugins can surround it with setup/teardown via `yield`:

```python
@hookimpl(wrapper=True)
def custody_sync(self, config_name, target_path):
    app_quit()
    try:
        yield          # runs the sync (and any inner wrappers)
    finally:
        app_start()
```

### Two-level registration

Plugins are declared in plain Python files that define a `plugins` list:

```
~/.config/custody/customize.py          # global — active for every config
~/.config/custody/<name>/customize.py   # scoped — active only for that sync
```

The CLI registers global plugins once at startup, then wraps each config's sync
with its per-dir plugins via `scoped_plugins()` (a context manager that
registers on enter and unregisters on exit). This means a `SidebarPlugin` in
`sidebar/customize.py` never fires for `claude_desktop_config` — no `config_name`
guard needed inside the plugin.

**Ordering across levels:** per-dir plugins are registered after global plugins,
so they are outermost by default (LIFO). To pin a plugin's position regardless
of registration order, use `@hookimpl(wrapper=True, tryfirst=True)` (outermost)
or `trylast=True` (innermost).

**Installable plugins** (PyPI packages) register via entry points instead of
`customize.py`:

```toml
[project.entry-points."custody"]
chezmoi = "custody_chezmoi:ChezmoidPlugin"
```

### chezmoi write-back

`ChezmoidPlugin` (a separate package, not part of custody core) implements
`after_managed_file_written` and writes managed files back to the chezmoi source
directory with template variable substitution:

```
deployed:  "/Users/michael/code/zk-prj"
source:    "{{ .chezmoi.homeDir }}/code/zk-prj"
```

Substitution map is built once from `chezmoi data --format=json`. custody core
has no chezmoi knowledge.

---

## chezmoi decoupling

custody writes only to the deployed target file. chezmoi integration is opt-in:

```sh
# run_onchange_after_custody.sh.tmpl
custody sync
```

chezmoi triggers custody (rather than custody writing into chezmoi). This keeps
custody chezmoi-agnostic — it works the same whether chezmoi is present or not.
