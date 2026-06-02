"""Sidebar sync plugin — quit before, restart after.

Declared in ~/.config/custody/sidebar/customize.py:

    from sidebar_plugin import SidebarPlugin
    plugins = [SidebarPlugin()]
"""
from __future__ import annotations

import subprocess
import time

from custody.hooks import hookimpl


class SidebarPlugin:
    """Quit Sidebar before custody writes its config, restart afterwards.

    No config_name guard needed — this plugin is only loaded for the
    sidebar config dir via scoped_plugins().
    """

    @hookimpl(wrapper=True)
    def custody_sync(self, config_name: str, target_path):
        self._quit()
        try:
            yield
        finally:
            subprocess.run(["open", "-a", "Sidebar"], check=True)

    def _quit(self) -> None:
        subprocess.run(
            ["osascript", "-e", "tell application \"Sidebar\" to quit"],
            check=True,
        )
        for _ in range(10):
            if subprocess.run(["pgrep", "-x", "Sidebar"], capture_output=True).returncode != 0:
                break
            time.sleep(1)
        time.sleep(1)  # extra buffer for final plist write-back
