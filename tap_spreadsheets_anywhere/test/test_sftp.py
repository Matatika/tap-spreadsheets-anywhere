import os
import socket
import threading

import paramiko

from tap_spreadsheets_anywhere import file_utils, format_handler
from tap_spreadsheets_anywhere.configuration import TableSpec


class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if password == "secret" else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED


class SFTPServer(paramiko.SFTPServerInterface):
    def list_folder(self, path):
        return [paramiko.SFTPAttributes.from_stat(os.stat(f"{path}/{name}"), name) for name in os.listdir(path)]

    def open(self, path, flags, attr):
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = open(path, "rb")  # noqa: SIM115  # the handle closes the file
        return handle


def serve_once(listener):
    transport = paramiko.Transport(listener.accept()[0])
    transport.add_server_key(paramiko.RSAKey.generate(2048))
    transport.set_subsystem_handler("sftp", paramiko.SFTPServer, SFTPServer)
    transport.start_server(server=Server())


def test_sync_from_server_with_unknown_host_key(tmp_path):
    (tmp_path / "sample.csv").write_text("id,name\n1,a\n2,b\n")
    listener = socket.create_server(("127.0.0.1", 0))
    threading.Thread(target=serve_once, args=(listener,), daemon=True).start()
    port = listener.getsockname()[1]
    format_handler.set_config({})

    table_spec = TableSpec(path=f"sftp://user:secret@127.0.0.1:{port}{tmp_path}", pattern=r"sample\.csv")
    [match] = file_utils.get_matching_objects(table_spec)
    uri = file_utils.resolve_target_uri(table_spec, match["key"])
    rows = list(format_handler.get_row_iterator(table_spec, uri))

    assert match["key"] == "sample.csv"
    assert rows == [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}]
