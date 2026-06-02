import json
import pytest
from pathlib import Path

from custody.config import ConfigTarget, find_configs


def make_config_dir(tmp_path, name="myapp", *, target_rel=None, global_doc=None,
                    local_doc=None, hostname="testhost", ignored=None, adapter=None):
    d = tmp_path / name
    d.mkdir()
    (d / "target").write_text(target_rel or f".config/{name}/config.json")
    if global_doc is not None:
        (d / "managed_global.json").write_text(json.dumps(global_doc))
    if local_doc is not None:
        (d / f"managed_{hostname}.json").write_text(json.dumps(local_doc))
    if ignored is not None:
        (d / "ignored_paths").write_text("\n".join(ignored))
    if adapter is not None:
        (d / "adapter").write_text(adapter)
    return d


class TestConfigTargetFromDir:
    def test_reads_name_and_target(self, tmp_path):
        d = make_config_dir(tmp_path, name="myapp", target_rel="Library/Prefs/app.json")
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.name == "myapp"
        assert cfg.target_path == Path.home() / "Library/Prefs/app.json"

    def test_reads_global_doc(self, tmp_path):
        d = make_config_dir(tmp_path, global_doc={"key": "value"})
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.global_doc == {"key": "value"}

    def test_reads_local_doc_for_hostname(self, tmp_path):
        d = make_config_dir(tmp_path, local_doc={"local": 1}, hostname="myhost")
        cfg = ConfigTarget.from_dir(d, hostname="myhost")
        assert cfg.local_doc == {"local": 1}

    def test_local_doc_empty_when_other_hostname(self, tmp_path):
        d = make_config_dir(tmp_path, local_doc={"local": 1}, hostname="otherhost")
        cfg = ConfigTarget.from_dir(d, hostname="myhost")
        assert cfg.local_doc == {}

    def test_missing_global_doc_defaults_to_empty(self, tmp_path):
        d = make_config_dir(tmp_path)
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.global_doc == {}

    def test_missing_local_doc_defaults_to_empty(self, tmp_path):
        d = make_config_dir(tmp_path, global_doc={"k": 1})
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.local_doc == {}

    def test_reads_ignored_expressions(self, tmp_path):
        d = make_config_dir(tmp_path, ignored=["/runtime", "/hints", "# comment", ""])
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.ignored_expressions == ["/runtime", "/hints"]

    def test_missing_ignored_paths_defaults_to_empty(self, tmp_path):
        d = make_config_dir(tmp_path)
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.ignored_expressions == []

    def test_reads_adapter(self, tmp_path):
        d = make_config_dir(tmp_path, adapter="plist")
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.adapter == "plist"

    def test_missing_adapter_defaults_to_json(self, tmp_path):
        d = make_config_dir(tmp_path)
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.adapter == "json"

    def test_customize_file_path(self, tmp_path):
        d = make_config_dir(tmp_path, name="sidebar")
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.customize_file == d / "customize.py"

    def test_customize_file_path_regardless_of_existence(self, tmp_path):
        d = make_config_dir(tmp_path)
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert not cfg.customize_file.exists()  # path is set even if file is absent

    def test_missing_target_file_raises(self, tmp_path):
        d = tmp_path / "noapp"
        d.mkdir()
        with pytest.raises(FileNotFoundError):
            ConfigTarget.from_dir(d, hostname="h")

    def test_invalid_json_in_global_doc_raises(self, tmp_path):
        d = make_config_dir(tmp_path)
        (d / "managed_global.json").write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            ConfigTarget.from_dir(d, hostname="h")

    def test_config_dir_stored(self, tmp_path):
        d = make_config_dir(tmp_path)
        cfg = ConfigTarget.from_dir(d, hostname="h")
        assert cfg.config_dir == d


class TestFindConfigs:
    def test_returns_all_valid_subdirs(self, tmp_path):
        make_config_dir(tmp_path, name="aaa")
        make_config_dir(tmp_path, name="bbb")
        configs = find_configs(tmp_path, hostname="h")
        assert [c.name for c in configs] == ["aaa", "bbb"]

    def test_skips_dirs_without_target_file(self, tmp_path):
        make_config_dir(tmp_path, name="valid")
        (tmp_path / "nontarget").mkdir()
        configs = find_configs(tmp_path, hostname="h")
        assert [c.name for c in configs] == ["valid"]

    def test_skips_files(self, tmp_path):
        make_config_dir(tmp_path, name="app")
        (tmp_path / "customize.py").write_text("plugins = []")
        configs = find_configs(tmp_path, hostname="h")
        assert [c.name for c in configs] == ["app"]

    def test_empty_when_custody_dir_missing(self, tmp_path):
        configs = find_configs(tmp_path / "nonexistent", hostname="h")
        assert configs == []

    def test_sorted_by_name(self, tmp_path):
        make_config_dir(tmp_path, name="zzz")
        make_config_dir(tmp_path, name="aaa")
        configs = find_configs(tmp_path, hostname="h")
        assert [c.name for c in configs] == ["aaa", "zzz"]
