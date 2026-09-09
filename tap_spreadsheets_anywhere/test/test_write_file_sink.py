import json
from unittest.mock import patch

import pytest
from pyarrow import ipc

from tap_spreadsheets_anywhere import file_utils
from tap_spreadsheets_anywhere.arrow_batch import ArrowBatchWriter, BatchConfig
from tap_spreadsheets_anywhere.configuration import TableSpec
from tap_spreadsheets_anywhere.record_sink import SingerRecordSink

TABLE_SPEC = TableSpec(
    path="file://./does-not-matter",
    name="my_stream",
    format="csv",
)
SCHEMA = {"properties": {"id": {"type": ["null", "string"]}}}


class FakeSink:
    def __init__(self):
        self.written = []
        self.flushed = False

    def write(self, record):
        self.written.append(record)

    def flush(self):
        self.flushed = True


class TestWriteFileSink:
    def _rows(self, *rows):
        return patch.object(
            file_utils.tap_spreadsheets_anywhere.format_handler,
            "get_row_iterator",
            return_value=iter(rows),
        )

    def test_writes_each_row_to_the_provided_sink(self):
        sink = FakeSink()
        with self._rows({"id": "1"}, {"id": "2"}):
            records_synced = file_utils.write_file("f.csv", "2024-01-01T00:00:00Z", TABLE_SPEC, SCHEMA, sink=sink)

        assert records_synced == 2
        assert [r["id"] for r in sink.written] == ["1", "2"]
        assert sink.written[0]["_smart_source_file"] == "f.csv"

    def test_respects_max_records(self):
        sink = FakeSink()
        with self._rows({"id": "1"}, {"id": "2"}, {"id": "3"}):
            records_synced = file_utils.write_file(
                "f.csv",
                "2024-01-01T00:00:00Z",
                TABLE_SPEC,
                SCHEMA,
                max_records=2,
                sink=sink,
            )

        assert records_synced == 2
        assert len(sink.written) == 2

    def test_defaults_to_a_singer_record_sink_when_none_provided(self):
        calls = []
        with (
            self._rows({"id": "1"}),
            patch(
                "tap_spreadsheets_anywhere.record_sink.singer.write_record",
                side_effect=lambda stream, record: calls.append((stream, record)),
            ),
        ):
            records_synced = file_utils.write_file("f.csv", "2024-01-01T00:00:00Z", TABLE_SPEC, SCHEMA)

        assert records_synced == 1
        assert calls[0][0] == "my_stream"
        assert calls[0][1]["id"] == "1"

    def test_write_file_never_constructs_its_own_singer_record_sink_by_name(self):
        # Guards against the default sink silently swallowing errors: a broken
        # pipe from the sink should still propagate out of write_file.
        class BrokenPipeSink(SingerRecordSink):
            def write(self, record):
                raise BrokenPipeError()

        with self._rows({"id": "1"}), pytest.raises(BrokenPipeError):
            file_utils.write_file(
                "f.csv",
                "2024-01-01T00:00:00Z",
                TABLE_SPEC,
                SCHEMA,
                sink=BrokenPipeSink("my_stream"),
            )


class _ListOutput:
    """Minimal `arrow_batch.write_message` target: collects each written line."""

    def __init__(self):
        self.lines = []

    def write(self, data):
        self.lines.append(data)

    def flush(self):
        pass


class TestWriteFileArrowFastPath:
    """write_file's vectorized CSV fast path, exercised through a real ArrowBatchWriter
    (not a mock) against a real CSV file on disk - the mocked-sink tests above only cover
    the row-by-row path, since FakeSink isn't an ArrowBatchWriter."""

    def _table_spec(self, tmp_path, **overrides):
        return TableSpec(
            path=f"file://{tmp_path}",
            name="my_stream",
            format="csv",
            **overrides,
        )

    def _writer(self, tmp_path, schema, output, **table_spec_overrides):
        batch_config = BatchConfig(batch_size=100, batch_root_dir=str(tmp_path))
        table_spec = self._table_spec(tmp_path, **table_spec_overrides)
        writer = ArrowBatchWriter(
            "my_stream",
            schema,
            batch_config,
            arrow_native_timestamps=table_spec_overrides.get("arrow_native_timestamps", True),
            output=output,
        )
        return table_spec, writer

    def test_uses_the_fast_path_for_csv(self, tmp_path):
        (tmp_path / "f.csv").write_text("id,name\n1,Alice\n2,Bob\n")
        schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "name": {"type": ["null", "string"]},
                "_smart_source_bucket": {"type": "string"},
                "_smart_source_file": {"type": "string"},
                "_smart_source_lineno": {"type": "integer"},
                "_smart_source_last_modified": {"type": "string", "format": "date-time"},
            }
        }
        output = _ListOutput()
        table_spec, writer = self._writer(tmp_path, schema, output)

        with patch.object(file_utils.tap_spreadsheets_anywhere.format_handler, "get_row_iterator") as row_iterator:
            records_synced = file_utils.write_file("f.csv", "2024-01-01T00:00:00Z", table_spec, schema, sink=writer)

        row_iterator.assert_not_called()
        assert records_synced == 2

        writer.flush()
        message = json.loads(output.lines[0])
        manifest_path = message["manifest"][0].removeprefix("file://")
        with ipc.open_file(manifest_path) as reader:
            table = reader.read_all()
            assert table.column("id").to_pylist() == [1, 2]
            assert table.column("name").to_pylist() == ["Alice", "Bob"]
            assert table.column("_smart_source_file").to_pylist() == ["f.csv", "f.csv"]
            assert table.column("_smart_source_lineno").to_pylist() == [2, 3]

    def test_falls_back_to_row_by_row_when_pyarrow_cannot_parse(self, tmp_path):
        # A non-ISO-8601 date-time column with arrow_native_timestamps=True (the default)
        # can't be parsed by pyarrow's fast path - write_file should still succeed, via
        # the row-by-row fallback.
        (tmp_path / "f.csv").write_text("id,d\n1,2020-01-01\n")
        schema = {
            "properties": {
                "id": {"type": ["null", "integer"]},
                "d": {"type": ["null", "string"], "format": "date-time"},
                "_smart_source_bucket": {"type": "string"},
                "_smart_source_file": {"type": "string"},
                "_smart_source_lineno": {"type": "integer"},
                "_smart_source_last_modified": {"type": "string", "format": "date-time"},
            }
        }
        table_spec, writer = self._writer(tmp_path, schema, _ListOutput())

        records_synced = file_utils.write_file("f.csv", "2024-01-01T00:00:00Z", table_spec, schema, sink=writer)

        assert records_synced == 1
        assert len(writer._rows) == 1, "should have buffered via the row-by-row write(), not write_table()"
