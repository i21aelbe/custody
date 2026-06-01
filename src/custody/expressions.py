"""Path expression evaluation for ignored_paths entries.

Expressions declare which paths in the target document belong to the app.
Dispatch is based on the expression string itself:

  "" or "/foo/bar"  → JSON Pointer (RFC 6901), always one concrete path
  "$..."            → JSON Path (RFC 9535), may match multiple paths

Both syntaxes return a set of PathSegments. Each returned path is the root of
a subtree — the expression covers that path and all its sub-paths (is_prefix
semantics in ownership classification).

Filter expressions require jsonpath_ng.ext (not the base jsonpath_ng module).
"""

from typing import Any

from custody.segments import PathSegments, parse_pointer


def expand(expression: str, document: Any) -> set[PathSegments]:
    """Expand a path expression against a document into a set of concrete paths."""
    if expression == "" or expression.startswith("/"):
        return {parse_pointer(expression)}
    elif expression.startswith("$"):
        return _expand_jsonpath(expression, document)
    else:
        raise ValueError(f"Unknown path expression syntax: {expression!r}")


def _expand_jsonpath(expression: str, document: Any) -> set[PathSegments]:
    from jsonpath_ng.ext import parse  # ext required for filter expressions [?(...)]
    from jsonpath_ng.jsonpath import Child, Fields, Index, Root

    def to_segments(path: Any) -> PathSegments:
        if isinstance(path, Root):
            return ()
        if isinstance(path, Fields):
            return (path.fields[0],)
        if isinstance(path, Index):
            return (path.indices[0],)
        if isinstance(path, Child):
            return to_segments(path.left) + to_segments(path.right)
        raise ValueError(f"Unsupported jsonpath_ng path node: {type(path).__name__}")

    expr = parse(expression)
    return {to_segments(match.full_path) for match in expr.find(document)}
