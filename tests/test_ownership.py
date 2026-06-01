import pytest
from custody.ownership import (
    IgnoredPathsHandler,
    ManagedDocHandler,
    OwnershipChain,
    PathRequest,
    Resolution,
    SourceKind,
)

TARGET = {
    "theme": "dark",
    "fontSize": 12,
    "plugins": ["a", "b"],
    "runtime": {"pid": 1234, "startedAt": "2026-01-01"},
    "applicationConfigurations": [
        {"bundleId": "com.apple.Finder", "path": "/Applications/Finder.app"},
        {"bundleId": "com.example.App", "path": "/Applications/App.app"},
    ],
}

GLOBAL_DOC = {"theme": "dark", "fontSize": 12}
LOCAL_DOC = {"fontSize": 14}
IGNORED_EXPRS = ["/runtime", "/plugins"]


class TestIgnoredPathsHandler:
    def setup_method(self):
        self.handler = IgnoredPathsHandler.from_expressions(IGNORED_EXPRS, TARGET)

    def test_claims_exact_path(self):
        r = self.handler.handle(PathRequest(("runtime",), TARGET))
        assert r is not None
        assert r.kind == SourceKind.PASSTHROUGH

    def test_claims_subpath(self):
        r = self.handler.handle(PathRequest(("runtime", "pid"), TARGET))
        assert r is not None
        assert r.kind == SourceKind.PASSTHROUGH

    def test_passthrough_returns_current_value(self):
        r = self.handler.handle(PathRequest(("runtime", "pid"), TARGET))
        assert r.desired == 1234

    def test_does_not_claim_other(self):
        r = self.handler.handle(PathRequest(("theme",), TARGET))
        assert r is None

    def test_jsonpath_filter(self):
        handler = IgnoredPathsHandler.from_expressions(
            ['$.applicationConfigurations[?(@.bundleId == "com.apple.Finder")]'],
            TARGET,
        )
        r = handler.handle(PathRequest(("applicationConfigurations", 0), TARGET))
        assert r is not None
        assert r.kind == SourceKind.PASSTHROUGH

    def test_jsonpath_does_not_claim_other_element(self):
        handler = IgnoredPathsHandler.from_expressions(
            ['$.applicationConfigurations[?(@.bundleId == "com.apple.Finder")]'],
            TARGET,
        )
        assert handler.handle(PathRequest(("applicationConfigurations", 1), TARGET)) is None


class TestManagedDocHandler:
    def setup_method(self):
        self.handler = ManagedDocHandler.from_doc(GLOBAL_DOC, "managed_global")

    def test_claims_owned_path(self):
        r = self.handler.handle(PathRequest(("theme",), TARGET))
        assert r is not None
        assert r.kind == SourceKind.WRITE
        assert r.source == "managed_global"

    def test_returns_desired_value(self):
        r = self.handler.handle(PathRequest(("fontSize",), TARGET))
        assert r.desired == 12

    def test_does_not_claim_unknown(self):
        r = self.handler.handle(PathRequest(("runtime",), TARGET))
        assert r is None


class TestOwnershipChain:
    def setup_method(self):
        self.chain = OwnershipChain.from_files(
            global_doc=GLOBAL_DOC,
            local_doc=LOCAL_DOC,
            ignored_expressions=IGNORED_EXPRS,
            target_doc=TARGET,
        )

    def test_ignored_wins(self):
        r = self.chain.resolve(("runtime",), TARGET)
        assert r.source == "ignored"
        assert r.kind == SourceKind.PASSTHROUGH

    def test_local_beats_global(self):
        # fontSize in both — local wins
        r = self.chain.resolve(("fontSize",), TARGET)
        assert r.source == "managed_local"
        assert r.desired == 14

    def test_global_only(self):
        r = self.chain.resolve(("theme",), TARGET)
        assert r.source == "managed_global"
        assert r.desired == "dark"

    def test_unknown_returns_none(self):
        assert self.chain.resolve(("applicationConfigurations",), TARGET) is None

    def test_is_unknown(self):
        assert self.chain.is_unknown(("applicationConfigurations",), TARGET)
        assert not self.chain.is_unknown(("theme",), TARGET)

    def test_chain_order_matters(self):
        # ignored has higher priority than managed — even if a path is in both
        chain = OwnershipChain(handlers=[
            IgnoredPathsHandler.from_expressions(["/theme"], TARGET),
            ManagedDocHandler.from_doc({"theme": "light"}, "managed_global"),
        ])
        r = chain.resolve(("theme",), TARGET)
        assert r.source == "ignored"

    def test_transformer_handler(self):
        # A handler that mutates the request and returns None passes modified
        # request to downstream handlers
        class NormalisingTransformer:
            name = "normaliser"

            def handle(self, request: PathRequest) -> Resolution | None:
                # rename "colour" → "theme" before downstream sees it
                if request.path == ("colour",):
                    request.path = ("theme",)
                return None

        chain = OwnershipChain(handlers=[
            NormalisingTransformer(),
            ManagedDocHandler.from_doc({"theme": "dark"}, "managed_global"),
        ])
        r = chain.resolve(("colour",), TARGET)
        assert r is not None
        assert r.source == "managed_global"
