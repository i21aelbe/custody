"""custody CLI — entry point for all commands."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import socket

from custody.adapters import JsonAdapter, get_adapter
from custody.config import ConfigTarget, find_configs, write_pending
from custody.engine import SyncResult, sync
from custody.hooks import (
    CustomizeModule,
    hookimpl,
    load_customize_file,
    make_plugin_manager,
    scoped_plugins,
)
from custody.merge import smart_merge
from custody.ownership import OwnershipChain

_DEFAULT_CUSTODY_DIR = Path.home() / ".config" / "custody"


# ---------------------------------------------------------------------------
# Core sync hookimpl — registered per-config, performs the actual work
# ---------------------------------------------------------------------------

class _SyncCore:
    """Internal hookimpl that performs the actual sync for one config target.

    Registered into the plugin manager for the duration of each config's sync,
    so external wrapper plugins surround the real work via yield.
    """

    def __init__(self, config: ConfigTarget, adapter, pm, adopt_callback=None) -> None:
        self._config = config
        self._adapter = adapter
        self._pm = pm
        self._adopt_callback = adopt_callback
        self.last_result: SyncResult | None = None

    @hookimpl(trylast=True)  # innermost — runs after all wrapper setup
    def custody_sync(self, config_name: str, target_path: Path) -> None:
        target_doc = self._adapter.load(target_path)
        desired = smart_merge(self._config.global_doc, self._config.local_doc)
        chain = OwnershipChain.from_files(
            global_doc=self._config.global_doc,
            local_doc=self._config.local_doc,
            ignored_expressions=self._config.ignored_expressions,
            target_doc=target_doc,
        )

        updated_doc, result = sync(target_doc, chain, desired, self._adopt_callback)
        self.last_result = result

        if updated_doc != target_doc:
            self._adapter.save(target_path, updated_doc)
            self._pm.hook.after_target_written(
                config_name=config_name,
                target_path=target_path,
            )


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------

def _resolve_adapter(cm: CustomizeModule, config: ConfigTarget):
    if cm.adapter is not None:
        return cm.adapter
    return get_adapter(config.adapter)


def _sync_one(pm, config: ConfigTarget) -> None:
    from custody.interactive import Abort, build_adopt_callback

    if not config.target_path.exists():
        print(f"  {config.name}: target not found ({config.target_path}), skipping")
        return

    hostname = socket.gethostname()
    adopt_callback = (
        build_adopt_callback(config, pm, hostname) if sys.stdin.isatty() else None
    )

    cm = load_customize_file(config.customize_file) if config.customize_file.exists() else CustomizeModule()
    adapter = _resolve_adapter(cm, config)
    core = _SyncCore(config, adapter, pm, adopt_callback)
    pm.register(core)
    try:
        with scoped_plugins(pm, config.customize_file):
            pm.hook.custody_sync(
                config_name=config.name,
                target_path=config.target_path,
            )
        _report(config.name, core.last_result)
        write_pending(config, core.last_result.unknown if core.last_result else [])
    except Abort:
        print("\n  Sync aborted.")
        sys.exit(0)
    finally:
        pm.unregister(core)


def _report(config_name: str, result: SyncResult | None) -> None:
    if result is None:
        return
    parts = []
    if result.drift_fixed:
        parts.append(f"{len(result.drift_fixed)} drift fixed")
    if result.inserted:
        parts.append(f"{len(result.inserted)} inserted")
    if result.unknown:
        parts.append(f"{len(result.unknown)} unknown (deferred)")
    if parts:
        print(f"  {config_name}: {', '.join(parts)}")
    else:
        print(f"  {config_name}: up to date")


def cmd_sync(args, custody_dir: Path = _DEFAULT_CUSTODY_DIR) -> None:
    pm = make_plugin_manager()

    global_cm = load_customize_file(custody_dir / "customize.py") \
        if (custody_dir / "customize.py").exists() else CustomizeModule()
    for p in global_cm.plugins:
        pm.register(p)

    try:
        configs = find_configs(custody_dir)
        if args.name:
            configs = [c for c in configs if c.name == args.name]
            if not configs:
                print(f"custody: no config named '{args.name}'")
                sys.exit(1)

        for config in configs:
            _sync_one(pm, config)
    finally:
        for p in global_cm.plugins:
            pm.unregister(p)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="custody",
        description="Partial-ownership manager for config files.",
    )
    sub = parser.add_subparsers(dest="command")

    sync_p = sub.add_parser("sync", help="Sync all configured targets (or one by name)")
    sync_p.add_argument("name", nargs="?", help="Config name to sync (default: all)")

    args = parser.parse_args()

    if args.command == "sync":
        cmd_sync(args)
    else:
        parser.print_help()
