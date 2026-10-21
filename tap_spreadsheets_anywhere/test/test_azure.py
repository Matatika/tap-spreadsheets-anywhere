from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from tap_spreadsheets_anywhere.file_utils import _list_azure_container, list_files_in_azure_bucket

OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW = datetime(2026, 6, 1, tzinfo=timezone.utc)
BLOBS = [
    SimpleNamespace(name="20260101/A_1.csv", last_modified=OLD, size=10),
    SimpleNamespace(name="20260601/B_2.csv", last_modified=NEW, size=10),
    SimpleNamespace(name="20260601/EMPTY_3.csv", last_modified=NEW, size=0),
]


class TestListFilesInAzureBucket:
    def setup_method(self):
        _list_azure_container.cache_clear()

    def test_container_listed_once_and_filtered_per_call(self):
        with (
            patch.dict("os.environ", {"AZURE_STORAGE_CONNECTION_STRING": "test"}),
            patch("tap_spreadsheets_anywhere.file_utils.BlobServiceClient") as client,
        ):
            list_blobs = client.from_connection_string.return_value.get_container_client.return_value.list_blobs
            list_blobs.return_value = BLOBS

            all_files = list_files_in_azure_bucket("container")
            new_files = list_files_in_azure_bucket("container", modified_since=NEW)

        # one listing serves both calls, each with its own modified_since filter
        assert list_blobs.call_count == 1
        assert [f["Key"] for f in all_files] == ["20260101/A_1.csv", "20260601/B_2.csv"]
        assert new_files == [{"Key": "20260601/B_2.csv", "LastModified": NEW}]

    def test_search_prefix_is_listed_separately(self):
        with (
            patch.dict("os.environ", {"AZURE_STORAGE_CONNECTION_STRING": "test"}),
            patch("tap_spreadsheets_anywhere.file_utils.BlobServiceClient") as client,
        ):
            list_blobs = client.from_connection_string.return_value.get_container_client.return_value.list_blobs
            list_blobs.return_value = BLOBS

            list_files_in_azure_bucket("container")
            list_files_in_azure_bucket("container", search_prefix="2026")

        assert list_blobs.call_count == 2
        assert list_blobs.call_args.kwargs == {"name_starts_with": "2026"}
