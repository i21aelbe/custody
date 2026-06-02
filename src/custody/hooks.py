"""Pluggy hook specifications for custody.

Hook overview:

  custody_sync(config_name, target_path)
      Wrapper hook around a full sync for one config target.
      Use @hookimpl(wrapper=True) to run code before/after the sync.
      The core sync logic is itself a hookimpl — wrappers surround it.

  after_managed_file_written(config_name, file_path, scope)
      Called after custody writes a managed_*.json file — on adoption
      (Phase 2B) or drift-accept (Phase 2A). Use for write-back to external
      sources (e.g. chezmoi source dir).

  after_target_written(config_name, target_path)
      Called after custody writes the merged result back to the target file.
"""
from __future__ import annotations

from pathlib import Path

import pluggy

hookspec = pluggy.HookspecMarker("custody")
hookimpl = pluggy.HookimplMarker("custody")


class CustodySpec:
    @hookspec
    def custody_sync(self, config_name: str, target_path: Path) -> None:
        """Wrap a full sync for one config target.

        Implement with @hookimpl(wrapper=True) for setup/teardown around the
        actual sync. The core sync is itself a hookimpl in the same call chain,
        so yield passes control to it:

            @hookimpl(wrapper=True)
            def custody_sync(self, config_name, target_path):
                if config_name != "sidebar":
                    yield
                    return
                app_quit()
                try:
                    yield
                finally:
                    app_start()
        """

    @hookspec
    def after_managed_file_written(
        self, config_name: str, file_path: Path, scope: str
    ) -> None:
        """Called after custody writes a managed_*.json file.

        scope: "global" or a hostname string (matches the filename suffix).
        Called from config.py whenever an adoption or drift-accept causes a
        managed file to be updated on disk.
        """

    @hookspec
    def after_target_written(self, config_name: str, target_path: Path) -> None:
        """Called after custody writes the merged result back to the target."""


def make_plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager("custody")
    pm.add_hookspecs(CustodySpec)
    return pm


from dataclasses import dataclass, field


@dataclass
class CustomizeModule:
    plugins: list[object] = field(default_factory=list)
    adapter: object | None = None  # None → use default (JsonAdapter)


def load_customize_file(customize_file: Path) -> CustomizeModule:
    """Import a customize.py and extract plugins + adapter.

    The file may define:
        plugins = [SidebarPlugin(), ...]   # hook implementations
        adapter = PlistAdapter()           # target file format (optional)
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_custody_customize", customize_file)
    if spec is None or spec.loader is None:
        return CustomizeModule()
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return CustomizeModule(
        plugins=list(getattr(mod, "plugins", [])),
        adapter=getattr(mod, "adapter", None),
    )


from contextlib import contextmanager
from typing import Generator


@contextmanager
def scoped_plugins(
    pm: pluggy.PluginManager, customize_file: Path
) -> Generator[None, None, None]:
    """Register plugins from customize.py for the duration of the with-block.

    Usage:
        with scoped_plugins(pm, config_dir / "customize.py"):
            pm.hook.custody_sync(config_name=name, target_path=path)
    """
    cm = load_customize_file(customize_file) if customize_file.exists() else CustomizeModule()
    for p in cm.plugins:
        pm.register(p)
    try:
        yield
    finally:
        for p in cm.plugins:
            pm.unregister(p)
