import pytest
from custody.segments import (
    PathSegments,
    delete_at,
    get_at,
    is_prefix,
    leaf_paths,
    parse_pointer,
    set_at,
    to_jsonpath_wildcard,
    to_pointer,
    walk,
)


class TestParsePointer:
    def test_root(self):
        assert parse_pointer("") == ()

    def test_single_key(self):
        assert parse_pointer("/foo") == ("foo",)

    def test_nested(self):
        assert parse_pointer("/foo/bar/baz") == ("foo", "bar", "baz")

    def test_integer_token_stays_string(self):
        # Arrays are atomic — integer tokens are not converted to int
        assert parse_pointer("/foo/0/bar") == ("foo", "0", "bar")

    def test_rfc6901_tilde_escape(self):
        assert parse_pointer("/a~0b") == ("a~b",)

    def test_rfc6901_slash_escape(self):
        assert parse_pointer("/a~1b") == ("a/b",)

    def test_escape_order(self):
        # ~01 must decode to ~1, not /
        assert parse_pointer("/a~01b") == ("a~1b",)

    def test_empty_key(self):
        assert parse_pointer("/") == ("",)

    def test_missing_leading_slash(self):
        with pytest.raises(ValueError):
            parse_pointer("foo/bar")


class TestToPointer:
    def test_root(self):
        assert to_pointer(()) == ""

    def test_single(self):
        assert to_pointer(("foo",)) == "/foo"

    def test_nested(self):
        assert to_pointer(("foo", "bar")) == "/foo/bar"

    def test_escape_tilde(self):
        assert to_pointer(("a~b",)) == "/a~0b"

    def test_escape_slash(self):
        assert to_pointer(("a/b",)) == "/a~1b"

    def test_roundtrip(self):
        for pointer in ("", "/foo", "/foo/bar", "/a~0b", "/a~1b"):
            assert to_pointer(parse_pointer(pointer)) == pointer


class TestIsPrefix:
    def test_equal_is_prefix(self):
        assert is_prefix(("foo",), ("foo",))

    def test_strict_prefix(self):
        assert is_prefix(("foo",), ("foo", "bar"))

    def test_not_prefix(self):
        assert not is_prefix(("foo",), ("bar",))

    def test_longer_not_prefix(self):
        assert not is_prefix(("foo", "bar"), ("foo",))

    def test_root_prefix_of_everything(self):
        assert is_prefix((), ("foo", "bar"))

    def test_root_prefix_of_root(self):
        assert is_prefix((), ())


class TestGetAt:
    def test_root(self):
        doc = {"a": 1}
        assert get_at(doc, ()) == {"a": 1}

    def test_nested(self):
        doc = {"a": {"b": 42}}
        assert get_at(doc, ("a", "b")) == 42

    def test_list_value(self):
        doc = {"items": [1, 2, 3]}
        assert get_at(doc, ("items",)) == [1, 2, 3]

    def test_missing_key(self):
        with pytest.raises(KeyError):
            get_at({"a": 1}, ("b",))


class TestSetAt:
    def test_root_replacement(self):
        assert set_at({"a": 1}, (), {"b": 2}) == {"b": 2}

    def test_existing_key(self):
        result = set_at({"a": 1, "b": 2}, ("a",), 99)
        assert result == {"a": 99, "b": 2}

    def test_nested(self):
        doc = {"a": {"b": 1}}
        result = set_at(doc, ("a", "b"), 2)
        assert result == {"a": {"b": 2}}

    def test_new_key(self):
        result = set_at({"a": 1}, ("b",), 2)
        assert result == {"a": 1, "b": 2}

    def test_does_not_mutate(self):
        doc = {"a": {"b": 1}}
        set_at(doc, ("a", "b"), 99)
        assert doc == {"a": {"b": 1}}

    def test_non_dict_raises(self):
        with pytest.raises(TypeError):
            set_at([1, 2, 3], ("0",), 99)


class TestDeleteAt:
    def test_top_level(self):
        assert delete_at({"a": 1, "b": 2}, ("a",)) == {"b": 2}

    def test_nested(self):
        doc = {"a": {"b": 1, "c": 2}}
        assert delete_at(doc, ("a", "b")) == {"a": {"c": 2}}

    def test_missing_key_is_noop(self):
        doc = {"a": 1}
        assert delete_at(doc, ("b",)) == {"a": 1}

    def test_root_raises(self):
        with pytest.raises(ValueError):
            delete_at({"a": 1}, ())

    def test_does_not_mutate(self):
        doc = {"a": 1}
        delete_at(doc, ("a",))
        assert doc == {"a": 1}


class TestWalk:
    def test_scalar_value(self):
        result = list(walk({"a": 1}))
        assert ((), {"a": 1}) in result
        assert (("a",), 1) in result

    def test_nested_dict(self):
        doc = {"a": {"b": 2}}
        paths = {p for p, _ in walk(doc)}
        assert paths == {(), ("a",), ("a", "b")}

    def test_list_is_atomic(self):
        doc = {"items": [1, 2, 3]}
        paths = {p for p, _ in walk(doc)}
        # Must NOT contain ("items", 0) etc.
        assert paths == {(), ("items",)}

    def test_nested_list_not_traversed(self):
        doc = {"a": {"b": [{"c": 1}]}}
        paths = {p for p, _ in walk(doc)}
        assert ("a", "b") in paths
        assert ("a", "b", 0) not in paths


class TestLeafPaths:
    def test_flat_dict(self):
        assert set(leaf_paths({"a": 1, "b": 2})) == {("a",), ("b",)}

    def test_nested_dict(self):
        doc = {"a": {"b": 1, "c": 2}}
        assert set(leaf_paths(doc)) == {("a", "b"), ("a", "c")}

    def test_list_is_leaf(self):
        doc = {"items": [1, 2, 3]}
        assert set(leaf_paths(doc)) == {("items",)}

    def test_scalar_root(self):
        assert list(leaf_paths(42)) == [()]

    def test_list_root(self):
        assert list(leaf_paths([1, 2])) == [()]

    def test_empty_dict_is_leaf(self):
        assert list(leaf_paths({})) == [()]

    def test_mixed(self):
        doc = {"a": 1, "b": {"c": [1, 2]}}
        assert set(leaf_paths(doc)) == {("a",), ("b", "c")}


class TestToJsonpathWildcard:
    def test_plain_path(self):
        assert to_jsonpath_wildcard(("foo", "bar")) == "$.foo.bar"

    def test_single_key(self):
        assert to_jsonpath_wildcard(("foo",)) == "$.foo"

    def test_with_array_index(self):
        assert to_jsonpath_wildcard(("foo", 0, "bar")) == "$.foo[*].bar"

    def test_nested_array_indices(self):
        assert to_jsonpath_wildcard(("a", 0, "b", 1, "c")) == "$.a[*].b[*].c"

    def test_root(self):
        assert to_jsonpath_wildcard(()) == "$"
