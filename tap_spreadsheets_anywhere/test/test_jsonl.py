import logging

from tap_spreadsheets_anywhere import format_handler
from tap_spreadsheets_anywhere.configuration import TableSpec

LOGGER = logging.getLogger(__name__)

TEST_TABLE_SPEC = [
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="json_sample_multiple_records",
        pattern="sample\\.json",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="json",
    ),
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="json_sample_one_record",
        pattern="one-row-sample\\.json",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="json",
    ),
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="jsonl_sample_multiple_records",
        pattern="sample-jsonl\\.json",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="jsonl",
        universal_newlines=True,
    ),
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="jsonl_sample_one_record",
        pattern="one-row-sample-jsonl\\.json",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="jsonl",
    ),
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="jsonl_sample_multiple_records_detect",
        pattern="sample\\.jsonl",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="detect",
    ),
    TableSpec(
        path="file://./tap_spreadsheets_anywhere/test",
        name="jsonl_sample_one_record_detect",
        pattern="one-row-sample\\.jsonl",
        start_date="2017-05-01T00:00:00Z",
        key_properties=[],
        format="detect",
    ),
]


class TestJsonFormatHandler:
    def test_json_file(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/sample.json"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[0], test_filename_uri)
        expected_row_count = 6
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] is not None, f"ID field is None for row {row}"
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"

    def test_one_row_json_file(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/one-row-sample.json"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[1], test_filename_uri)
        expected_row_count = 1
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] == 3884, f"ID field is {row['id']} - expected it to be 3884."
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"

    def test_jsonl_file(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/sample-jsonl.json"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[2], test_filename_uri)
        expected_row_count = 6
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] is not None, f"ID field is None for row {row}"
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"

    def test_one_row_jsonl_file(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/one-row-sample-jsonl.json"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[3], test_filename_uri)
        expected_row_count = 1
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] == 3884, f"ID field is {row['id']} - expected it to be 3884."
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"

    def test_jsonl_file_detect(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/sample.jsonl"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[4], test_filename_uri)
        expected_row_count = 6
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] is not None, f"ID field is None for row {row}"
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"

    def test_one_row_jsonl_file_detect(self):
        test_filename_uri = "./tap_spreadsheets_anywhere/test/one-row-sample.jsonl"
        iterator = format_handler.get_row_iterator(TEST_TABLE_SPEC[5], test_filename_uri)
        expected_row_count = 1
        row_count = 0
        for row in iterator:
            row_count += 1
            assert row["id"] == 3884, f"ID field is {row['id']} - expected it to be 3884."
        assert row_count == expected_row_count, f"Expected row_count to be {expected_row_count} but was {row_count}"
