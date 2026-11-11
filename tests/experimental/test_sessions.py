# ruff: noqa: ASYNC109 — timeout kwarg mirrors the PreviewTransport protocol
"""Thread sessions (Developer Preview): request shapes and local guards."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported
from chattice.client import Bot, ChatAPIError
from chattice.events import SpaceRef, ThreadRef
from chattice.experimental.sessions import ThreadSession, ThreadSessions

THREAD = "spaces/DM/threads/t1"

Request = tuple[str, str, Mapping[str, str] | None, Mapping[str, object] | None]


def _thread(index: int, *, title: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"name": f"spaces/DM/threads/t{index}"}
    if title is not None:
        payload["threadMetadata"] = {
            "title": title,
            "icon": {"materialIcon": {"name": "notes"}},
        }
    return payload


class FakeTransport:
    def __init__(self, pages: list[dict[str, object]] | None = None) -> None:
        self.requests: list[Request] = []
        self._pages = pages or []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, path, params, body))
        if path.endswith("/threads"):
            return self._pages.pop(0)
        if method == "PATCH":
            assert body is not None
            return dict(body)
        return _thread(1, title="Report")


def _bot(*, enable_preview: bool = True, auth_mode: AuthMode = AuthMode.APP) -> Bot:
    creds = AnonymousCredentials()  # type: ignore[no-untyped-call]
    return Bot(credentials=creds, auth_mode=auth_mode, enable_preview=enable_preview)


async def test_get_returns_typed_session() -> None:
    transport = FakeTransport()
    session = await ThreadSessions(_bot(), transport=transport).get(
        ThreadRef(name=THREAD)
    )
    assert session == ThreadSession(
        name=THREAD, title="Report", icon="notes", raw=session.raw
    )
    assert transport.requests == [("GET", THREAD, None, None)]


async def test_list_follows_page_tokens() -> None:
    transport = FakeTransport(
        pages=[
            {"threads": [_thread(1, title="A"), _thread(2)], "nextPageToken": "p2"},
            {"threads": [_thread(3)]},
        ]
    )
    sessions = await ThreadSessions(_bot(), transport=transport).list(
        SpaceRef(name="spaces/DM"), page_size=2
    )
    names = [session.name async for session in sessions]

    assert names == [f"spaces/DM/threads/t{index}" for index in (1, 2, 3)]
    assert transport.requests == [
        ("GET", "spaces/DM/threads", {"pageSize": "2"}, None),
        ("GET", "spaces/DM/threads", {"pageSize": "2", "pageToken": "p2"}, None),
    ]


async def test_update_sends_only_the_changed_metadata_paths() -> None:
    transport = FakeTransport()
    sessions = ThreadSessions(_bot(), transport=transport)
    updated = await sessions.update(THREAD, title="Quarterly report")
    assert updated.title == "Quarterly report"
    assert transport.requests[-1] == (
        "PATCH",
        THREAD,
        {"updateMask": "threadMetadata.title"},
        {"name": THREAD, "threadMetadata": {"title": "Quarterly report"}},
    )

    updated = await sessions.update(THREAD, title="T", icon="bar_chart")
    assert updated.icon == "bar_chart"
    assert transport.requests[-1][2] == {
        "updateMask": "threadMetadata.title,threadMetadata.icon"
    }


@pytest.mark.parametrize(
    ("title", "icon"),
    [(None, None), ("  ", None), ("x" * 1025, None), (None, "")],
)
async def test_update_validates_locally(title: str | None, icon: str | None) -> None:
    transport = FakeTransport()
    with pytest.raises(ChatAPIError):
        await ThreadSessions(_bot(), transport=transport).update(
            THREAD, title=title, icon=icon
        )
    assert transport.requests == []


@pytest.mark.parametrize("name", ["", "t1", "spaces/DM", "spaces/DM/messages/m1"])
async def test_malformed_thread_name_fails_locally(name: str) -> None:
    transport = FakeTransport()
    with pytest.raises(ChatAPIError):
        await ThreadSessions(_bot(), transport=transport).get(name)
    assert transport.requests == []


async def test_list_validates_space_and_page_size_locally() -> None:
    sessions = ThreadSessions(_bot(), transport=FakeTransport())
    with pytest.raises(ChatAPIError):
        await sessions.list("DM")
    with pytest.raises(ChatAPIError):
        await sessions.list("spaces/DM", page_size=0)


async def test_requires_preview_opt_in_and_app_identity() -> None:
    transport = FakeTransport()
    with pytest.raises(CapabilityNotSupported, match="enable_preview"):
        await ThreadSessions(_bot(enable_preview=False), transport=transport).get(
            THREAD
        )
    with pytest.raises(CapabilityNotSupported, match="app authentication"):
        await ThreadSessions(_bot(auth_mode=AuthMode.USER), transport=transport).update(
            THREAD, title="T"
        )
    assert transport.requests == []
