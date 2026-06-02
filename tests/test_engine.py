import pytest
from custody.engine import DriftItem, SyncResult, run_phase_1, run_phase_2a, run_phase_2b, sync
from custody.merge import smart_merge
from custody.ownership import (
    IgnoredPathsHandler,
    ManagedDocHandler,
    OwnershipChain,
    Resolution,
    SourceKind,
)


def make_chain(global_doc, local_doc=None, ignored_exprs=None, target=None):
    local_doc = local_doc or {}
    ignored_exprs = ignored_exprs or []
    target = target or {}
    return OwnershipChain.from_files(
        global_doc=global_doc,
        local_doc=local_doc,
        ignored_expressions=ignored_exprs,
        target_doc=target,
    )


class TestPhase2A:
    def test_fixes_drifted_scalar(self):
        target = {"theme": "light", "other": "x"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        desired = smart_merge(global_doc, {})
        new_target, fixed = run_phase_2a(target, chain, desired)
        assert new_target["theme"] == "dark"
        assert len(fixed) == 1
        assert fixed[0].path == ("theme",)
        assert fixed[0].actual == "light"
        assert fixed[0].desired == "dark"

    def test_no_drift_no_change(self):
        target = {"theme": "dark"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        new_target, fixed = run_phase_2a(target, chain, global_doc)
        assert new_target == target
        assert fixed == []

    def test_missing_path_skipped(self):
        # missing paths are Phase 1 territory
        target = {"other": "x"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        new_target, fixed = run_phase_2a(target, chain, global_doc)
        assert "theme" not in new_target
        assert fixed == []

    def test_local_overrides_global_in_drift(self):
        target = {"fontSize": 10}
        global_doc = {"fontSize": 12}
        local_doc = {"fontSize": 14}
        chain = make_chain(global_doc, local_doc, target=target)
        desired = smart_merge(global_doc, local_doc)
        new_target, fixed = run_phase_2a(target, chain, desired)
        assert new_target["fontSize"] == 14
        assert fixed[0].source == "managed_local"

    def test_ignored_path_not_fixed(self):
        target = {"runtime": {"pid": 999}}
        global_doc = {}
        chain = make_chain(global_doc, ignored_exprs=["/runtime"], target=target)
        new_target, fixed = run_phase_2a(target, chain, global_doc)
        assert new_target["runtime"]["pid"] == 999
        assert fixed == []

    def test_does_not_mutate_original(self):
        target = {"theme": "light"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        run_phase_2a(target, chain, global_doc)
        assert target["theme"] == "light"


class TestPhase2B:
    def test_unknown_paths_recorded(self):
        target = {"theme": "dark", "unknown_key": "value"}
        chain = make_chain({"theme": "dark"}, target=target)
        _, unknown = run_phase_2b(target, chain, adopt_callback=None)
        assert ("unknown_key",) in unknown

    def test_known_paths_not_in_unknown(self):
        target = {"theme": "dark"}
        chain = make_chain({"theme": "dark"}, target=target)
        _, unknown = run_phase_2b(target, chain, adopt_callback=None)
        assert ("theme",) not in unknown

    def test_adopt_callback_called_for_unknown(self):
        target = {"theme": "dark", "new_key": "val"}
        chain = make_chain({"theme": "dark"}, target=target)
        seen = []

        def callback(path, value, target_doc):
            seen.append((path, value))
            return None  # skip

        run_phase_2b(target, chain, adopt_callback=callback)
        assert ("new_key",) in [p for p, _ in seen]

    def test_adopted_path_written(self):
        target = {"theme": "dark", "new_key": "old"}
        chain = make_chain({"theme": "dark"}, target=target)

        def callback(path, value, target_doc):
            if path == ("new_key",):
                return Resolution(SourceKind.WRITE, "new_value", "user")
            return None

        new_target, unknown = run_phase_2b(target, chain, adopt_callback=callback)
        assert new_target["new_key"] == "new_value"
        assert ("new_key",) not in unknown

    def test_ignored_path_not_in_unknown(self):
        target = {"runtime": {"pid": 1}}
        chain = make_chain({}, ignored_exprs=["/runtime"], target=target)
        _, unknown = run_phase_2b(target, chain, adopt_callback=None)
        assert ("runtime",) not in unknown
        assert ("runtime", "pid") not in unknown


class TestPhase1:
    def test_inserts_missing_key(self):
        target = {"other": "x"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        new_target, inserted = run_phase_1(target, chain, global_doc)
        assert new_target["theme"] == "dark"
        assert ("theme",) in inserted

    def test_does_not_overwrite_existing(self):
        target = {"theme": "light"}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        new_target, inserted = run_phase_1(target, chain, global_doc)
        assert new_target["theme"] == "light"
        assert inserted == []

    def test_ignored_not_inserted(self):
        target = {}
        global_doc = {}
        chain = make_chain(global_doc, ignored_exprs=["/runtime"], target=target)
        new_target, inserted = run_phase_1(target, chain, global_doc)
        assert "runtime" not in new_target

    def test_does_not_mutate_original(self):
        target = {}
        global_doc = {"theme": "dark"}
        chain = make_chain(global_doc, target=target)
        run_phase_1(target, chain, global_doc)
        assert target == {}


class TestSync:
    def test_full_sync(self):
        target = {
            "theme": "light",    # drift
            "runtime": {"pid": 1},  # ignored
            "extra": "unknown",  # unknown
                                 # "fontSize" missing → Phase 1
        }
        global_doc = {"theme": "dark", "fontSize": 12}
        chain = make_chain(global_doc, ignored_exprs=["/runtime"], target=target)
        desired = smart_merge(global_doc, {})

        new_target, result = sync(target, chain, desired)

        assert new_target["theme"] == "dark"        # drift fixed
        assert new_target["fontSize"] == 12         # inserted
        assert new_target["runtime"]["pid"] == 1    # passthrough, unchanged
        assert new_target["extra"] == "unknown"     # unknown, untouched
        assert len(result.drift_fixed) == 1
        assert len(result.inserted) == 1
        assert ("extra",) in result.unknown

    def test_non_interactive_defers_unknowns(self):
        target = {"known": "x", "unknown": "y"}
        chain = make_chain({"known": "x"}, target=target)
        _, result = sync(target, chain, {"known": "x"})
        assert ("unknown",) in result.unknown

    def test_phases_run_in_order(self):
        # Phase 2A fixes drift, Phase 1 adds missing
        # If order were reversed, Phase 1 would add the wrong value first
        target = {"a": "wrong"}
        global_doc = {"a": "right", "b": "new"}
        chain = make_chain(global_doc, target=target)
        new_target, result = sync(target, chain, global_doc)
        assert new_target["a"] == "right"
        assert new_target["b"] == "new"
        assert len(result.drift_fixed) == 1
        assert len(result.inserted) == 1
