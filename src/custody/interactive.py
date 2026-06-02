"""Interactive adopt dialog for Phase 2B unknown paths.

Only used when sys.stdin.isatty() is True. Non-interactive runs (no TTY,
CI, cron) pass adopt_callback=None to the engine and skip all unknowns.
"""
from __future__ import annotations

import difflib
import json
import sys
import termios
import tty
from typing import Any

from custody.config import ConfigTarget, write_ignored, write_managed
from custody.engine import AdoptCallback
from custody.merge import smart_merge
from custody.ownership import Resolution, SourceKind
from custody.segments import PathSegments, get_at, to_pointer


class Abort(Exception):
    pass


class _Skip(Exception):
    pass


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def getch() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


_RED   = "\033[31m"
_GREEN = "\033[32m"
_CYAN  = "\033[36m"
_RESET = "\033[0m"

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def show_diff(before: Any, after: Any, before_label: str = "managed", after_label: str = "target") -> None:
    """Print a colored unified diff between two JSON-serialisable values."""
    def _to_lines(v: Any) -> list[str]:
        if v is None:
            return ["(absent)\n"]
        return json.dumps(v, indent=2, ensure_ascii=False).splitlines(keepends=True)

    color = _supports_color()
    for line in difflib.unified_diff(
        _to_lines(before), _to_lines(after),
        fromfile=before_label, tofile=after_label,
    ):
        if color:
            if line.startswith("+") and not line.startswith("+++"):
                sys.stdout.write(f"  {_GREEN}{line}{_RESET}")
            elif line.startswith("-") and not line.startswith("---"):
                sys.stdout.write(f"  {_RED}{line}{_RESET}")
            elif line.startswith("@@"):
                sys.stdout.write(f"  {_CYAN}{line}{_RESET}")
            else:
                sys.stdout.write(f"  {line}")
        else:
            sys.stdout.write(f"  {line}")


def _context_subtree(doc: Any, path: PathSegments) -> Any:
    """Return the parent subtree of path, wrapped in its full key hierarchy.

    For path = ("preferences", "theme"):
      - navigates to doc["preferences"]
      - wraps result as {"preferences": <preferences dict>}

    This shows the unknown value in its surrounding context rather than in
    isolation, matching the cz_partial _subtree_at() approach.
    """
    parent = path[:-1]
    subtree: Any = doc
    for seg in parent:
        if not isinstance(subtree, dict) or seg not in subtree:
            return {}
        subtree = subtree[seg]
    result: Any = subtree
    for seg in reversed(parent):
        result = {seg: result}
    return result


# ---------------------------------------------------------------------------
# Interactive dialog
# ---------------------------------------------------------------------------

def ask_unknown_path(
    path: PathSegments,
    value: Any,
    target_doc: Any,
    desired_doc: Any,
    hostname: str,
) -> str:
    """Display an unknown path in context and prompt for a decision.

    Shows a diff of the parent subtree: desired (managed) → target.
    The unknown path appears green as an addition.

    Returns 'g' (global), 'l' (local), or 'i' (ignore).
    Raises Abort or _Skip.
    """
    pointer = to_pointer(path)
    print(f"\n  Unknown: {pointer}")
    show_diff(
        _context_subtree(desired_doc, path),
        _context_subtree(target_doc, path),
    )
    print()
    print(f"  [g] adopt globally  — managed_global.json (all machines)")
    print(f"  [l] adopt locally   — managed_{hostname}.json (this machine)")
    print( "  [i] ignore          — add to ignored_paths (app-owned)")
    print( "  [s] skip            — ask again next run")
    print( "  [a] abort           — stop sync")

    print(f"\n  [g/l/i/s/a]: ", end="", flush=True)
    while True:
        ch = getch().lower()
        if ch == "a":
            print("a")
            raise Abort()
        if ch == "s":
            print("s")
            raise _Skip()
        if ch in ("g", "l", "i"):
            print(ch)
            return ch
        print("\x07", end="", flush=True)  # bell on invalid key


# ---------------------------------------------------------------------------
# Adopt callback factory
# ---------------------------------------------------------------------------

def build_adopt_callback(config: ConfigTarget, pm, hostname: str) -> AdoptCallback:
    """Return an AdoptCallback that interactively classifies unknown paths.

    On adoption: writes to managed file + fires after_managed_file_written.
    On ignore:   writes to ignored_paths.
    On skip:     returns None (engine records path as still unknown).
    On abort:    raises Abort (propagates up through engine and CLI).
    """
    desired_doc = smart_merge(config.global_doc, config.local_doc)

    def callback(path: PathSegments, current_value: Any, target_doc: Any) -> Resolution | None:
        try:
            choice = ask_unknown_path(path, current_value, target_doc, desired_doc, hostname)
        except _Skip:
            return None

        if choice in ("g", "l"):
            scope = "global" if choice == "g" else hostname
            file_path = write_managed(config, scope, path, current_value)
            pm.hook.after_managed_file_written(
                config_name=config.name,
                file_path=file_path,
                scope=scope,
            )
            return Resolution(SourceKind.WRITE, current_value, f"managed_{scope}")

        else:  # ignore
            write_ignored(config, path)
            return Resolution(SourceKind.PASSTHROUGH, current_value, "ignored")

    return callback
