# Example: Sidebar (macOS)

[Sidebar](https://sidebarapp.net) is a Dock replacement for macOS that stores
its configuration in a Binary Plist:

```
~/Library/Preferences/at.sidebar.Sidebar.plist
```

This is the first concrete use case custody was built for, and it exercises
most of custody's advanced features: Binary Plist adapter, hooks, merge keys,
and display-specific config via `managed_<hostname>.json`.

## Constraints (empirically verified)

- Sidebar reads config **only at startup** — changes while running have no effect
- On quit, Sidebar writes its **full in-memory state** back to the plist →
  any external edits made while Sidebar was running are silently overwritten
- No checksum or integrity check — custody can write freely
- **Sync window:** after quit (wait ~3s for writes to finish) and before restart
- The Finder Extension process stays alive after Sidebar quits and writes some
  keys periodically (~every 2 min) — the sync window must account for this

## Plist structure

Most values inside the Binary Plist are JSON-encoded bytes. The PlistAdapter
decodes these transparently so the engine sees a plain Python dict.

| Key | Type | Ownership |
|-----|------|-----------|
| `sidebarStyle` | JSON list (one entry per display) | custody — global + display-specific |
| `applicationConfigurations` | JSON list (~139 apps) | custody — global |
| `linkConfigurations` | JSON list | custody — global |
| `smartStackConfigurations` | JSON list | custody — global |
| `stackConfigurations` | JSON list | custody — global |
| `spacerConfigurations` | JSON list | custody — global |
| `launcherConfigurations` | JSON list | custody — global |
| `KeyboardShortcuts_*` | string (JSON) | custody — global |
| `sidebarSettings` | bytes (encrypted, License key) | **ignored — never touch** |
| `applicationStatistics` | JSON dict | ignored (app-managed runtime data) |
| `applicationWindowOrders` | JSON dict | ignored (app-managed runtime data) |
| `recentlyClosedApps` | JSON list | ignored (app-managed runtime data) |
| `hints` | JSON list | ignored (app-managed runtime data) |
| `NSWindow Frame *` | string | ignored (UI state) |
| `at.sidebar.Sidebar.tabWindow.size.*` | dict | ignored (display-specific UI state) |

## sidebarStyle — display-specific config

`sidebarStyle` is a list of style objects, one per display:

- `displayId: null` — default style for any display not explicitly listed
- `displayId: "UUID"` — override for a specific physical monitor

Each entry has ~110 fields (fully specified — no inheritance from the default
entry). Display UUIDs come from macOS IOKit/EDID and are stable per physical
monitor, independent of which machine it is connected to.

This maps naturally to custody's global/local split:
- `managed_global.json` — the `displayId: null` default entry (same everywhere)
- `managed_<hostname>.json` — display-specific entries for the monitors on that machine

Schema declaration:
```json
{
  "properties": {
    "sidebarStyle": {
      "type": "array",
      "x-merge-key": "displayId"
    },
    "applicationConfigurations": {
      "type": "array",
      "x-merge-key": "bundleId"
    }
  }
}
```

**Open question:** In "Individual" mode, does `displayId: null` act as a
fallback for unknown displays, or do they get factory defaults? Not empirically
verified.

**Universal Control artefact:** The macOS windowserver plist may contain
display UUIDs from monitors reachable via Universal Control from other Macs.
These are not reliable as "physically connected to this machine."

## Config subdir

```
~/.config/custody/sidebar/
  target              # Library/Preferences/at.sidebar.Sidebar.plist
  adapter             # plist
  managed_global.json # sidebarStyle default + applicationConfigurations + ...
  managed_memac.json  # sidebarStyle entries for monitors on this machine
  ignored_paths       # sidebarSettings, applicationStatistics, NSWindow Frame *, ...
  schema.json         # x-merge-key: bundleId, displayId
  pre_sync.sh         # quit Sidebar, wait for write-back
  post_sync.sh        # restart Sidebar
```

## Hooks

```sh
#!/bin/sh
# pre_sync.sh — quit Sidebar and wait for it to finish writing its state back
osascript -e 'tell application "Sidebar" to quit'
# Poll until the process is gone (max ~10s)
for i in $(seq 1 10); do
    pgrep -x "Sidebar" > /dev/null || break
    sleep 1
done
sleep 1  # extra buffer for the final plist write
```

```sh
#!/bin/sh
# post_sync.sh — restart Sidebar
open -a Sidebar
```
