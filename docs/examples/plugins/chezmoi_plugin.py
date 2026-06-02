"""chezmoi write-back plugin.

After custody writes a managed_*.json file (adoption or drift-accept), this
plugin reverse-substitutes resolved values back to chezmoi template syntax and
writes the result to the chezmoi source directory.

Example: "/Users/michael/code/zk-prj" → "{{ .chezmoi.homeDir }}/code/zk-prj"

Registered in ~/.config/custody/customize.py:

    from chezmoi_plugin import ChezmoidPlugin
    pm.register(ChezmoidPlugin.from_chezmoi_data())

The substitution map is built once from `chezmoi data --format=json`.
Additional substitutions can be passed to the constructor.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from custody.hooks import hookimpl

_CUSTODY_CONFIG_DIR = Path.home() / ".config" / "custody"


class ChezmoidPlugin:
    def __init__(self, substitutions: dict[str, str]) -> None:
        # {resolved_value: template_expression}, longest keys matched first
        self._subs = dict(sorted(substitutions.items(), key=lambda x: -len(x[0])))

    @classmethod
    def from_chezmoi_data(
        cls, extra: dict[str, str] | None = None
    ) -> ChezmoidPlugin:
        """Build from `chezmoi data`. Extend with extra substitutions if needed."""
        result = subprocess.run(
            ["chezmoi", "data", "--format=json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout).get("chezmoi", {})
        subs: dict[str, str] = {}
        if "homeDir" in data:
            subs[data["homeDir"]] = "{{ .chezmoi.homeDir }}"
        if "hostname" in data:
            subs[data["hostname"]] = "{{ .chezmoi.hostname }}"
        if extra:
            subs.update(extra)
        return cls(subs)

    @hookimpl
    def after_managed_file_written(
        self, config_name: str, file_path: Path, scope: str
    ) -> None:
        content = file_path.read_text()
        templated = self._templatize(content)
        source = self._source_path(file_path)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(templated)

    # ------------------------------------------------------------------

    def _templatize(self, content: str) -> str:
        for value, template in self._subs.items():
            content = content.replace(value, template)
        return content

    def _source_path(self, file_path: Path) -> Path:
        """Map deployed managed file path to chezmoi source path.

        ~/.config/custody/foo/managed_global.json
            → <chezmoi-source>/dot_config/custody/foo/managed_global.json.tmpl
        """
        result = subprocess.run(
            ["chezmoi", "source-path"],
            capture_output=True, text=True, check=True,
        )
        source_dir = Path(result.stdout.strip())
        rel = file_path.relative_to(Path.home() / ".config")
        return source_dir / "dot_config" / rel.parent / (rel.name + ".tmpl")
