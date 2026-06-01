# custody

## Was ist custody?

Partial-ownership manager für Config-Dateien die von Apps UND vom User verwaltet werden.

Das Kernproblem: Tools wie Sidebar, Claude Desktop, VS Code schreiben ihre Config-Dateien selbst. Chezmoi kann diese Dateien nicht vollständig verwalten ohne App-eigene Werte zu überschreiben. custody löst das: du deklarierst welche JSON-Pfade "dir gehören" (global auf allen Rechnern, oder nur lokal), der Rest gehört der App.

**Langfristiges Ziel:** FOSS-Veröffentlichung auf PyPI als `custody`. Name auf PyPI noch nicht reserviert — tun wenn bereit.

## Ersetzt

`~/code/shell-tools/src/shell_tools/cz_partial_sync.py` — wird am Ende gelöscht wenn custody produktionsreif ist. Bis dahin: zero Aufwand in cz_partial_sync, kein Code-Sharing während Entwicklung. Konzepte und Algorithmen können übernommen werden.

## Kernkonzepte (aus cz_partial_sync geerbt und erweitert)

### Ownership-Modell

Jeder JSON-Pfad (JSON Pointer, RFC 6901) hat genau einen Owner:

| Quelle | Bedeutung |
|--------|-----------|
| `managed_global.json` | custody owned, alle Rechner |
| `managed_<hostname>.json` | custody owned, nur dieser Rechner |
| `ignored_paths` | App owned — nie anfassen |
| (keines) | unklassifiziert → interaktiv fragen |

### Phasen (Reihenfolge fix)

1. **Phase 2A** — Drift in owned Pfaden: desired vs. target abweichend → fix + warn
2. **Phase 2B** — Unklassifizierte Pfade im Target → interaktiver Adopt-Dialog
3. **Phase 1** — Additive Sync: fehlende owned Pfade ins Target schreiben (nie überschreiben)

### Merge-Semantik (global + hostname → desired)

- JSON Object: rekursiv, hostname ergänzt/überschreibt global
- JSON Array: Union (unique + sort)
- Scalar: hostname überschreibt global

### Interaktiver Dialog (Single-Keypress)

Bei unklassifizierten Pfaden: global übernehmen / nur lokal / App überlassen / skip / abort.
Skip-Persistenz: `.pending`-Datei → nächster Run fragt erneut.

## Geplante Erweiterungen gegenüber cz_partial_sync

### Pre/Post-Hooks

Optionale Shell-Scripts pro Config-Subdir:
- `pre_sync.sh` — vor dem Sync ausführen (z.B. App beenden)
- `post_sync.sh` — nach dem Sync (z.B. App neu starten)

Erster Use Case: Sidebar (Dock-Replacement für macOS) — muss vor dem Config-Write beendet und danach neu gestartet werden, weil er beim Quit seinen kompletten In-Memory-State zurückschreibt.

### Schema-Validierung (mit Pydantic)

Pro Config-Subdir: Pydantic-Modell das die erwartete Struktur der Zieldatei beschreibt.
Vor jedem Sync: Validierung. Bei Mismatch → Warnung "App hat sein Format geändert, re-engineering nötig" statt blindes Schreiben.

Pydantic ist ok hier (kein Symlink-Deployment-Problem wie bei cz_partial_sync — custody wird als echtes Package deployed).

### Format-Adapter

Zieldateien müssen nicht JSON sein. Adapter-Schicht für:
- **Binary Plist** (macOS): Sidebar, viele andere Mac-Apps
- JSON (Standard)
- Weitere nach Bedarf

Der Adapter konvertiert vor dem Sync zu JSON, danach zurück.

### Chezmoi-Entkopplung

cz_partial_sync ist tief mit chezmoi verknüpft (`_chezmoi_source_dir()`, onchange-Trigger).
custody soll chezmoi-agnostisch sein — chezmoi ist ein optionaler Adapter, nicht Voraussetzung.

## Erster konkreter Use Case: Sidebar (macOS)

Sidebar ist ein Dock-Replacement das seine Config in einem Binary Plist speichert:
`~/Library/Preferences/at.sidebar.Sidebar.plist`

### Empirisch ermittelte Rahmenbedingungen

- Sidebar liest Config **nur beim Start** (nicht während der Laufzeit)
- Beim Quit schreibt Sidebar **kompletten In-Memory-State** zurück → externe Änderungen werden überschrieben
- Kein Prüfsummen-/Integrity-Check
- **Sync-Fenster:** nach Quit (Writes abwarten, ~3s polling) und vor Neustart
- Finder-Extension-Prozess bleibt nach Quit aktiv, schreibt andere Keys periodisch (~alle 2 min)

### Plist-Struktur

Die meisten Werte sind JSON-Bytes innerhalb des Binary Plist:

| Key | Typ | Sync |
|-----|-----|------|
| `sidebarStyle` | JSON list (pro Display ein Eintrag) | global + display-spezifisch |
| `applicationConfigurations` | JSON list (139 Apps) | global |
| `linkConfigurations` | JSON list | global |
| `smartStackConfigurations` | JSON list | global |
| `stackConfigurations` | JSON list | global |
| `spacerConfigurations` | JSON list | global |
| `launcherConfigurations` | JSON list | global |
| `KeyboardShortcuts_*` | string (JSON) | global |
| `sidebarSettings` | bytes (encrypted, License) | **nie anfassen** |
| `applicationStatistics` | JSON dict | app-owned (runtime) |
| `applicationWindowOrders` | JSON dict | app-owned (runtime) |
| `recentlyClosedApps` | JSON list | app-owned (runtime) |
| `hints` | JSON list | app-owned (runtime) |
| `NSWindow Frame *` | string | app-owned (ui-state) |
| `at.sidebar.Sidebar.tabWindow.size.*` | dict | app-owned (display-spezifisch) |

### sidebarStyle — Besonderheit

Liste von Style-Einträgen, einer pro Display:
- `displayId: null` → Default (alle unbekannten Screens)
- `displayId: "UUID"` → Override für spezifischen Monitor

Jeder Eintrag hat ~110 Felder (vollständig, keine Vererbung). Display-UUIDs kommen aus dem
macOS IOKit/EDID — stabil pro physischem Monitor, unabhängig vom Rechner.

**Offene Frage:** Verhält sich `displayId: null` als Fallback für unbekannte Displays in
"Individual"-Modus, oder bekommen unbekannte Displays Factory-Defaults? Nicht empirisch
verifiziert — der Test wurde noch nicht durchgeführt.

**Universal Control Artefakt:** Der macOS windowserver-Plist enthält Display-UUIDs von
via UC erreichbaren Monitoren anderer Macs — kein verlässlicher Source für "physisch
angeschlossene Displays dieser Maschine".

## Deployment-Ziel

```
uv tool install custody        # installiert Binary ins System
custody sync                   # führt Sync für alle konfigurierten Targets aus
```

Kein Symlink-Deployment, kein venv-Bewusstsein beim Aufrufer nötig.
chezmoi-Trigger optional: `run_onchange_after_custody.sh.tmpl`

## Repository

GitHub: https://github.com/i21aelbe/custody
