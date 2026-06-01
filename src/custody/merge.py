"""Merge logic for custody.

smart_merge: combines global + local managed docs into the desired state.
merge_by_key: array-level merge using an identity key (from schema x-merge-key).
"""

from typing import Any


def smart_merge(base: Any, override: Any) -> Any:
    """Merge override into base, returning the combined desired value.

    Rules (mirroring cz_partial_sync semantics):
      dict + dict  → recursive merge; override keys win on conflict
      list + list  → union (base items + override items not already in base)
      anything else → override wins
    """
    if isinstance(base, dict) and isinstance(override, dict):
        result = dict(base)
        for key, val in override.items():
            if key in result:
                result[key] = smart_merge(result[key], val)
            else:
                result[key] = val
        return result

    if isinstance(base, list) and isinstance(override, list):
        seen: list[Any] = list(base)
        for item in override:
            if item not in seen:
                seen.append(item)
        try:
            return sorted(seen)
        except TypeError:
            return seen

    return override


_MISSING = object()  # sentinel to distinguish "key absent" from "key present but None"


def merge_by_key(
    base: list[Any],
    override: list[Any],
    merge_key: str,
) -> list[Any]:
    """Merge two arrays using an identity key field.

    For each element in override:
      - If an element with the same merge_key value exists in base → smart_merge them
      - Otherwise → append to result (new element)
    Elements in base that have no counterpart in override are kept as-is.

    None is a valid identity value (e.g. sidebarStyle displayId: null for the default
    display entry). A sentinel distinguishes "key present, value None" from "key absent".

    Used when schema declares x-merge-key for an array path.
    """
    index: dict[Any, int] = {}
    result: list[Any] = []

    for i, item in enumerate(base):
        key_val = item.get(merge_key, _MISSING) if isinstance(item, dict) else _MISSING
        result.append(item)
        if key_val is not _MISSING:
            index[key_val] = i

    for item in override:
        key_val = item.get(merge_key, _MISSING) if isinstance(item, dict) else _MISSING
        if key_val is not _MISSING and key_val in index:
            result[index[key_val]] = smart_merge(result[index[key_val]], item)
        else:
            result.append(item)
            if key_val is not _MISSING:
                index[key_val] = len(result) - 1

    return result
