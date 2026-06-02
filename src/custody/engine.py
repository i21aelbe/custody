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
from custody.segments import PathSegments, get_at, leaf_paths, set_at


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


# Signature: (path, current_value, current_target_doc) → Resolution | None
# Return a Resolution to adopt the path, None to skip (recorded as unknown).
AdoptCallback = Callable[[PathSegments, Any, Any], Resolution | None]


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


def _has_any_classified_descendant(
    doc: Any,
    base: PathSegments,
    target: Any,
    chain: OwnershipChain,
) -> bool:
    """Return True if any leaf path within doc is classified by the chain."""
    if not isinstance(doc, dict) or not doc:
        return chain.resolve(base, target) is not None
    return any(
        _has_any_classified_descendant(val, base + (key,), target, chain)
        for key, val in doc.items()
    )


def _classify_doc(
    doc: Any,
    base: PathSegments,
    target: Any,
    chain: OwnershipChain,
    adopt_callback: AdoptCallback | None,
    unknown: list[PathSegments],
) -> Any:
    """Recursively classify unknown paths in doc, starting from base.

    For entirely-unclassified dict paths (no child is managed):
      - Interactive: present to user with adopt/ignore/recurse options.
      - Non-interactive: recurse automatically, collect leaf unknowns.

    For partially-classified dict paths (some children already managed):
      - Always recurse — only ask about the unclassified children.
    """
    if not isinstance(doc, dict):
        return target
    for key, value in doc.items():
        path = base + (key,)
        if chain.resolve(path, target) is not None:
            continue  # already classified

        if isinstance(value, dict) and value:
            entirely_unknown = not _has_any_classified_descendant(
                value, path, target, chain
            )
            if entirely_unknown and adopt_callback is not None:
                resolution = adopt_callback(path, value, target)
                if resolution is None:
                    unknown.append(path)  # deferred — skip subtree
                elif resolution.kind == SourceKind.WRITE:
                    target = set_at(target, path, resolution.desired)
                elif resolution.kind == SourceKind.RECURSE:
                    target = _classify_doc(
                        value, path, target, chain, adopt_callback, unknown
                    )
                # PASSTHROUGH: ignored — skip subtree, not unknown
            else:
                # Partially classified, or non-interactive: recurse
                target = _classify_doc(
                    value, path, target, chain, adopt_callback, unknown
                )
        else:
            # Leaf: scalar, list, or empty dict
            if adopt_callback is None:
                unknown.append(path)
            else:
                resolution = adopt_callback(path, value, target)
                if resolution is None:
                    unknown.append(path)
                elif resolution.kind == SourceKind.WRITE:
                    target = set_at(target, path, resolution.desired)
                # PASSTHROUGH: ignored — not unknown
    return target


def run_phase_2b(
    target: Any,
    chain: OwnershipChain,
    adopt_callback: AdoptCallback | None,
) -> tuple[Any, list[PathSegments]]:
    """Classify unknown paths via the adopt callback.

    For entirely-unclassified dict-valued paths the callback may return
    RECURSE to descend into children, WRITE to adopt the whole subtree,
    PASSTHROUGH to ignore it, or None to defer.

    Non-interactive runs (adopt_callback=None) always recurse into dicts
    and collect every unknown leaf path.
    """
    unknown: list[PathSegments] = []
    target = _classify_doc(target, (), target, chain, adopt_callback, unknown)
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
