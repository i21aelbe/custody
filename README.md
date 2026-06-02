# custody

**Partial-ownership manager for config files shared between you and your apps.**

## The problem

Many apps write their own config files at runtime. A dotfile manager like chezmoi cannot fully manage these files without overwriting values the app sets itself. custody solves this: you declare which JSON paths are *yours*, the rest belongs to the app.

```
~/.config/custody/claude-desktop/
  target              # path to the real config file
  managed_global.json # your settings, all machines
  managed_memac.json  # your settings, this machine only
  ignored_paths       # app-owned paths — never touched
```

custody keeps your paths in sync across machines. App-written paths are left alone.

## Install

```sh
uv tool install custody
```

## Usage

```sh
custody sync              # sync all configured targets
custody sync claude-desktop  # sync one target
custody init <name>       # set up a new managed config interactively
```

## How it works

For each configured target, custody runs three phases:

1. **Drift detection** — if a path you own has been changed (by you on another machine, or by the app accidentally), custody restores it and warns you.
2. **Unknown paths** — if the target contains paths that are neither owned nor ignored, custody asks what to do: adopt globally, adopt locally, ignore, or leave alone.
3. **Additive sync** — paths you own that are missing from the target are inserted. Existing values are never overwritten in this phase.

See [docs/concept.md](docs/concept.md) for a full explanation.

## Hooks

Place executable shell scripts in a config subdir to run before or after a sync:

```
~/.config/custody/sidebar/
  pre_sync.sh    # e.g. quit the app
  post_sync.sh   # e.g. restart the app
```

## Format support

- **JSON** — default
- **Binary Plist** — for macOS apps (e.g. Sidebar)

## Requirements

- Python 3.12+
- macOS (primary target; Linux/Windows support untested)
