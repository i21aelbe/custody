"""PathSegments — canonical internal representation of a location in a JSON document.

Arrays are treated as atomic: walk() and leaf_paths() stop at lists and do not
recurse into individual elements. This matches the ownership semantics: you own
an array as a whole, not individual indices. Array-element-level ownership is
handled separately via merge keys (schema x-merge-key).
"""

from typing import Any, Iterator

PathSegments = tuple[str | int, ...]


def parse_pointer(pointer: str) -> PathSegments:
    """Parse a JSON Pointer (RFC 6901) into path segments.

    ""   → ()
    "/"  → ("",)       (key that is an empty string)
    "/foo/bar" → ("foo", "bar")
    "/foo/0"   → ("foo", "0")   NOTE: integer-looking tokens stay as strings —
                                 pointer arithmetic is on dicts only; array access
                                 is not part of the atomic-array model.
    """
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/' or be empty, got: {pointer!r}")
    parts = pointer[1:].split("/")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def to_pointer(segments: PathSegments) -> str:
    """Convert path segments back to a JSON Pointer string."""
    if not segments:
        return ""
    return "/" + "/".join(str(s).replace("~", "~0").replace("/", "~1") for s in segments)


def is_prefix(prefix: PathSegments, path: PathSegments) -> bool:
    """Return True if prefix is a prefix of (or equal to) path.

    Ownership semantics: owning /foo covers /foo and all sub-paths.
    """
    return path[: len(prefix)] == prefix


def get_at(doc: Any, segments: PathSegments) -> Any:
    """Retrieve the value at segments. Raises KeyError/TypeError if not found."""
    node = doc
    for seg in segments:
        node = node[seg]
    return node


def set_at(doc: Any, segments: PathSegments, value: Any) -> Any:
    """Return a new document with value set at segments (shallow-copies along the path).

    Does not recurse into lists — only dict traversal is supported, consistent
    with the atomic-array model.
    """
    if not segments:
        return value
    head, *tail = segments
    if not isinstance(doc, dict):
        raise TypeError(f"Expected dict at segment {head!r}, got {type(doc).__name__}")
    new_doc = dict(doc)
    existing = doc.get(head)  # type: ignore[arg-type]
    new_doc[head] = set_at(existing, tuple(tail), value)  # type: ignore[index]
    return new_doc


def delete_at(doc: Any, segments: PathSegments) -> Any:
    """Return a new document with the key at segments removed."""
    if not segments:
        raise ValueError("Cannot delete root")
    if len(segments) == 1:
        if not isinstance(doc, dict):
            raise TypeError(f"Expected dict, got {type(doc).__name__}")
        new_doc = dict(doc)
        new_doc.pop(segments[0], None)  # type: ignore[arg-type]
        return new_doc
    head, *tail = segments
    if not isinstance(doc, dict):
        raise TypeError(f"Expected dict at segment {head!r}, got {type(doc).__name__}")
    new_doc = dict(doc)
    new_doc[head] = delete_at(doc[head], tuple(tail))  # type: ignore[index]
    return new_doc


def walk(doc: Any, base: PathSegments = ()) -> Iterator[tuple[PathSegments, Any]]:
    """Yield (path, value) for every node in doc, depth-first.

    Stops recursing at lists — lists are yielded as atomic values.
    """
    yield base, doc
    if isinstance(doc, dict):
        for key, val in doc.items():
            yield from walk(val, base + (key,))


def leaf_paths(doc: Any, base: PathSegments = ()) -> Iterator[PathSegments]:
    """Yield paths of all leaf nodes (scalars and lists — not intermediate dicts)."""
    if isinstance(doc, dict):
        if not doc:
            yield base  # empty dict is a leaf
        else:
            for key, val in doc.items():
                yield from leaf_paths(val, base + (key,))
    else:
        yield base  # scalar or list: atomic leaf
