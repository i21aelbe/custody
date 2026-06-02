import json
import argparse
import pytest
from pathlib import Path

from custody.cli import cmd_sync, _report
from custody.engine import SyncResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_custody_dir(tmp_path):
    d = tmp_path / "custody"
    d.mkdir()
    return d


def make_config(custody_dir, name, *, target_content=None, global_doc=None,
                local_doc=None, hostname="testhost", ignored=None):
    d = custody_dir / name
    d.mkdir()

    target_file = custody_dir / f"{name}_target.json"
    if target_content is not None:
        target_file.write_text(json.dumps(target_content, indent=2))

    rel = target_file.relative_to(Path.home()) if target_file.is_relative_to(Path.home()) \
        else Path("..") / target_file  # fallback for tmp_path outside home

    # write target as absolute path workaround: store full path in target file
    # (target file normally stores path relative to $HOME, but in tests we use
    #  a helper that patches target resolution)
    (d / "target_abs").write_text(str(target_file))
    (d / "target").write_text(str(target_file.relative_to(Path.home()))
                               if target_file.is_relative_to(Path.home())
                               else _write_abs_target(d, target_file))

    if global_doc is not None:
        (d / "managed_global.json").write_text(json.dumps(global_doc))
    if local_doc is not None:
        (d / f"managed_{hostname}.json").write_text(json.dumps(local_doc))
    if ignored:
        (d / "ignored_paths").write_text("\n".join(ignored))
    return d, target_file


def _write_abs_target(config_dir, target_file):
    """Write an absolute path into target and patch ConfigTarget to use it."""
    (config_dir / "_abs_target").write_text(str(target_file))
    return str(target_file)  # stored as-is; config.py will prepend home, so use relative


# ---------------------------------------------------------------------------
# Simpler setup: use a fixture that creates configs with absolute target paths
# ---------------------------------------------------------------------------

@pytest.fixture
def custody_dir(tmp_path):
    return tmp_path / "custody"


def setup_config(custody_dir, name, *, target_json=None, global_doc=None,
                 local_doc=None, hostname="testhost", ignored=None):
    """Create a config subdir and a target file. Returns (config_dir, target_path)."""
    custody_dir.mkdir(exist_ok=True)
    config_dir = custody_dir / name
    config_dir.mkdir()

    target_path = custody_dir / f"{name}.json"
    if target_json is not None:
        target_path.write_text(json.dumps(target_json, indent=2) + "\n")

    # Store absolute path — ConfigTarget.from_dir prepends Path.home(),
    # so we store a path that's relative to home if possible, else use a
    # direct approach: monkeypatch target_path after loading.
    # Easiest: write a customize.py that patches nothing; instead we set
    # target relative to home (tests run on the developer's machine).
    # Simplest hack: just write the absolute path and accept that from_dir
    # will compute Path.home() / abs_path (which is wrong), so we test via
    # a patched version of cmd_sync that accepts custody_dir.
    (config_dir / "target").write_text(
        str(target_path.relative_to(Path.home()))
        if target_path.is_relative_to(Path.home())
        else str(target_path)
    )

    if global_doc is not None:
        (config_dir / "managed_global.json").write_text(json.dumps(global_doc))
    if local_doc is not None:
        (config_dir / f"managed_{hostname}.json").write_text(json.dumps(local_doc))
    if ignored:
        (config_dir / "ignored_paths").write_text("\n".join(ignored))

    return config_dir, target_path


# ---------------------------------------------------------------------------
# Tests use a patched ConfigTarget that resolves target_path absolutely
# ---------------------------------------------------------------------------

import custody.config as config_mod

@pytest.fixture(autouse=True)
def patch_target_resolution(monkeypatch, tmp_path):
    """Make ConfigTarget resolve target paths relative to tmp_path, not home."""
    original = config_mod.ConfigTarget.from_dir.__func__

    @classmethod  # type: ignore[misc]
    def patched(cls, config_dir, hostname=None):
        import socket
        if hostname is None:
            hostname = socket.gethostname()
        target_text = (config_dir / "target").read_text().strip()
        target_path = Path(target_text) if Path(target_text).is_absolute() \
            else tmp_path / target_text
        global_file = config_dir / "managed_global.json"
        local_file = config_dir / f"managed_{hostname}.json"
        import json as _json
        return cls(
            name=config_dir.name,
            target_path=target_path,
            config_dir=config_dir,
            global_doc=_json.loads(global_file.read_text()) if global_file.exists() else {},
            local_doc=_json.loads(local_file.read_text()) if local_file.exists() else {},
            ignored_expressions=config_mod._load_ignored_paths(config_dir / "ignored_paths"),
            adapter=config_mod._read_text_or(config_dir / "adapter", "json"),
            customize_file=config_dir / "customize.py",
        )

    monkeypatch.setattr(config_mod.ConfigTarget, "from_dir", patched)


def args(name=None):
    a = argparse.Namespace()
    a.name = name
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCmdSync:
    def test_inserts_missing_owned_path(self, custody_dir, tmp_path):
        target_path = tmp_path / "app.json"
        target_path.write_text(json.dumps({"existing": "value"}) + "\n")
        cd = custody_dir / "app"
        cd.mkdir(parents=True)
        (cd / "target").write_text(str(target_path))
        (cd / "managed_global.json").write_text(json.dumps({"newKey": "hello"}))

        cmd_sync(args(), custody_dir=custody_dir)

        result = json.loads(target_path.read_text())
        assert result["newKey"] == "hello"
        assert result["existing"] == "value"

    def test_fixes_drift(self, custody_dir, tmp_path):
        target_path = tmp_path / "app.json"
        target_path.write_text(json.dumps({"theme": "light"}) + "\n")
        cd = custody_dir / "app"
        cd.mkdir(parents=True)
        (cd / "target").write_text(str(target_path))
        (cd / "managed_global.json").write_text(json.dumps({"theme": "dark"}))

        cmd_sync(args(), custody_dir=custody_dir)

        assert json.loads(target_path.read_text())["theme"] == "dark"

    def test_no_write_when_up_to_date(self, custody_dir, tmp_path):
        target_path = tmp_path / "app.json"
        target_path.write_text(json.dumps({"theme": "dark"}) + "\n")
        mtime_before = target_path.stat().st_mtime
        cd = custody_dir / "app"
        cd.mkdir(parents=True)
        (cd / "target").write_text(str(target_path))
        (cd / "managed_global.json").write_text(json.dumps({"theme": "dark"}))

        cmd_sync(args(), custody_dir=custody_dir)

        assert target_path.stat().st_mtime == mtime_before

    def test_skips_missing_target_file(self, custody_dir, tmp_path, capsys):
        target_path = tmp_path / "missing.json"  # does not exist
        cd = custody_dir / "app"
        cd.mkdir(parents=True)
        (cd / "target").write_text(str(target_path))
        (cd / "managed_global.json").write_text(json.dumps({"k": "v"}))

        cmd_sync(args(), custody_dir=custody_dir)  # must not raise

        out = capsys.readouterr().out
        assert "skipping" in out

    def test_sync_by_name(self, custody_dir, tmp_path):
        t1 = tmp_path / "one.json"
        t1.write_text(json.dumps({}) + "\n")
        t2 = tmp_path / "two.json"
        t2.write_text(json.dumps({}) + "\n")

        for name, tpath in [("one", t1), ("two", t2)]:
            cd = custody_dir / name
            cd.mkdir(parents=True)
            (cd / "target").write_text(str(tpath))
            (cd / "managed_global.json").write_text(json.dumps({"key": name}))

        cmd_sync(args(name="one"), custody_dir=custody_dir)

        assert json.loads(t1.read_text())["key"] == "one"
        assert "key" not in json.loads(t2.read_text())  # two not synced

    def test_unknown_name_exits(self, custody_dir, tmp_path):
        custody_dir.mkdir(exist_ok=True)
        with pytest.raises(SystemExit) as exc:
            cmd_sync(args(name="nonexistent"), custody_dir=custody_dir)
        assert exc.value.code == 1

    def test_empty_custody_dir(self, custody_dir):
        custody_dir.mkdir()
        cmd_sync(args(), custody_dir=custody_dir)  # must not raise

    def test_ignored_paths_not_touched(self, custody_dir, tmp_path):
        target_path = tmp_path / "app.json"
        target_path.write_text(json.dumps({"runtime": "app-value", "theme": "light"}) + "\n")
        cd = custody_dir / "app"
        cd.mkdir(parents=True)
        (cd / "target").write_text(str(target_path))
        (cd / "managed_global.json").write_text(json.dumps({"theme": "dark"}))
        (cd / "ignored_paths").write_text("/runtime\n")

        cmd_sync(args(), custody_dir=custody_dir)

        result = json.loads(target_path.read_text())
        assert result["runtime"] == "app-value"  # ignored — not touched
        assert result["theme"] == "dark"          # owned — fixed


class TestReport:
    def test_up_to_date(self, capsys):
        _report("myapp", SyncResult())
        assert "up to date" in capsys.readouterr().out

    def test_drift_fixed(self, capsys):
        from custody.engine import DriftItem
        result = SyncResult(drift_fixed=[DriftItem(("k",), "a", "b", "global")])
        _report("myapp", result)
        assert "1 drift fixed" in capsys.readouterr().out

    def test_inserted(self, capsys):
        result = SyncResult(inserted=[("k",)])
        _report("myapp", result)
        assert "1 inserted" in capsys.readouterr().out

    def test_unknown_deferred(self, capsys):
        result = SyncResult(unknown=[("k",)])
        _report("myapp", result)
        assert "1 unknown (deferred)" in capsys.readouterr().out
