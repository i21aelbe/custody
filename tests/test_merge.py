from custody.merge import merge_by_key, smart_merge


class TestSmartMerge:
    def test_scalar_override(self):
        assert smart_merge("a", "b") == "b"

    def test_scalar_base_none(self):
        assert smart_merge(None, 42) == 42

    def test_dict_merge_disjoint(self):
        assert smart_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_dict_override_existing(self):
        assert smart_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_dict_recursive(self):
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"b": 99}}
        assert smart_merge(base, override) == {"a": {"b": 99, "c": 2}}

    def test_dict_does_not_mutate(self):
        base = {"a": 1}
        smart_merge(base, {"b": 2})
        assert base == {"a": 1}

    def test_list_union(self):
        result = smart_merge([1, 2], [2, 3])
        assert set(result) == {1, 2, 3}

    def test_list_union_sorted(self):
        assert smart_merge([3, 1], [2]) == [1, 2, 3]

    def test_list_union_unsortable_preserves_order(self):
        # dicts are not sortable — order must be preserved
        a = [{"x": 1}]
        b = [{"x": 2}]
        result = smart_merge(a, b)
        assert {"x": 1} in result
        assert {"x": 2} in result

    def test_list_no_duplicates(self):
        assert smart_merge([1, 2], [1, 2]) == [1, 2]

    def test_override_wins_on_type_mismatch(self):
        assert smart_merge({"a": 1}, "string") == "string"

    def test_global_local_pattern(self):
        global_doc = {
            "theme": "dark",
            "allowed_dirs": ["/home"],
            "features": {"a": True, "b": False},
        }
        local_doc = {
            "allowed_dirs": ["/work"],
            "features": {"b": True},
        }
        result = smart_merge(global_doc, local_doc)
        assert result["theme"] == "dark"
        assert set(result["allowed_dirs"]) == {"/home", "/work"}
        assert result["features"] == {"a": True, "b": True}


class TestMergeByKey:
    def test_matching_element_merged(self):
        base = [{"id": "a", "value": 1}]
        override = [{"id": "a", "value": 2}]
        result = merge_by_key(base, override, "id")
        assert result == [{"id": "a", "value": 2}]

    def test_new_element_appended(self):
        base = [{"id": "a", "value": 1}]
        override = [{"id": "b", "value": 2}]
        result = merge_by_key(base, override, "id")
        assert len(result) == 2
        assert {"id": "a", "value": 1} in result
        assert {"id": "b", "value": 2} in result

    def test_base_element_without_match_kept(self):
        base = [{"id": "a"}, {"id": "b"}]
        override = [{"id": "a", "extra": True}]
        result = merge_by_key(base, override, "id")
        ids = [item["id"] for item in result]
        assert "a" in ids
        assert "b" in ids

    def test_merge_adds_fields(self):
        base = [{"id": "a", "x": 1}]
        override = [{"id": "a", "y": 2}]
        result = merge_by_key(base, override, "id")
        assert result == [{"id": "a", "x": 1, "y": 2}]

    def test_empty_base(self):
        override = [{"id": "a"}]
        result = merge_by_key([], override, "id")
        assert result == [{"id": "a"}]

    def test_empty_override(self):
        base = [{"id": "a"}]
        result = merge_by_key(base, [], "id")
        assert result == [{"id": "a"}]

    def test_null_key_value_treated_as_identity(self):
        # displayId: null is a valid identity in sidebarStyle
        base = [{"displayId": None, "color": "dark"}]
        override = [{"displayId": None, "color": "light"}]
        result = merge_by_key(base, override, "displayId")
        assert len(result) == 1
        assert result[0]["color"] == "light"

    def test_sidebar_style_pattern(self):
        global_styles = [{"displayId": None, "fontSize": 12}]
        local_styles = [
            {"displayId": "uuid-monitor-1", "fontSize": 14},
            {"displayId": None, "fontSize": 13},  # local overrides global default
        ]
        result = merge_by_key(global_styles, local_styles, "displayId")
        by_id = {item["displayId"]: item for item in result}
        assert by_id[None]["fontSize"] == 13
        assert by_id["uuid-monitor-1"]["fontSize"] == 14
