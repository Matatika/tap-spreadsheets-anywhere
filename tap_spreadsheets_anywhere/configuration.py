"""Provides an object model for a our config file"""

from __future__ import annotations

import dataclasses
import json
import logging

from voluptuous import Any, Extra, Optional, Required, Schema

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class TableSpec:
    """A single, validated entry from the tap config's `tables` array.

    Supports the same `table_spec['key']` / `table_spec.get('key', default)` / `'key' in
    table_spec` access patterns as the raw dict it replaces (see `__getitem__`/`get`/
    `__contains__` below), so existing call sites across the tap - and test fixtures that
    still construct plain dicts directly - keep working unchanged. New code can additionally
    use typed attribute access (e.g. `table_spec.path`) for IDE/type-checker support.
    """

    # `path`/`name`/`pattern`/`start_date`/`key_properties`/`format` are required by
    # CONFIG_CONTRACT for a real tap config - but that requirement is enforced there (by
    # voluptuous), not here, so this dataclass can also be constructed directly (e.g. in
    # tests exercising a single option) without spelling out unrelated fields every time.
    path: str = ""
    name: str = ""
    pattern: str = ""
    start_date: str = ""
    key_properties: list[str] = dataclasses.field(default_factory=list)
    format: str = "detect"
    encoding: str = "utf-8"
    invalid_format_action: str = "fail"
    universal_newlines: bool = True
    skip_initial: int = 0
    selected: bool = True
    field_names: list[str] | None = None
    search_prefix: str | None = None
    worksheet_name: str | None = None
    delimiter: str | None = None
    quotechar: str = '"'
    json_path: str | None = None
    sample_rate: int = 5
    max_sampling_read: int = 1000
    max_records_per_run: int = -1
    max_sampled_files: int = 50
    prefer_number_vs_integer: bool = False
    prefer_schema_as_string: bool = False
    schema_overrides: dict = dataclasses.field(default_factory=dict)
    ignore_undefined_field_names: bool = False
    ignore_state: bool = False
    skip_empty_rows: bool = False
    state_based_discovery: bool = False
    # Only consulted in Arrow BATCH mode (see arrow_batch.schema_to_arrow_schema): whether
    # date-time columns are typed as native Arrow timestamps (parsed with pyarrow's strict
    # ISO-8601 parser) or left as unparsed strings. Defaults on since Arrow BATCH mode is
    # itself already opt-in; set to False for tables with non-ISO-8601 date formatting.
    arrow_native_timestamps: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> TableSpec:
        known_fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known_fields})

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __contains__(self, key):
        return getattr(self, key, None) is not None


CONFIG_CONTRACT = Schema(
    {
        Required("tables"): [
            {
                Required("path"): str,
                Required("name"): str,
                Required("pattern"): str,
                Required("start_date"): str,
                Required("key_properties"): [str],
                Required("format"): Any("csv", "excel", "json", "jsonl", "detect"),
                Optional("encoding"): str,
                Optional("invalid_format_action"): Any("ignore", "fail"),
                Optional("universal_newlines"): bool,
                Optional("skip_initial"): int,
                Optional("selected"): bool,
                Optional("field_names"): [str],
                Optional("search_prefix"): str,
                Optional("worksheet_name"): str,
                Optional("delimiter"): str,
                Optional("quotechar"): str,
                Optional("json_path"): str,
                Optional("sample_rate"): int,
                Optional("max_sampling_read"): int,
                Optional("max_records_per_run"): int,
                Optional("max_sampled_files"): int,
                Optional("prefer_number_vs_integer"): bool,
                Optional("prefer_schema_as_string"): bool,
                Optional("schema_overrides"): {
                    str: {
                        Required("type"): Any(
                            Any(
                                "null",
                                "string",
                                "integer",
                                "number",
                                "date-time",
                                "object",
                            ),
                            [
                                Any(
                                    "null",
                                    "string",
                                    "integer",
                                    "number",
                                    "date-time",
                                    "object",
                                )
                            ],
                        )
                    }
                },
                Optional("ignore_undefined_field_names"): bool,
                Optional("ignore_state"): bool,
                Optional("skip_empty_rows"): bool,
                Optional("state_based_discovery"): bool,
                Optional("arrow_native_timestamps"): bool,
            }
        ],
        Optional("azure_storage_connection_string"): str,
        Optional("aws_access_key_id"): str,
        Optional("aws_secret_access_key"): str,
        Optional("google_application_credentials"): str,
        Optional("ssh_private_key"): str,
        Optional("ssh_passphrase"): str,
        Optional("username"): str,
        Optional("password"): str,
        Optional("oauth_credentials"): {
            Optional("access_token"): str,
            Optional("refresh_token"): str,
            Optional("refresh_proxy_url"): str,
            Optional("refresh_proxy_url_auth"): str,
            Optional("client_id"): str,
            Optional("client_secret"): str,
            Optional("tenant_id"): str,
            Extra: object,
        },
        Optional("batch_config"): {
            Optional("encoding"): {
                Optional("format"): Any("arrow"),
            },
            Optional("storage"): {
                Optional("root"): str,
            },
            Optional("batch_size"): int,
        },
    }
)


class Config:
    @classmethod
    def dump(cls, config_json, ostream):
        json.dump(config_json, ostream, indent=2)

    @classmethod
    def validate(cls, config_json):
        CONFIG_CONTRACT(config_json)
        config_json["tables"] = [TableSpec.from_dict(table) for table in config_json["tables"]]
        return config_json

    @classmethod
    def load(cls, filename):
        with open(filename) as fp:  # pylint: disable=invalid-name
            return Config.validate(json.load(fp))
