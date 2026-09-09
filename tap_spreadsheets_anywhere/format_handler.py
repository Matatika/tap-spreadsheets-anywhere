import json
import logging
import os
from codecs import StreamReader
from functools import cache
from imaplib import IMAP4
from io import StringIO
from urllib.parse import urlparse, urlunparse

import httpx
import msgraphfs.core
import pyarrow as pa
import smart_open
from azure.storage.blob import BlobServiceClient
from google.cloud.storage import Client as GCSClient
from imapfs.core import IMAPFileSystem
from paramiko.rsakey import RSAKey

import tap_spreadsheets_anywhere.csv_handler
import tap_spreadsheets_anywhere.excel_handler
import tap_spreadsheets_anywhere.json_handler
import tap_spreadsheets_anywhere.jsonl_handler
from tap_spreadsheets_anywhere.auth import refresh_microsoft_token
from tap_spreadsheets_anywhere.configuration import TableSpec

LOGGER = logging.getLogger(__name__)

_config: dict = {}


def set_config(config: dict) -> None:
    """Make the tap's validated config available to `get_transport_params`.

    Called once by `main()` for a real run. Reading `sys.argv` again here (as this used to,
    via `singer.utils.parse_args`) broke under any host whose own argv doesn't match this
    tap's CLI contract - such as pytest.
    """
    global _config
    _config = config


def get_transport_params(protocol: str):
    config: dict = _config

    if protocol == "sftp":
        # https://docs.paramiko.org/en/stable/api/client.html#paramiko.client.SSHClient.connect
        connect_kwargs = {
            "allow_agent": False,
            "look_for_keys": False,
            "timeout": 10,
        }

        if "password" in config:
            connect_kwargs["password"] = config["password"]

        if "ssh_private_key" in config:
            with StringIO(config["ssh_private_key"]) as f:
                private_key = RSAKey.from_private_key(f)

            connect_kwargs["pkey"] = private_key
            connect_kwargs["passphrase"] = config.get("ssh_passphrase")

        return {"connect_kwargs": connect_kwargs}

    if protocol == "azure":
        return {"client": BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])}

    if protocol == "gs":
        return {"client": get_gcs_client()}

    if protocol == "s3":
        return {}

    if protocol in ["http", "https"]:
        return {}

    if protocol == "imap":
        return {
            "username": config["username"],
            "password": config.get("password"),
            **config.get("oauth_credentials", {}),
        }

    if protocol in ("file", ""):
        # A blank scheme means a bare local path (e.g. no `file://` prefix), which
        # smart_open/urlparse otherwise treat the same as a local filesystem read.
        return {}

    if protocol == "sharepoint":
        return config.get("oauth_credentials", {})

    msg = f"Protocol '{protocol}' not supported"
    raise ValueError(msg)


@cache
def get_gcs_client():
    credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    try:
        return GCSClient.from_service_account_info(json.loads(credentials or ""))
    except (TypeError, json.decoder.JSONDecodeError):
        return GCSClient()


class InvalidFormatError(Exception):
    def __init__(self, fname, message="The file was not in the expected format"):
        self.name = fname
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.name} could not be parsed: {self.message}"


@cache
def get_imap_fs(host):
    transport_params = get_transport_params("imap")

    def refresh():
        # the IMAP client authenticates with the access token only
        return refresh_microsoft_token(transport_params)["access_token"]

    username = transport_params["username"]

    fs_kwargs = {}
    password = transport_params.get("password")
    if password:
        fs_kwargs["password"] = password
    else:
        fs_kwargs["access_token"] = transport_params.get("access_token") or refresh()

    try:
        return IMAPFileSystem(host=host, username=username, **fs_kwargs)
    except IMAP4.error:
        if "access_token" not in transport_params:
            raise  # we just refreshed the access token; likely some other error

        access_token = refresh()

    return IMAPFileSystem(host=host, username=username, access_token=access_token)


class MSGDriveFS(msgraphfs.core.MSGDriveFS):
    async def _get_site_id(self):
        """Get the ID of the site.

        Address the site directly, because the superclass searches for the site, and
        the search endpoint requires `Sites.Read.All`. Fall back to the search of the
        superclass for a site outside `/sites/`, which the direct address cannot reach.
        """
        url = f"https://graph.microsoft.com/v1.0/sites/root:/sites/{self.site_name}"

        try:
            response = await self._msgraph_get(url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

            return await super()._get_site_id()

        return response.json()["id"]


@cache
def get_sharepoint_fs(uri):
    transport_params = get_transport_params("sharepoint")

    if "access_token" in transport_params:
        fs = MSGDriveFS(
            oauth2_client_params={"token": {"access_token": transport_params["access_token"]}},
            url_path=uri,
        )
        try:
            fs.msgraph_get("https://graph.microsoft.com/v1.0/me/drive")
            return fs
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 401:
                raise

    if "refresh_token" in transport_params:
        return MSGDriveFS(
            oauth2_client_params={"token": refresh_microsoft_token(transport_params)},
            url_path=uri,
        )

    if {"client_id", "client_secret", "tenant_id"} <= transport_params.keys():
        return MSGDriveFS(
            client_id=transport_params["client_id"],
            client_secret=transport_params["client_secret"],
            tenant_id=transport_params["tenant_id"],
            url_path=uri,
        )

    lines = (
        "Insufficient `oauth_credentials` configuration to authenticate with SharePoint. Must satisfy one of:",
        "  - `access_token`",
        "  - `refresh_token`, `client_id`, `client_secret`",
        "  - `refresh_token`, `refresh_proxy_url`, `refresh_proxy_url_auth`",
        "  - `client_id`, `client_secret`, `tenant_id`",
    )
    raise ValueError("\n".join(lines))


def get_streamreader(
    uri: str,
    universal_newlines=True,
    newline="",
    open_mode="r",
    encoding="utf-8",
):
    # When reading in binary mode, undefine `encoding`.
    # Otherwise, `smart_open` will return a `TextIOWrapper` in `"r"` mode.
    # However, reading binary streams needs a `BufferedReader`.
    if "b" in open_mode:
        encoding = None

    parsed = urlparse(uri)

    if parsed.scheme == "imap":
        fs = get_imap_fs(parsed.netloc)
        path = uri.lstrip(urlunparse(parsed._replace(path="/")))
        return fs.open(
            path,
            open_mode,
            newline=newline,
            encoding=encoding,
            errors="replace",
        )

    if parsed.scheme == "sharepoint":
        path = uri.split("/", 4)[-1]
        fs = get_sharepoint_fs(uri.replace(path, "", 1))

        return fs.open(
            path,
            open_mode,
            newline=newline,
            encoding=encoding,
            errors="replace",
        )

    streamreader = smart_open.open(
        uri,
        open_mode,
        newline=newline,
        errors="surrogateescape",
        encoding=encoding,
        transport_params=get_transport_params(parsed.scheme),
    )

    if not universal_newlines and isinstance(streamreader, StreamReader):
        return monkey_patch_streamreader(streamreader)
    return streamreader


def monkey_patch_streamreader(streamreader):
    streamreader.mp_newline = "\n"
    streamreader.readline = mp_readline.__get__(streamreader, StreamReader)
    return streamreader


def mp_readline(self, size=None, keepends=False):
    """
    Modified version of readline for StreamReader that avoids the use of splitlines
    in favor of a call to split(self.mp_newline)
    This supports poorly formatted CSVs that the author has sadly seen in the wild
    from commercial vendors.
    """
    # If we have lines cached from an earlier read, return
    # them unconditionally
    if self.linebuffer:
        line = self.linebuffer[0]
        del self.linebuffer[0]
        if len(self.linebuffer) == 1:
            # revert to charbuffer mode; we might need more data
            # next time
            self.charbuffer = self.linebuffer[0]
            self.linebuffer = None
        if not keepends:
            line = line.split(self.mp_newline)[0]
        return line

    readsize = size or 72
    line = self._empty_charbuffer
    # If size is given, we call read() only once
    while True:
        data = self.read(readsize, firstline=True)
        # If we're at a "\r" read one extra character (which might
        # be a "\n") to get a proper line ending. If the stream is
        # temporarily exhausted we return the wrong line ending.
        if data and (
            (isinstance(data, str) and data.endswith("\r")) or (isinstance(data, bytes) and data.endswith(b"\r"))
        ):
            data += self.read(size=1, chars=1)

        line += data
        lines = line.split(self.mp_newline)
        if lines:
            if len(lines) > 1:
                # More than one line result; the first line is a full line
                # to return
                line = lines[0]
                del lines[0]
                if len(lines) > 1:
                    # cache the remaining lines
                    lines[-1] += self.charbuffer
                    self.linebuffer = lines
                    self.charbuffer = None
                else:
                    # only one remaining line, put it back into charbuffer
                    self.charbuffer = lines[0] + self.charbuffer
                if not keepends:
                    line = line.split(self.mp_newline)[0]
                break
            line0withend = lines[0]
            line0withoutend = lines[0].split(self.mp_newline)[0]
            if line0withend != line0withoutend:  # We really have a line end
                # Put the rest back together and keep it until the next call
                self.charbuffer = self._empty_charbuffer.join(lines[1:]) + self.charbuffer
                if keepends:
                    line = line0withend
                else:
                    line = line0withoutend
                break
        # we didn't get anything or this was our only try
        if not data or size is not None:
            if line and not keepends:
                line = line.split(self.mp_newline)[0]
            break
        if readsize < 8000:
            readsize *= 2
    return line


def _resolve_format(table_spec: TableSpec, uri: str) -> str:
    if table_spec.format != "detect":
        return table_spec.format

    lowered_uri = uri.lower()
    if lowered_uri.endswith((".xlsx", ".xls")):
        return "excel"
    if lowered_uri.endswith((".json", ".js")):
        return "json"
    if lowered_uri.endswith(".jsonl"):
        return "jsonl"
    if lowered_uri.endswith(".csv"):
        return "csv"

    # TODO: some protocols provide the ability to pull format (content-type) info & we could make use of that here
    reader = get_streamreader(
        uri,
        universal_newlines=table_spec.universal_newlines,
        open_mode="r",
        encoding=table_spec.encoding,
    )
    buf = reader.read(10)
    reader.seek(0)
    if len(buf) > 0:
        if buf[0].lstrip() == "[":
            return "json"
        elif buf[0].isprintable():
            return "csv"
        else:
            raise ValueError(f"Unable to detect the format for {uri}")
    else:
        raise ValueError(f"Unable to read {uri} for type detection")


def get_arrow_table(table_spec: TableSpec, uri: str, data_schema: pa.Schema) -> pa.Table | None:
    """Vectorized Arrow BATCH fast path for CSV (see `csv_handler.get_arrow_table`).

    Returns `None` when the fast path isn't applicable - either because `uri` doesn't
    resolve to CSV format, or because pyarrow's stricter CSV parsing rejected something
    (unexpected data shape, non-ISO-8601 date-time values when
    `table_spec.arrow_native_timestamps` is set, etc.) - in which case the caller
    (`file_utils.write_file`) should fall back to `get_row_iterator` and emit the file
    row by row instead. A fast-path failure never fails the file outright: the row-by-row
    path is always tried as a fallback first.
    """
    if _resolve_format(table_spec, uri) != "csv":
        return None

    reader = get_streamreader(
        uri,
        universal_newlines=table_spec.universal_newlines,
        newline=None,
        open_mode="rb",
    )
    try:
        return tap_spreadsheets_anywhere.csv_handler.get_arrow_table(table_spec, reader, data_schema)
    except (ValueError, pa.lib.ArrowInvalid) as err:
        LOGGER.info("Falling back to row-by-row processing for %s: %s", uri, err)
        return None


def get_row_iterator(table_spec: TableSpec, uri):
    universal_newlines = table_spec.universal_newlines
    encoding = table_spec.encoding
    skip_initial = table_spec.skip_initial
    format = _resolve_format(table_spec, uri)

    try:
        if format == "csv":
            reader = get_streamreader(
                uri,
                universal_newlines=universal_newlines,
                open_mode="r",
                encoding=encoding,
            )
            iterator = tap_spreadsheets_anywhere.csv_handler.get_row_iterator(table_spec, reader)
        elif format == "excel":
            if uri.lower().endswith(".xls"):
                reader = get_streamreader(
                    uri,
                    universal_newlines=universal_newlines,
                    newline=None,
                    open_mode="rb",
                )
                iterator = tap_spreadsheets_anywhere.excel_handler.get_legacy_row_iterator(table_spec, reader)
            else:
                # If encoding is set, smart_open will override binary mode ('b' in open_mode) and it will result in a BadZipFile error
                reader = get_streamreader(
                    uri,
                    universal_newlines=universal_newlines,
                    newline=None,
                    open_mode="rb",
                    encoding=None,
                )
                iterator = tap_spreadsheets_anywhere.excel_handler.get_row_iterator(table_spec, reader)
        elif format == "json":
            reader = get_streamreader(
                uri,
                universal_newlines=universal_newlines,
                open_mode="r",
                encoding=encoding,
            )
            iterator = tap_spreadsheets_anywhere.json_handler.get_row_iterator(table_spec, reader)
        elif format == "jsonl":
            reader = get_streamreader(
                uri,
                universal_newlines=universal_newlines,
                open_mode="r",
                encoding=encoding,
            )
            iterator = tap_spreadsheets_anywhere.jsonl_handler.get_row_iterator(table_spec, reader)
    except (ValueError, TypeError) as err:
        raise InvalidFormatError(uri, message=err)

    if format != "excel":
        # Reduce the scope of changes to fix Issue #52.
        for _ in range(skip_initial):
            next(iterator)

    return iterator
