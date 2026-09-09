import pyarrow as pa

from tap_spreadsheets_anywhere import format_handler
from tap_spreadsheets_anywhere.configuration import TableSpec

DATA_SCHEMA = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])


class TestGetArrowTable:
    def test_returns_none_for_non_csv_format(self):
        table_spec = TableSpec(
            path="file://./tap_spreadsheets_anywhere/test",
            pattern=".*no_errors\\.xlsx",
            format="excel",
        )
        uri = "file://./tap_spreadsheets_anywhere/test/excel_with_no_errors.xlsx"

        assert format_handler.get_arrow_table(table_spec, uri, DATA_SCHEMA) is None

    def test_returns_a_table_for_csv(self, tmp_path):
        csv_path = tmp_path / "sample.csv"
        csv_path.write_text("id,name\n1,Alice\n2,Bob\n")
        table_spec = TableSpec(format="csv")

        table = format_handler.get_arrow_table(table_spec, f"file://{csv_path}", DATA_SCHEMA)

        assert table is not None
        assert table.to_pylist() == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def test_falls_back_to_none_on_non_iso8601_native_timestamp(self, tmp_path):
        # This is exactly the "opt-in to arrow_native_timestamps, but the source data
        # isn't cleanly ISO-8601" case: the caller (file_utils.write_file) should fall
        # back to row-by-row processing for the file, not fail it outright.
        csv_path = tmp_path / "sample.csv"
        csv_path.write_text("id,d\n1,2020-01-01\n")
        json_schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "d": {"type": ["null", "string"], "format": "date-time"},
            }
        }
        from tap_spreadsheets_anywhere.arrow_batch import schema_to_arrow_schema

        data_schema = schema_to_arrow_schema(json_schema, arrow_native_timestamps=True)
        table_spec = TableSpec(format="csv", arrow_native_timestamps=True)

        assert format_handler.get_arrow_table(table_spec, f"file://{csv_path}", data_schema) is None
