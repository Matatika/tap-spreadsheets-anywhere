import io

import pyarrow as pa
import pytest

from tap_spreadsheets_anywhere.arrow_batch import schema_to_arrow_schema
from tap_spreadsheets_anywhere.configuration import TableSpec
from tap_spreadsheets_anywhere.csv_handler import get_arrow_table


def _read(data: bytes, data_schema: pa.Schema, table_spec: TableSpec | None = None) -> pa.Table:
    table_spec = table_spec or TableSpec(format="csv")
    return get_arrow_table(table_spec, io.BytesIO(data), data_schema)


class TestGetArrowTable:
    def test_basic_types(self):
        data = b"id,name,cost\n1,Alice,1.5\n2,Bob,2.25\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string()), pa.field("cost", pa.float64())])

        table = _read(data, schema)

        assert table.column_names == ["id", "name", "cost"]
        assert table.to_pylist() == [
            {"id": 1, "name": "Alice", "cost": 1.5},
            {"id": 2, "name": "Bob", "cost": 2.25},
        ]

    def test_header_key_normalization_matches_row_path(self):
        # Mixed-case survives (only fully-uppercase headers get lowercased) - matching
        # excel_handler/csv_handler.generator_wrapper's shared _normalize_key semantics.
        data = b"id,Leaf Color,HEIGHT\n1,Red,549\n"
        schema = pa.schema(
            [pa.field("id", pa.int64()), pa.field("Leaf_Color", pa.string()), pa.field("height", pa.int64())]
        )

        table = _read(data, schema)

        assert table.column_names == ["id", "Leaf_Color", "height"]

    def test_empty_cell_becomes_null_regardless_of_column_type(self):
        data = b"id,name\n1,\n,Bob\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])

        table = _read(data, schema)

        assert table.to_pylist() == [{"id": 1, "name": None}, {"id": None, "name": "Bob"}]

    def test_literal_null_token_is_not_nulled(self):
        # pyarrow's default null_values list includes tokens like "NULL"/"NaN"; the tap
        # only ever treats a truly empty cell as null, so these must survive as text.
        data = b"id,note\n1,NULL\n2,NaN\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("note", pa.string())])

        table = _read(data, schema)

        assert table.column("note").to_pylist() == ["NULL", "NaN"]

    def test_skip_empty_rows(self):
        data = b"id,name\n1,Alice\n,\n2,Bob\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])
        table_spec = TableSpec(format="csv", skip_empty_rows=True)

        table = _read(data, schema, table_spec)

        assert table.to_pylist() == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def test_embedded_newline_in_quoted_value(self):
        data = b'id,note\n1,"line1\nline2"\n2,plain\n'
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("note", pa.string())])

        table = _read(data, schema)

        assert table.column("note").to_pylist() == ["line1\nline2", "plain"]

    def test_custom_delimiter_and_quotechar(self):
        data = b"id|name\n1|'Alice'\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])
        table_spec = TableSpec(format="csv", delimiter="|", quotechar="'")

        table = _read(data, schema, table_spec)

        assert table.to_pylist() == [{"id": 1, "name": "Alice"}]

    def test_field_names_override_with_no_header_row(self):
        data = b"1,Alice\n2,Bob\n"
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])
        table_spec = TableSpec(format="csv", field_names=["id", "name"])

        table = _read(data, schema, table_spec)

        assert table.to_pylist() == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def test_native_timestamp_column(self):
        data = b"id,d\n1,2020-01-01T00:00:00+00:00\n2,2020-06-15T12:30:00+00:00\n"
        json_schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "d": {"type": ["null", "string"], "format": "date-time"},
            }
        }
        schema = schema_to_arrow_schema(json_schema, arrow_native_timestamps=True)

        table = _read(data, schema)

        assert table.column("d").type == pa.timestamp("us")
        assert table.to_pylist()[0]["d"].isoformat() == "2020-01-01T00:00:00"

    def test_non_iso8601_timestamp_raises_for_caller_to_fall_back(self):
        data = b"id,d\n1,2020-01-01\n"
        json_schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "d": {"type": ["null", "string"], "format": "date-time"},
            }
        }
        schema = schema_to_arrow_schema(json_schema, arrow_native_timestamps=True)

        with pytest.raises(pa.lib.ArrowInvalid):
            _read(data, schema)

    def test_arrow_native_timestamps_false_keeps_raw_string(self):
        data = b"id,d\n1,01/02/2017\n"
        json_schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "d": {"type": ["null", "string"], "format": "date-time"},
            }
        }
        schema = schema_to_arrow_schema(json_schema, arrow_native_timestamps=False)

        table = _read(data, schema)

        assert table.column("d").type == pa.string()
        assert table.to_pylist() == [{"id": 1, "d": "01/02/2017"}]

    def test_empty_file_returns_zero_row_table_matching_schema(self):
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])

        table = _read(b"", schema)

        assert table.schema == schema
        assert table.num_rows == 0

    def test_column_not_in_schema_is_dropped_from_type_casting_but_still_present(self):
        # A column present in the file but absent from data_schema (e.g. sampled schema
        # missed it) keeps its inferred type rather than raising.
        data = b"id,extra\n1,hello\n"
        schema = pa.schema([pa.field("id", pa.int64())])

        table = _read(data, schema)

        assert set(table.column_names) == {"id", "extra"}
