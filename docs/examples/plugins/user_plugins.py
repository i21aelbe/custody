"""Example plugin declarations.

Global:  ~/.config/custody/customize.py       — active for every config dir
Per-dir: ~/.config/custody/<name>/customize.py — active only for that sync

custody loads global plugins once at startup, then wraps each config's sync
with its per-dir plugins via scoped_plugins():

    pm = make_plugin_manager()
    load_global_plugins(pm)                            # register chezmoid etc.

    for config_dir in config_dirs:
        with scoped_plugins(pm, config_dir / "customize.py"):
            pm.hook.custody_sync(...)                  # per-dir plugins active here only
"""

# ~/.config/custody/customize.py  (global — runs for every config)
from chezmoi_plugin import ChezmoidPlugin

plugins = [ChezmoidPlugin.from_chezmoi_data()]


# ~/.config/custody/sidebar/customize.py  (only for sidebar)
# from sidebar_plugin import SidebarPlugin
# plugins = [SidebarPlugin()]


# ~/.config/custody/claude_desktop_config/customize.py  → not needed, no app lifecycle
