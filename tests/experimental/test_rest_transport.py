"""Default REST transport for Developer Preview methods."""

from __future__ import annotations

import json
from typing import Any, ClassVar

import pytest
import requests
from google.auth.credentials import AnonymousCredentials

from chattice.capabilities import CapabilityNotSupported
from chattice.client import Bot, ChatNotFoundError
from chattice.experimental._rest import RestTransport


class _FakeSession:
    """Stands in for google-auth's AuthorizedSession."""

    instances: ClassVar[list[_FakeSession]] = []
    status: ClassVar[int] = 200
    payload: ClassVar[dict[str, object] | None] = {"name": "spaces/A/streamMessages/s1"}

    def __init__(self, credentials: object) -> None:
        self.credentials = credentials
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        type(self).instances.append(self)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = requests.Response()
        response.status_code = type(self).status
        payload = type(self).payload
        response._content = b"" if payload is None else json.dumps(payload).encode()
        response.request = requests.Request(method, url).prepare()
        return response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSession]:
    _FakeSession.instances = []
    _FakeSession.status = 200
    _FakeSession.payload = {"name": "spaces/A/streamMessages/s1"}
    monkeypatch.setattr(
        "google.auth.transport.requests.AuthorizedSession", _FakeSession
    )
    return _FakeSession


def _bot() -> Bot:
    return Bot(credentials=AnonymousCredentials())  # type: ignore[no-untyped-call]


async def test_request_targets_the_chat_rest_endpoint(
    session: type[_FakeSession],
) -> None:
    result = await RestTransport(_bot()).request(
        "PATCH",
        "spaces/A/streamMessages/s1",
        params={"updateMask": "progressText"},
        body={"progressText": "Working..."},
        timeout=5.0,
    )
    assert result == {"name": "spaces/A/streamMessages/s1"}
    used = session.instances[-1]
    assert used.closed
    assert used.calls == [
        {
            "method": "PATCH",
            "url": "https://chat.googleapis.com/v1/spaces/A/streamMessages/s1",
            "params": {"updateMask": "progressText"},
            "json": {"progressText": "Working..."},
            "timeout": 5.0,
        }
    ]


async def test_empty_response_body_becomes_empty_mapping(
    session: type[_FakeSession],
) -> None:
    session.payload = None
    assert await RestTransport(_bot()).request("DELETE", "spaces/A/x/1") == {}
    assert session.instances[-1].calls[0]["timeout"] == 60.0


async def test_http_errors_map_to_the_chat_error_family(
    session: type[_FakeSession],
) -> None:
    session.status = 404
    session.payload = {"error": {"code": 404, "message": "stream not found"}}
    with pytest.raises(ChatNotFoundError, match="stream not found"):
        await RestTransport(_bot()).request("GET", "spaces/A/threads/t1")
    assert session.instances[-1].closed


async def test_missing_app_credentials_fail_before_any_request(
    session: type[_FakeSession],
) -> None:
    with pytest.raises(CapabilityNotSupported):
        await RestTransport(Bot()).request("GET", "spaces/A/threads/t1")
    assert session.instances == []
