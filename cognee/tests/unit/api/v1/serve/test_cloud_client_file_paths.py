"""Over serve(), a string that names a local file uploads the file, not the path.

Local add() and remember() read a string naming an existing file as that file.
CloudClient sent every string as text, so a remote ``cognee.add("/docs/q3.pdf")``
uploaded the 12-byte path as ``text_<md5>.txt``, reported success, and the
remote instance built its graph from the path text instead of the document.
"""

import asyncio
from unittest.mock import patch

import pytest

from cognee.api.v1.serve.cloud_client import CloudClient, _text_upload_filename


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return {"status": "completed"}

    async def text(self):
        return ""


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in that captures the POST body."""

    def __init__(self):
        self.posts = []
        self.closed = False

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, data))
        return _FakeResponse()


def _data_fields(form):
    """(filename, body_bytes) of each multipart ``data`` field."""
    out = []
    for type_options, _headers, value in form._fields:
        if type_options.get("name") != "data":
            continue
        body = value.read() if hasattr(value, "read") else str(value).encode("utf-8")
        if hasattr(value, "close"):
            value.close()
        out.append((type_options.get("filename"), body))
    return out


def _send(operation, data, **kwargs):
    client = CloudClient(service_url="https://example.test", api_key="k")
    session = _FakeSession()

    async def run():
        with patch.object(client, "_get_session", return_value=session):
            await getattr(client, operation)(data, "ds", **kwargs)

    asyncio.run(run())
    return session


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "q3_report.txt"
    path.write_text("Q3 revenue grew 12 percent.", encoding="utf-8")
    return path


@pytest.mark.parametrize("operation", ["add", "remember"])
def test_file_path_uploads_the_file_contents(operation, report):
    session = _send(operation, str(report))

    (_url, form) = session.posts[0]
    assert _data_fields(form) == [("q3_report.txt", b"Q3 revenue grew 12 percent.")]


def test_relative_file_path_uploads_the_file_contents(report, monkeypatch):
    monkeypatch.chdir(report.parent)

    session = _send("add", "q3_report.txt")

    assert _data_fields(session.posts[0][1]) == [("q3_report.txt", b"Q3 revenue grew 12 percent.")]


def test_list_mixes_file_paths_and_text(report):
    session = _send("add", [str(report), "a plain note"])

    assert _data_fields(session.posts[0][1]) == [
        ("q3_report.txt", b"Q3 revenue grew 12 percent."),
        (_text_upload_filename("a plain note"), b"a plain note"),
    ]


def test_path_looking_text_that_names_no_file_stays_text(tmp_path):
    note = f"{tmp_path}/remember to call Bob"

    session = _send("add", note)

    assert _data_fields(session.posts[0][1]) == [
        (_text_upload_filename(note), note.encode("utf-8"))
    ]


def test_file_outside_allowed_roots_stays_text(report, tmp_path_factory, monkeypatch):
    allowed = tmp_path_factory.mktemp("allowed")
    monkeypatch.setenv("COGNEE_ALLOWED_LOCAL_FILE_ROOTS", str(allowed))

    session = _send("add", str(report))

    assert _data_fields(session.posts[0][1]) == [
        (_text_upload_filename(str(report)), str(report).encode("utf-8"))
    ]


@pytest.mark.parametrize("operation", ["add", "remember"])
def test_directory_path_fails_loudly_instead_of_uploading_the_path(operation, tmp_path):
    with pytest.raises(ValueError, match="is a directory"):
        _send(operation, str(tmp_path))
