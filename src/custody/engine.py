"""Sync engine — the three phases of custody.

Phase order is fixed:
  2A — Drift: owned paths where target differs from desired → overwrite + warn
  2B — Unknown paths in target → interactive adopt dialog
  1  — Additive sync: owned paths missing from target → insert (never overwrite)

The engine works exclusively through OwnershipChain.resolve() — it has no
knowledge of individual handler types. New sources (transforms, etc.) integrate
by extending the chain, not by changing engine logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from custody.ownership import OwnershipChain, Resolution, SourceKind
from custody.segments import PathSegments, get_at, leaf_paths, set_at, walk


@dataclass
class DriftItem:
    path: PathSegments
    desired: Any
    actual: Any
    source: str


@dataclass
class SyncResult:
    drift_fixed: list[DriftItem] = field(default_factory=list)
    inserted: list[PathSegments] = field(default_factory=list)
    unknown: list[PathSegments] = field(default_factory=list)


# Signature: (path, current_value) → Resolution | None
# Return a Resolution to adopt the path, None to defer (recorded as unknown).
AdoptCallback = Callable[[PathSegments, Any], Resolution | None]


def _owned_write_paths(chain: OwnershipChain, doc: Any, target_doc: Any) -> list[tuple[PathSegments, Resolution]]:
    """Return all (path, resolution) pairs for WRITE-owned leaf paths in doc."""
    result = []
    for path in leaf_paths(doc):
        if not path:
            continue
        resolution = chain.resolve(path, target_doc)
        if resolution is not None and resolution.kind == SourceKind.WRITE:
            result.append((path, resolution))
    return result


def run_phase_2a(
    target: Any,
    chain: OwnershipChain,
    desired_doc: Any,
) -> tuple[Any, list[DriftItem]]:
    """Fix drift: overwrite target paths where actual value differs from desired.

    desired_doc is the merged global+local document — used to enumerate owned
    paths. The desired value comes from chain.resolve() (handler decides).
    """
    fixed: list[DriftItem] = []

    for path, resolution in _owned_write_paths(chain, desired_doc, target):
        try:
            actual = get_at(target, path)
        except (KeyError, TypeError):
            continue  # missing paths handled by Phase 1
        if actual != resolution.desired:
            target = set_at(target, path, resolution.desired)
            fixed.append(DriftItem(path, resolution.desired, actual, resolution.source))

    return target, fixed


def run_phase_2b(
    target: Any,
    chain: OwnershipChain,
    adopt_callback: AdoptCallback | None,
) -> tuple[Any, list[PathSegments]]:
    """Classify unknown paths via the adopt callback.

    Walks the target document and calls adopt_callback for each unclassified
    path. If the callback returns a Resolution, the handler's desired value is
    written; if it returns None, the path is recorded as still unknown.

    If adopt_callback is None (non-interactive run), all unknown paths are
    recorded without prompting.
    """
    unknown: list[PathSegments] = []

    for path, current_value in walk(target):
        if not path:
            continue
        if chain.resolve(path, target) is not None:
            continue  # already classified

        if adopt_callback is not None:
            resolution = adopt_callback(path, current_value)
            if resolution is not None and resolution.kind == SourceKind.WRITE:
                target = set_at(target, path, resolution.desired)
                continue
        unknown.append(path)

    return target, unknown


def run_phase_1(
    target: Any,
    chain: OwnershipChain,
    desired_doc: Any,
) -> tuple[Any, list[PathSegments]]:
    """Additive sync: insert owned paths that are missing from target.

    Never overwrites — only adds. Drift was already handled by Phase 2A.
    """
    inserted: list[PathSegments] = []

    for path, resolution in _owned_write_paths(chain, desired_doc, target):
        try:
            get_at(target, path)
        except (KeyError, TypeError):
            target = set_at(target, path, resolution.desired)
            inserted.append(path)

    return target, inserted


def sync(
    target: Any,
    chain: OwnershipChain,
    desired_doc: Any,
    adopt_callback: AdoptCallback | None = None,
) -> tuple[Any, SyncResult]:
    """Run all three phases and return the updated target and a result summary.

    desired_doc: smart_merge(global_doc, local_doc) — enumerates owned paths.
    adopt_callback: called for each UNKNOWN path in Phase 2B. None = non-interactive.
    """
    result = SyncResult()

    target, result.drift_fixed = run_phase_2a(target, chain, desired_doc)
    target, result.unknown = run_phase_2b(target, chain, adopt_callback)
    target, result.inserted = run_phase_1(target, chain, desired_doc)

    return target, result
