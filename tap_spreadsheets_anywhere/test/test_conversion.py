from tap_spreadsheets_anywhere.conversion import (
    convert,
    count_sample,
    count_samples,
    generate_schema,
    pick_datatype,
)


class TestConverter:
    def test_convert(self):
        # none
        assert convert("") == (None, None)
        assert convert(None) == (None, None)

        # integers
        assert convert("1") == (1, "integer")
        assert convert("1058") == (1058, "integer")
        assert convert("-1") == (-1, "integer")

        # floats
        assert convert("1.0") == (1.0, "number")

        # dates
        assert convert("2017-01-01") == ("2017-01-01", "string")
        assert convert("2017-01-01", "date-time") == ("2017-01-01T00:00:00+00:00", "date-time")

        assert convert("2017-01-01T01:01:01+04:00") == ("2017-01-01T01:01:01+04:00", "string")
        assert convert("2017-01-01T01:01:01+04:00", "date-time") == (
            "2017-01-01T01:01:01+04:00",
            "date-time",
        )

        assert convert("2017-01-01T01:01") == ("2017-01-01T01:01", "string")
        assert convert("2017-01-01T01:01", "date-time") == ("2017-01-01T01:01:00+00:00", "date-time")

        # strings
        assert convert("4 o clock") == ("4 o clock", "string")

    def test_convert_objects(self):
        assert convert("{'k': 'v','k': 'v'}") == ("{'k': 'v','k': 'v'}", "string")
        assert convert({"k": "v"}) == ({"k": "v"}, "object")
        assert convert({"k": "v"}, "object") == ({"k": "v"}, "object")

    def test_count_sample(self):
        assert count_sample({"id": "1", "first_name": "Connor"}) == {
            "id": {"integer": 1},
            "first_name": {"string": 1},
        }

    def test_count_samples(self):
        assert count_samples([{"id": "1", "first_name": "Connor"}, {"id": "2", "first_name": "1"}]) == {
            "id": {"integer": 2},
            "first_name": {"string": 1, "integer": 1},
        }

    def test_pick_datatype(self):
        assert pick_datatype({"string": 1}) == "string"
        assert pick_datatype({"integer": 1}) == "integer"
        assert pick_datatype({"number": 1}) == "number"

        assert pick_datatype({"number": 1, "integer": 1}) == "number"

        assert pick_datatype({"string": 1, "integer": 1}) == "string"
        assert pick_datatype({"string": 1, "number": 1}) == "string"
        assert pick_datatype({}) == "string"

    def test_pick_datatype_objects(self):
        assert pick_datatype({"object": 1}) == "object"
        assert pick_datatype({"string": 1, "object": 1}) == "string"

    def test_generate_schema(self):
        assert generate_schema([{"id": "1", "first_name": "Connor"}, {"id": "2", "first_name": "1"}]) == {
            "id": {
                "type": ["null", "integer"],
            },
            "first_name": {
                "type": ["null", "string"],
            },
        }

        assert generate_schema([{"id": "1", "cost": "1"}, {"id": "2", "cost": "1.25"}]) == {
            "id": {
                "type": ["null", "integer"],
            },
            "cost": {
                "type": ["null", "number"],
            },
        }

        assert generate_schema(
            [
                {"id": "1", "cost": "1"},
                {"id": "2", "cost": "1"},
                {"id": "-3", "cost": "25"},
                {"id": "+4", "cost": "3.25"},
            ]
        ) == {
            "id": {
                "type": ["null", "integer"],
            },
            "cost": {
                "type": ["null", "number"],
            },
        }

        assert generate_schema([{"id": "1", "date": "2017-01-01"}, {"id": "2", "date": "2017-01-02"}]) == {
            "id": {
                "type": ["null", "integer"],
            },
            "date": {
                "type": ["null", "string"],
            },
        }

    def test_generate_schema_objects(self):
        assert generate_schema(
            [
                {"id": "1", "obj": {"date": "2017-01-01", "count": 100}},
                {"id": "2", "obj": {"date": "2017-01-01", "count": 0}},
            ]
        ) == {
            "id": {
                "type": ["null", "integer"],
            },
            "obj": {
                "type": ["null", "object"],
            },
        }
