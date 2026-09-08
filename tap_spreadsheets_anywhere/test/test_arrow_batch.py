import json
import os

import pyarrow as pa
import pytest
from pyarrow import ipc

from tap_spreadsheets_anywhere.arrow_batch import (
    ArrowBatchWriter,
    BatchConfig,
    build_batch_message,
    rows_to_arrow_table,
    schema_to_arrow_schema,
    write_arrow_ipc_file,
    write_message,
)


class TestBatchConfig:
    def test_from_config_returns_none_without_batch_config(self):
        assert BatchConfig.from_config({}) is None

    def test_from_config_applies_defaults(self, tmp_path):
        batch_config = BatchConfig.from_config(
            {
                "batch_config": {"storage": {"root": str(tmp_path)}},
            }
        )
        assert batch_config is not None
        assert batch_config.format == "arrow"
        assert batch_config.batch_root_dir == str(tmp_path)
        assert batch_config.batch_size > 0

    def test_from_config_honors_overrides(self, tmp_path):
        batch_config = BatchConfig.from_config(
            {
                "batch_config": {
                    "encoding": {"format": "arrow"},
                    "storage": {"root": str(tmp_path)},
                    "batch_size": 10,
                },
            }
        )
        assert batch_config is not None
        assert batch_config.batch_size == 10
        assert batch_config.batch_root_dir == str(tmp_path)

    def test_rejects_unsupported_format(self, tmp_path):
        with pytest.raises(ValueError):
            BatchConfig(batch_size=10, batch_root_dir=str(tmp_path), format="jsonl")

    def test_rejects_nonpositive_batch_size(self, tmp_path):
        with pytest.raises(ValueError):
            BatchConfig(batch_size=0, batch_root_dir=str(tmp_path))

    def test_rejects_missing_batch_root_dir(self):
        with pytest.raises(ValueError):
            BatchConfig(batch_size=10, batch_root_dir="/no/such/directory/exists")


class TestSchemaToArrowSchema:
    def test_maps_primitive_types(self):
        schema = {
            "properties": {
                "an_int": {"type": ["null", "integer"]},
                "a_number": {"type": ["null", "number"]},
                "a_bool": {"type": ["null", "boolean"]},
                "a_string": {"type": ["null", "string"]},
                "a_date": {"type": ["null", "string"], "format": "date-time"},
                "untyped": {},
            },
        }
        arrow_schema = schema_to_arrow_schema(schema)
        by_name = {field.name: field.type for field in arrow_schema}

        assert by_name["an_int"] == pa.int64()
        assert by_name["a_number"] == pa.float64()
        assert by_name["a_bool"] == pa.bool_()
        assert by_name["a_string"] == pa.string()
        assert by_name["a_date"] == pa.string()
        assert by_name["untyped"] == pa.string()

    def test_handles_bare_string_type(self):
        schema = {"properties": {"field": {"type": "integer"}}}
        arrow_schema = schema_to_arrow_schema(schema)
        assert arrow_schema.field("field").type == pa.int64()


class TestRowsToArrowTable:
    def test_builds_table_matching_schema(self):
        arrow_schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])
        rows = [{"id": 1, "name": "a"}, {"id": 2, "name": None}]

        table = rows_to_arrow_table(rows, arrow_schema)

        assert table.schema == arrow_schema
        assert table.column("id").to_pylist() == [1, 2]
        assert table.column("name").to_pylist() == ["a", None]

    def test_json_encodes_nested_values(self):
        arrow_schema = pa.schema([pa.field("payload", pa.string())])
        rows = [{"payload": {"k": "v"}}]

        table = rows_to_arrow_table(rows, arrow_schema)

        assert json.loads(table.column("payload")[0].as_py()) == {"k": "v"}


class TestWriteArrowIpcFile:
    def test_round_trips_table(self, tmp_path):
        table = pa.table({"id": [1, 2, 3]})
        path = os.path.join(tmp_path, "out.arrow")
        size_bytes = write_arrow_ipc_file(table, path)

        assert size_bytes > 0
        with ipc.open_file(path) as reader:
            assert reader.read_all().column("id").to_pylist() == [1, 2, 3]


class TestBuildBatchMessage:
    def test_shape(self):
        message = build_batch_message("my_stream", ["file:///a.arrow"])
        assert message == {
            "type": "BATCH",
            "stream": "my_stream",
            "encoding": {"format": "arrow"},
            "manifest": ["file:///a.arrow"],
        }


class FakeOutput:
    def __init__(self):
        self.lines = []
        self.flushed = False

    def write(self, data):
        self.lines.append(data)

    def flush(self):
        self.flushed = True


class TestWriteMessage:
    def test_writes_json_line_and_flushes(self):
        output = FakeOutput()
        write_message({"type": "BATCH"}, output)
        assert json.loads(output.lines[0]) == {"type": "BATCH"}
        assert output.flushed


class TestArrowBatchWriter:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_dir = tmp_path
        self.schema = {"properties": {"id": {"type": ["null", "integer"]}}}

    def _writer(self, batch_size, output):
        batch_config = BatchConfig(batch_size=batch_size, batch_root_dir=str(self.tmp_dir))
        return ArrowBatchWriter("my_stream", self.schema, batch_config, output=output)

    def test_flush_with_no_rows_is_a_noop(self):
        output = FakeOutput()
        writer = self._writer(batch_size=10, output=output)
        writer.flush()
        assert output.lines == []

    def test_auto_flushes_at_batch_size(self):
        output = FakeOutput()
        writer = self._writer(batch_size=2, output=output)

        writer.write({"id": 1})
        assert output.lines == [], "should not flush before batch_size rows are buffered"
        writer.write({"id": 2})

        assert len(output.lines) == 1
        message = json.loads(output.lines[0])
        assert message["type"] == "BATCH"
        assert message["stream"] == "my_stream"
        manifest_path = message["manifest"][0].removeprefix("file://")
        with ipc.open_file(manifest_path) as reader:
            assert reader.read_all().column("id").to_pylist() == [1, 2]

    def test_explicit_flush_emits_partial_batch(self):
        output = FakeOutput()
        writer = self._writer(batch_size=10, output=output)

        writer.write({"id": 1})
        writer.flush()

        assert len(output.lines) == 1
        writer.flush()
        assert len(output.lines) == 1, "a second flush with no new rows should not emit another message"

    def test_each_flush_writes_a_new_file(self):
        output = FakeOutput()
        writer = self._writer(batch_size=1, output=output)

        writer.write({"id": 1})
        writer.write({"id": 2})

        paths = [json.loads(line)["manifest"][0] for line in output.lines]
        assert len(set(paths)) == 2
