"""Read a custody config subdir from disk.

One ConfigTarget per managed config file:

    ~/.config/custody/<name>/
      target              # path to the real config file (relative to $HOME)
      managed_global.json # custody-owned, all machines
      managed_<host>.json # custody-owned, this machine (optional)
      ignored_paths       # one path expression per line; # comments allowed
      adapter             # format: "json", "plist", ... (optional, default: json)
      customize.py          # per-config plugin declarations (optional)
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from custody.segments import PathSegments

_DEFAULT_CUSTODY_DIR = Path.home() / ".config" / "custody"


@dataclass
class ConfigTarget:
    name: str
    target_path: Path
    config_dir: Path
    global_doc: Any
    local_doc: Any
    ignored_expressions: list[str]
    adapter: str
    customize_file: Path

    @classmethod
    def from_dir(
        cls, config_dir: Path, hostname: str | None = None
    ) -> ConfigTarget:
        """Read a config subdir and return a ConfigTarget.

        Raises FileNotFoundError if the `target` file is missing.
        Raises json.JSONDecodeError if a managed_*.json file is invalid.
        """
        if hostname is None:
            hostname = socket.gethostname()

        target_rel = (config_dir / "target").read_text().strip()
        target_path = Path.home() / target_rel

        global_file = config_dir / "managed_global.json"
        local_file = config_dir / f"managed_{hostname}.json"

        global_doc = json.loads(global_file.read_text()) if global_file.exists() else {}
        local_doc = json.loads(local_file.read_text()) if local_file.exists() else {}

        return cls(
            name=config_dir.name,
            target_path=target_path,
            config_dir=config_dir,
            global_doc=global_doc,
            local_doc=local_doc,
            ignored_expressions=_load_ignored_paths(config_dir / "ignored_paths"),
            adapter=_read_text_or(config_dir / "adapter", "json"),
            customize_file=config_dir / "customize.py",
        )


def find_configs(
    custody_dir: Path | None = None,
    hostname: str | None = None,
) -> list[ConfigTarget]:
    """Return all valid ConfigTargets found under custody_dir, sorted by name."""
    base = custody_dir or _DEFAULT_CUSTODY_DIR
    if not base.exists():
        return []
    return [
        ConfigTarget.from_dir(d, hostname)
        for d in sorted(base.iterdir())
        if d.is_dir() and (d / "target").exists()
    ]


def write_managed(
    config: ConfigTarget, scope: str, path: PathSegments, value: Any
) -> Path:
    """Write a path/value into a managed JSON file, creating it if absent.

    scope: "global" or a hostname string.
    Returns the path of the written file.
    """
    filename = "managed_global.json" if scope == "global" else f"managed_{scope}.json"
    file_path = config.config_dir / filename
    doc = json.loads(file_path.read_text()) if file_path.exists() else {}
    updated = _nested_set(doc, path, value)
    file_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n")
    return file_path


def write_ignored(config: ConfigTarget, path: PathSegments) -> None:
    """Append an expression to the ignored_paths file.

    Paths with integer segments (array indices) are written as JSON Path
    expressions with [*] wildcards so they match all elements, not just
    the positional index used during discovery:
      ("applicationConfigurations", 0, "lastLaunchDate")
        → $.applicationConfigurations[*].lastLaunchDate
    Plain paths are written as JSON Pointers.
    """
    from custody.segments import to_jsonpath_wildcard, to_pointer
    if any(isinstance(s, int) for s in path):
        expr = to_jsonpath_wildcard(path)
    else:
        expr = to_pointer(path)
    ignored_file = config.config_dir / "ignored_paths"
    existing = ignored_file.read_text() if ignored_file.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    ignored_file.write_text(existing + expr + "\n")


def write_pending(config: ConfigTarget, unknown: list[PathSegments]) -> None:
    """Write deferred paths to .pending, or delete it if there are none."""
    from custody.segments import to_pointer
    pending = config.config_dir / ".pending"
    if unknown:
        pending.write_text("\n".join(to_pointer(p) for p in unknown) + "\n")
    else:
        pending.unlink(missing_ok=True)


def _nested_set(doc: Any, path: PathSegments, value: Any) -> Any:
    """Return doc with value set at path, creating intermediate dicts as needed."""
    if not path:
        return value
    head, *tail = path
    if not isinstance(doc, dict):
        doc = {}
    result = dict(doc)
    result[head] = _nested_set(result.get(head, {}), tuple(tail), value)
    return result


def _load_ignored_paths(path: Path) -> list[str]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            result.append(line)
    return result


def _read_text_or(path: Path, default: str) -> str:
    return path.read_text().strip() if path.exists() else default
