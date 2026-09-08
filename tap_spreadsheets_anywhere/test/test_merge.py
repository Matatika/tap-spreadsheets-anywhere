from tap_spreadsheets_anywhere import merge_dicts


class TestDictionaryMerge:
    def test_merge_dicts(self):
        assert merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

        assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

        assert merge_dicts({"a": {"c": 1}}, {"a": {"d": 3}}) == {"a": {"c": 1, "d": 3}}
