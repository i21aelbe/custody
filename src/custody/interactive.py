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
from custody.ownership import Resolution, SourceKind
from custody.segments import PathSegments, delete_at, get_at, to_jsonpath_wildcard, to_pointer


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


_RED    = "\033[31m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def show_diff(
    before: Any,
    after: Any,
    before_label: str = "managed",
    after_label: str = "target",
    show_header: bool = True,
) -> None:
    """Print a colored unified diff between two JSON-serialisable values."""
    def _to_lines(v: Any) -> list[str]:
        if v is None:
            return ["(absent)\n"]
        text = json.dumps(v, indent=2, ensure_ascii=False)
        return (text + "\n").splitlines(keepends=True)

    color = _supports_color()
    for line in difflib.unified_diff(
        _to_lines(before), _to_lines(after),
        fromfile=before_label, tofile=after_label,
    ):
        if not show_header and (
            line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@")
        ):
            continue
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


def _split_at_last_int(path: PathSegments) -> tuple[PathSegments, PathSegments]:
    """Split path at the last integer segment (array index).

    ("items", 0, "name") → (("items", 0), ("name",))
    Used to navigate to the array element and then work on the field within it.
    """
    last_int = max(i for i, s in enumerate(path) if isinstance(s, int))
    return path[: last_int + 1], path[last_int + 1:]


# ---------------------------------------------------------------------------
# Interactive dialog
# ---------------------------------------------------------------------------

def ask_unknown_path(
    path: PathSegments,
    value: Any,
    target_doc: Any,
    hostname: str,
) -> str:
    """Display an unknown path in context and prompt for a decision.

    For plain paths: diffs target-without-key → target (only the unknown
    key appears green). For list-of-dicts: shows first element as sample.
    For paths through array indices (int segment): shows value directly
    and offers only ignore (adopt is not supported at element-field level).

    Returns '1' (global), '2' (local), '3' (ignore), or 'r' (recurse).
    Raises Abort or _Skip.
    """
    is_subdict = isinstance(value, dict) and bool(value)
    is_list_of_dicts = (
        isinstance(value, list) and bool(value) and isinstance(value[0], dict)
    )
    is_array_elem = any(isinstance(s, int) for s in path)

    display_path = to_jsonpath_wildcard(path) if is_array_elem else to_pointer(path)
    if _supports_color():
        header = f"  {_BOLD}{_YELLOW}Unknown:{_RESET} {_BOLD}{display_path}{_RESET}"
    else:
        header = f"  Unknown: {display_path}"
    print(f"\n{header}")
    print()

    if is_array_elem:
        array_path, field_path = _split_at_last_int(path)
        first_elem = get_at(target_doc, array_path)
        elem_without = delete_at(first_elem, field_path)
        show_diff(
            _context_subtree(elem_without, field_path),
            _context_subtree(first_elem, field_path),
            show_header=False,
        )
    elif is_list_of_dicts:
        print(f"  [list of {len(value)} objects — first element:]")
        show_diff(None, value[0], show_header=False)
    else:
        target_without = delete_at(target_doc, path)
        show_diff(
            _context_subtree(target_without, path),
            _context_subtree(target_doc, path),
            show_header=False,
        )

    print()
    print()
    if not is_array_elem:
        print(f"  [1] adopt globally  — managed_global.json (all machines)")
        print(f"  [2] adopt locally   — managed_{hostname}.json (this machine)")
    print( "  [3] ignore          — add to ignored_paths (app-owned)")
    print()
    if is_list_of_dicts:
        print("  [r] recurse into first element — discover per-element fields")
    elif is_subdict:
        print("  [r] recurse         — decide on sub-keys individually")
    print( "  [s] skip            — ask again next run")
    print( "  [a] abort           — stop sync")

    if is_array_elem:
        valid = ("3", "r") if is_subdict else ("3",)
    elif is_subdict or is_list_of_dicts:
        valid = ("1", "2", "3", "r")
    else:
        valid = ("1", "2", "3")
    print(f"\n  [{'/'.join(valid)}/s/a]: ", end="", flush=True)
    while True:
        ch = getch().lower()
        if ch == "a":
            print("a")
            raise Abort()
        if ch == "s":
            print("s\n")  # extra blank lines before next Unknown block
            raise _Skip()
        if ch in valid:
            print(f"{ch}\n")  # extra blank lines before next Unknown block
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
    def callback(path: PathSegments, current_value: Any, target_doc: Any) -> Resolution | None:
        try:
            choice = ask_unknown_path(path, current_value, target_doc, hostname)
        except _Skip:
            return None

        if choice in ("1", "2"):
            scope = "global" if choice == "1" else hostname
            file_path = write_managed(config, scope, path, current_value)
            pm.hook.after_managed_file_written(
                config_name=config.name,
                file_path=file_path,
                scope=scope,
            )
            return Resolution(SourceKind.WRITE, current_value, f"managed_{scope}")

        if choice == "r":
            return Resolution(SourceKind.RECURSE, current_value, "recurse")

        # "3" ignore
        write_ignored(config, path)
        return Resolution(SourceKind.PASSTHROUGH, current_value, "ignored")

    return callback
