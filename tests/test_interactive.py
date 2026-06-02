import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from custody.config import ConfigTarget, write_managed, write_ignored, write_pending
from custody.interactive import Abort, ask_unknown_path, build_adopt_callback, _Skip
from custody.ownership import SourceKind


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    d = tmp_path / "myapp"
    d.mkdir()
    (d / "target").write_text(".config/myapp/config.json")
    (d / "managed_global.json").write_text("{}")
    return ConfigTarget(
        name="myapp",
        target_path=tmp_path / "config.json",
        config_dir=d,
        global_doc={},
        local_doc={},
        ignored_expressions=[],
        adapter="json",
        customize_file=d / "customize.py",
    )


class FakePM:
    """Minimal plugin manager stub that records hook calls."""
    def __init__(self):
        self.calls = []

    class _hook:
        pass

    def __getattr__(self, name):
        if name == "hook":
            return self
        if name == "after_managed_file_written":
            return lambda **kw: self.calls.append(("after_managed_file_written", kw))
        return super().__getattribute__(name)

    def after_managed_file_written(self, **kw):
        self.calls.append(("after_managed_file_written", kw))


@pytest.fixture
def pm():
    class PM:
        def __init__(self):
            self.calls = []
            self.hook = self

        def after_managed_file_written(self, **kw):
            self.calls.append(kw)

    return PM()


# ---------------------------------------------------------------------------
# ask_unknown_path
# ---------------------------------------------------------------------------

class TestAskUnknownPath:
    _target = {"preferences": {"theme": "light", "other": 1}}

    def _run(self, keys):
        key_iter = iter(keys)
        with patch("custody.interactive.getch", side_effect=key_iter):
            return ask_unknown_path(
                ("preferences", "theme"), "light",
                self._target, "testhost",
            )

    def test_returns_1_for_global(self, capsys):
        assert self._run(["1"]) == "1"

    def test_returns_2_for_local(self, capsys):
        assert self._run(["2"]) == "2"

    def test_returns_3_for_ignore(self, capsys):
        assert self._run(["3"]) == "3"

    def test_raises_abort_for_a(self):
        with patch("custody.interactive.getch", return_value="a"):
            with pytest.raises(Abort):
                ask_unknown_path(("k",), "v", {"k": "v"}, "testhost")

    def test_raises_skip_for_s(self):
        with patch("custody.interactive.getch", return_value="s"):
            with pytest.raises(_Skip):
                ask_unknown_path(("k",), "v", {"k": "v"}, "testhost")

    def test_bell_on_invalid_then_accepts_valid(self, capsys):
        assert self._run(["x", "y", "1"]) == "1"

    def test_shows_diff_in_output(self, capsys):
        self._run(["1"])
        out = capsys.readouterr().out
        assert "theme" in out  # unknown key appears as + in diff

    def test_only_unknown_key_is_addition(self, capsys):
        # "other" is in both target_with and target_without, so it's context, not +
        self._run(["1"])
        out = capsys.readouterr().out
        lines = out.splitlines()
        plus_lines = [l for l in lines if l.strip().startswith("+")]
        assert any("theme" in l for l in plus_lines)
        assert not any("other" in l for l in plus_lines)

    def test_no_file_header_in_output(self, capsys):
        self._run(["1"])
        out = capsys.readouterr().out
        assert "--- " not in out
        assert "+++ " not in out
        assert "@@" not in out

    def test_recurse_option_not_shown_for_scalar(self, capsys):
        with patch("custody.interactive.getch", return_value="1"):
            ask_unknown_path(("k",), "scalar", {"k": "scalar"}, "testhost")
        out = capsys.readouterr().out
        assert "[r]" not in out


class TestAskUnknownPathDict:
    _target = {"config": {"theme": "dark", "size": 12}}
    _value = {"theme": "dark", "size": 12}

    def _run(self, keys):
        with patch("custody.interactive.getch", side_effect=iter(keys)):
            return ask_unknown_path(("config",), self._value, self._target, "testhost")

    def test_returns_4_for_recurse(self):
        assert self._run(["r"]) == "r"

    def test_recurse_option_shown_for_dict(self, capsys):
        self._run(["r"])
        out = capsys.readouterr().out
        assert "[r]" in out
        assert "recurse" in out.lower()

    def test_4_invalid_for_scalar_then_accepts_1(self, capsys):
        with patch("custody.interactive.getch", side_effect=iter(["r", "1"])):
            result = ask_unknown_path(("k",), "scalar", {"k": "scalar"}, "testhost")
        assert result == "1"


# ---------------------------------------------------------------------------
# write_managed / write_ignored / write_pending
# ---------------------------------------------------------------------------

class TestWriteManaged:
    def test_creates_global_file(self, config):
        write_managed(config, "global", ("theme",), "dark")
        result = json.loads((config.config_dir / "managed_global.json").read_text())
        assert result["theme"] == "dark"

    def test_creates_local_file(self, config):
        write_managed(config, "myhostname", ("fontSize",), 14)
        result = json.loads((config.config_dir / "managed_myhostname.json").read_text())
        assert result["fontSize"] == 14

    def test_merges_into_existing(self, config):
        (config.config_dir / "managed_global.json").write_text(json.dumps({"existing": 1}))
        write_managed(config, "global", ("new",), "value")
        result = json.loads((config.config_dir / "managed_global.json").read_text())
        assert result["existing"] == 1
        assert result["new"] == "value"

    def test_nested_path(self, config):
        write_managed(config, "global", ("mcpServers", "obsidian", "command"), "npx")
        result = json.loads((config.config_dir / "managed_global.json").read_text())
        assert result["mcpServers"]["obsidian"]["command"] == "npx"

    def test_returns_file_path(self, config):
        path = write_managed(config, "global", ("k",), "v")
        assert path == config.config_dir / "managed_global.json"


class TestWriteIgnored:
    def test_creates_ignored_paths(self, config):
        (config.config_dir / "ignored_paths").unlink(missing_ok=True)
        write_ignored(config, ("runtime",))
        content = (config.config_dir / "ignored_paths").read_text()
        assert "/runtime" in content

    def test_appends_to_existing(self, config):
        (config.config_dir / "ignored_paths").write_text("/existing\n")
        write_ignored(config, ("new",))
        content = (config.config_dir / "ignored_paths").read_text()
        assert "/existing" in content
        assert "/new" in content


class TestWritePending:
    def test_writes_pending_when_unknowns(self, config):
        write_pending(config, [("runtime",), ("hints",)])
        content = (config.config_dir / ".pending").read_text()
        assert "/runtime" in content
        assert "/hints" in content

    def test_deletes_pending_when_empty(self, config):
        (config.config_dir / ".pending").write_text("old\n")
        write_pending(config, [])
        assert not (config.config_dir / ".pending").exists()

    def test_no_error_when_pending_missing(self, config):
        write_pending(config, [])  # should not raise


# ---------------------------------------------------------------------------
# build_adopt_callback
# ---------------------------------------------------------------------------

class TestBuildAdoptCallback:
    def test_global_adoption_writes_managed_global(self, config, pm):
        with patch("custody.interactive.getch", return_value="1"):
            cb = build_adopt_callback(config, pm, "myhostname")
            resolution = cb(("theme",), "dark", {"theme": "dark"})

        assert resolution is not None
        assert resolution.kind == SourceKind.WRITE
        assert resolution.desired == "dark"
        doc = json.loads((config.config_dir / "managed_global.json").read_text())
        assert doc["theme"] == "dark"

    def test_global_adoption_fires_hook(self, config, pm):
        with patch("custody.interactive.getch", return_value="1"):
            cb = build_adopt_callback(config, pm, "myhostname")
            cb(("theme",), "dark", {"theme": "dark"})

        assert len(pm.calls) == 1
        assert pm.calls[0]["scope"] == "global"
        assert pm.calls[0]["config_name"] == "myapp"

    def test_local_adoption_writes_managed_hostname(self, config, pm):
        with patch("custody.interactive.getch", return_value="2"):
            cb = build_adopt_callback(config, pm, "myhostname")
            cb(("fontSize",), 14, {"fontSize": 14})

        doc = json.loads((config.config_dir / "managed_myhostname.json").read_text())
        assert doc["fontSize"] == 14

    def test_local_adoption_fires_hook_with_hostname_scope(self, config, pm):
        with patch("custody.interactive.getch", return_value="2"):
            cb = build_adopt_callback(config, pm, "myhostname")
            cb(("k",), "v", {"k": "v"})

        assert pm.calls[0]["scope"] == "myhostname"

    def test_ignore_writes_ignored_paths(self, config, pm):
        with patch("custody.interactive.getch", return_value="3"):
            cb = build_adopt_callback(config, pm, "myhostname")
            resolution = cb(("runtime",), {"x": 1}, {"runtime": {"x": 1}})

        assert resolution.kind == SourceKind.PASSTHROUGH
        content = (config.config_dir / "ignored_paths").read_text()
        assert "/runtime" in content

    def test_skip_returns_none(self, config, pm):
        with patch("custody.interactive.getch", return_value="s"):
            cb = build_adopt_callback(config, pm, "myhostname")
            result = cb(("k",), "v", {"k": "v"})

        assert result is None

    def test_abort_propagates(self, config, pm):
        with patch("custody.interactive.getch", return_value="a"):
            cb = build_adopt_callback(config, pm, "myhostname")
            with pytest.raises(Abort):
                cb(("k",), "v", {"k": "v"})

    def test_recurse_returns_recurse_resolution(self, config, pm):
        dict_value = {"a": 1}
        with patch("custody.interactive.getch", return_value="r"):
            cb = build_adopt_callback(config, pm, "myhostname")
            resolution = cb(("nested",), dict_value, {"nested": dict_value})
        assert resolution is not None
        assert resolution.kind == SourceKind.RECURSE
