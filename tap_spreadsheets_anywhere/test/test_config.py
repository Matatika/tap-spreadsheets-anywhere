import unittest

import dateutil
from io import StringIO
from tap_spreadsheets_anywhere import configuration, file_utils, csv_handler, json_handler

TEST_CRAWL_SPEC = {
    "tables": [
        {
            "crawl_config": "true",
            "path": "file://./tap_spreadsheets_anywhere/test",
            "pattern": ".*\\.xlsx",
            "start_date": "2017-05-01T00:00:00Z"
        }
    ]
}

TEST_TABLE_SPEC = {
    "tables": [
        {
            "path": "file://./artifacts",
            "name": "badnewlines",
            "pattern": '.*\\.csv',
            "start_date": "2017-05-01T00:00:00Z",
            "key_properties": [],
            "format": "csv",
            "universal_newlines": False,
            "sample_rate": 5,
            "max_sampling_read": 2000,
            "max_sampled_files": 3
        },
        {
            "path": "file://./artifacts",
            "name": "badnewlines",
            "pattern": '.*\\.csv',
            "start_date": "2024-01-01T00:00:00Z",
            "key_properties": [],
            "format": "csv",
            "universal_newlines": False,
            "sample_rate": 5,
            "max_sampling_read": 2000,
            "max_sampled_files": 3
        },
        {
            "path": "file://./artifacts",
            "name": "badnewlines",
            "pattern": '.*\\.csv',
            "start_date": "2017-05-01T00:00:00Z",
            "key_properties": [],
            "format": "csv",
            "universal_newlines": False,
            "sample_rate": 5,
            "max_sampling_read": 2000,
            "max_sampled_files": 3,
            "ignore_state": True
        }
    ]
}


class TestFormatHandler(unittest.TestCase):

    def test_config_by_crawl(self):
        crawl_paths = [x for x in TEST_CRAWL_SPEC['tables'] if "crawl_config" in x and x["crawl_config"]]
        config_struct = file_utils.config_by_crawl(crawl_paths)
        self.assertTrue(config_struct['tables'][0]['name'] == 'excel_with_bad_newlinesxlsx',
                        "config did not crawl and parse as expected!")


class TestConfigStartDate(unittest.TestCase):

    def test_config_with_start_date_less_than_file_modified_date(self):
        table_spec = TEST_TABLE_SPEC['tables'][0]
        modified_since = dateutil.parser.parse(table_spec['start_date'])
        target_files = file_utils.get_matching_objects(table_spec, modified_since)
        assert len(target_files) == 1

    def test_config_with_start_date_greater_than_file_modified_date(self):
        table_spec = TEST_TABLE_SPEC['tables'][1]
        modified_since = dateutil.parser.parse(table_spec['start_date'])
        target_files = file_utils.get_matching_objects(table_spec, modified_since)
        assert len(target_files) == 0


class TestConfigIgnoreState(unittest.TestCase):

    def test_config_ignore_state_true(self):
        table_spec = TEST_TABLE_SPEC['tables'][2]

        # This is the logic if state was found in the sync function.
        # 2024-01-01T00:00:00Z as our dummy state so this should not find any files unless we ignore_state
        modified_since = "2024-01-01T00:00:00Z"
        modified_since = table_spec['start_date'] if table_spec.get('ignore_state') else modified_since

        modified_since = dateutil.parser.parse(table_spec['start_date'])
        target_files = file_utils.get_matching_objects(table_spec, modified_since)
        assert len(target_files) == 1
