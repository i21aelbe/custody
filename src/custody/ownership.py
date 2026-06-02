"""Ownership resolution via Chain of Responsibility.

Each Handler in the chain either claims a path (returning a Resolution) or
passes it along (returning None). The first claiming handler wins.

Adding a new ownership source = adding a new Handler to the chain.
Changing priority = reordering the chain.
Transformers = handlers that mutate PathRequest and return None.

Standard chain (highest priority first):
  IgnoredPathsHandler   → PASSTHROUGH (app owns, never touch)
  ManagedDocHandler     → WRITE (static value from a managed_*.json doc)
  ...future handlers (transforms, schema defaults, etc.)
  → None                → UNKNOWN (triggers interactive adopt dialog)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol, runtime_checkable

from custody.expressions import expand
from custody.segments import PathSegments, get_at, is_prefix, leaf_paths


class SourceKind(Enum):
    WRITE = auto()        # custody owns and writes the desired value
    PASSTHROUGH = auto()  # custody acknowledges but never modifies (ignored)
    RECURSE = auto()      # descend into children (user deferred the whole-dict decision)


@dataclass
class PathRequest:
    """Mutable request object passed through the chain.

    Transformer handlers may modify fields (e.g. normalise a path) and return
    None to let downstream handlers work on the updated request.
    """
    path: PathSegments
    target_doc: Any


@dataclass
class Resolution:
    """A handler's answer: I claim this path, here is what to do with it."""
    kind: SourceKind
    desired: Any    # value to write (WRITE) or current target value (PASSTHROUGH)
    source: str     # handler name, used for reporting and drift messages


@runtime_checkable
class Handler(Protocol):
    name: str

    def handle(self, request: PathRequest) -> Resolution | None:
        """Claim the path by returning a Resolution, or return None to pass along."""
        ...


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

@dataclass
class IgnoredPathsHandler:
    """Marks paths as PASSTHROUGH — the app owns them, custody never writes."""
    name: str
    _roots: set[PathSegments] = field(default_factory=set)

    @classmethod
    def from_expressions(
        cls, expressions: list[str], target_doc: Any, name: str = "ignored"
    ) -> IgnoredPathsHandler:
        roots: set[PathSegments] = set()
        for expr in expressions:
            roots |= expand(expr, target_doc)
        handler = cls(name=name)
        handler._roots = roots
        return handler

    def handle(self, request: PathRequest) -> Resolution | None:
        if any(is_prefix(root, request.path) for root in self._roots):
            try:
                current = get_at(request.target_doc, request.path)
            except (KeyError, TypeError):
                current = None
            return Resolution(SourceKind.PASSTHROUGH, current, self.name)
        return None


@dataclass
class ManagedDocHandler:
    """Owns paths present in a managed JSON document (managed_global/local.json).

    Paths are determined by walking the document structure; arrays are atomic.
    """
    name: str
    _doc: Any = field(default=None)
    _roots: set[PathSegments] = field(default_factory=set)

    @classmethod
    def from_doc(cls, doc: Any, name: str) -> ManagedDocHandler:
        handler = cls(name=name)
        handler._doc = doc
        handler._roots = {path for path in leaf_paths(doc) if path}
        return handler

    def handle(self, request: PathRequest) -> Resolution | None:
        if any(is_prefix(root, request.path) for root in self._roots):
            try:
                desired = get_at(self._doc, request.path)
            except (KeyError, TypeError):
                return None  # ancestor is owned but this exact path isn't in the doc
            return Resolution(SourceKind.WRITE, desired, self.name)
        return None


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

@dataclass
class OwnershipChain:
    """Ordered chain of handlers. First matching handler wins."""
    handlers: list[Handler] = field(default_factory=list)

    def resolve(self, path: PathSegments, target_doc: Any) -> Resolution | None:
        """Return the first Resolution from the chain, or None if unknown."""
        request = PathRequest(path=path, target_doc=target_doc)
        for handler in self.handlers:
            result = handler.handle(request)
            if result is not None:
                return result
        return None

    def is_unknown(self, path: PathSegments, target_doc: Any) -> bool:
        return self.resolve(path, target_doc) is None

    # ------------------------------------------------------------------
    # Convenience constructor for the standard file-based chain
    # ------------------------------------------------------------------

    @classmethod
    def from_files(
        cls,
        *,
        global_doc: Any,
        local_doc: Any,
        ignored_expressions: list[str],
        target_doc: Any,
    ) -> OwnershipChain:
        """Build the standard chain from the three custody source files.

        Chain order (highest priority first):
          1. ignored          — PASSTHROUGH
          2. managed_local    — WRITE
          3. managed_global   — WRITE
        """
        return cls(handlers=[
            IgnoredPathsHandler.from_expressions(
                ignored_expressions, target_doc, name="ignored"
            ),
            ManagedDocHandler.from_doc(local_doc, name="managed_local"),
            ManagedDocHandler.from_doc(global_doc, name="managed_global"),
        ])
