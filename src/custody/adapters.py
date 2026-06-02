"""Format adapters — load and save target config files.

The engine works exclusively on Python objects (dict/list/str/int/...).
Adapters handle serialisation for a specific file format.

Adding a new format = adding an Adapter. Engine code unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Adapter(Protocol):
    def load(self, path: Path) -> Any: ...
    def save(self, path: Path, doc: Any) -> None: ...


class JsonAdapter:
    def load(self, path: Path) -> Any:
        return json.loads(path.read_text())

    def save(self, path: Path, doc: Any) -> None:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


_REGISTRY: dict[str, Adapter] = {
    "json": JsonAdapter(),
}


def get_adapter(name: str) -> Adapter:
    """Return a built-in adapter by name. Raises KeyError for unknown names."""
    return _REGISTRY[name]
