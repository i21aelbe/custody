import pytest
from custody.expressions import expand
from custody.segments import PathSegments

DOC = {
    "applicationConfigurations": [
        {"bundleId": "com.apple.Finder", "name": "Finder", "isSystem": True},
        {"bundleId": "com.apple.Safari", "name": "Safari", "isSystem": True},
        {"bundleId": "com.example.App", "name": "MyApp", "isSystem": False},
    ],
    "sidebarStyle": [
        {"displayId": None, "color": "dark"},
        {"displayId": "uuid-1", "color": "light"},
    ],
    "settings": {"theme": "dark", "fontSize": 12},
    "ignored": "app-owned",
}


class TestJsonPointer:
    def test_root(self):
        assert expand("", DOC) == {()}

    def test_simple_key(self):
        assert expand("/settings", DOC) == {("settings",)}

    def test_nested(self):
        assert expand("/settings/theme", DOC) == {("settings", "theme")}

    def test_array_key(self):
        assert expand("/applicationConfigurations", DOC) == {
            ("applicationConfigurations",)
        }

    def test_unknown_syntax_raises(self):
        with pytest.raises(ValueError, match="Unknown path expression syntax"):
            expand("settings.theme", DOC)


class TestJsonPath:
    def test_simple_field(self):
        assert expand("$.settings", DOC) == {("settings",)}

    def test_nested_field(self):
        assert expand("$.settings.theme", DOC) == {("settings", "theme")}

    def test_wildcard_all_elements(self):
        result = expand("$.applicationConfigurations[*]", DOC)
        assert result == {
            ("applicationConfigurations", 0),
            ("applicationConfigurations", 1),
            ("applicationConfigurations", 2),
        }

    def test_filter_by_value(self):
        result = expand(
            '$.applicationConfigurations[?(@.bundleId == "com.apple.Finder")]', DOC
        )
        assert result == {("applicationConfigurations", 0)}

    def test_filter_by_bool(self):
        result = expand("$.applicationConfigurations[?(@.isSystem == true)]", DOC)
        assert ("applicationConfigurations", 0) in result
        assert ("applicationConfigurations", 1) in result
        assert ("applicationConfigurations", 2) not in result

    def test_key_within_all_elements(self):
        result = expand("$.applicationConfigurations[*].name", DOC)
        assert result == {
            ("applicationConfigurations", 0, "name"),
            ("applicationConfigurations", 1, "name"),
            ("applicationConfigurations", 2, "name"),
        }

    def test_filter_existence_matches_null_value(self):
        # [?(@.displayId)] means "field exists", not "field is truthy"
        # displayId: null must match — it's a valid Sidebar identity
        result = expand("$.sidebarStyle[?(@.displayId)]", DOC)
        assert ("sidebarStyle", 0) in result  # displayId: null — field exists
        assert ("sidebarStyle", 1) in result  # displayId: "uuid-1"

    def test_no_match_returns_empty(self):
        result = expand("$.nonexistent", DOC)
        assert result == set()
