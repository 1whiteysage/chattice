# ruff: noqa: ASYNC109 — timeout kwarg mirrors the outbound client convention
"""Thread-based sessions in 1:1 app direct messages (Developer Preview).

With "Enable Agentic features" turned on in the Chat API configuration,
Google organizes a 1:1 direct message with the app into separate
thread-based conversation sessions. This module reads those sessions
and updates their title and icon::

    sessions = ThreadSessions(bot)
    await sessions.update(event.thread.name, title="Quarterly report")

Google constraints: app authentication only (``chat.bot``), 1:1 app DM
spaces only, Developer Preview Program enrollment. Requires
``Bot(enable_preview=True)`` or
``preview_features={PreviewFeature.THREAD_SESSIONS}``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field

from chattice.capabilities import PreviewFeature
from chattice.client import Bot
from chattice.client.errors import ChatAPIError
from chattice.events import SpaceRef, ThreadRef
from chattice.experimental._rest import (
    PreviewTransport,
    RestTransport,
    require_app_preview,
)

__all__ = ["ThreadSession", "ThreadSessions"]

_THREAD_NAME = re.compile(r"spaces/[^/]+/threads/[^/]+")
_SPACE_NAME = re.compile(r"spaces/[^/]+")
_MAX_TITLE = 1024
_FEATURE = "Thread sessions"


@dataclass(frozen=True, slots=True)
class ThreadSession:
    """One session: a thread of a 1:1 app DM with its display metadata."""

    name: str
    title: str | None = None
    icon: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)

    @classmethod
    def from_rest(cls, payload: Mapping[str, object]) -> ThreadSession:
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ChatAPIError("Google returned a thread without a name")
        metadata = payload.get("threadMetadata")
        title: str | None = None
        icon: str | None = None
        if isinstance(metadata, Mapping):
            raw_title = metadata.get("title")
            title = raw_title if isinstance(raw_title, str) else None
            raw_icon = metadata.get("icon")
            if isinstance(raw_icon, Mapping):
                material = raw_icon.get("materialIcon")
                if isinstance(material, Mapping) and isinstance(
                    material.get("name"), str
                ):
                    icon = str(material["name"])
        return cls(name=name, title=title, icon=icon, raw=dict(payload))


class ThreadSessions:
    """Session operations executed as the Chat app."""

    def __init__(self, bot: Bot, *, transport: PreviewTransport | None = None) -> None:
        self._bot = bot
        self._transport: PreviewTransport = transport or RestTransport(bot)

    async def get(
        self, thread: ThreadRef | str, *, timeout: float | None = None
    ) -> ThreadSession:
        """Get one session by its ``spaces/{space}/threads/{thread}`` name."""
        name = _thread_name(thread)
        await require_app_preview(self._bot, PreviewFeature.THREAD_SESSIONS, _FEATURE)
        return ThreadSession.from_rest(
            await self._transport.request("GET", name, timeout=timeout)
        )

    async def list(
        self,
        space: SpaceRef | str,
        *,
        page_size: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[ThreadSession]:
        """Iterate the sessions of a 1:1 app DM, newest first."""
        parent = space if isinstance(space, str) else space.name
        if not parent or _SPACE_NAME.fullmatch(parent) is None:
            raise ChatAPIError(
                f"space must be a canonical 'spaces/{{id}}' name; got {parent!r}"
            )
        if page_size is not None and page_size < 1:
            raise ChatAPIError("page_size must be a positive integer")
        await require_app_preview(self._bot, PreviewFeature.THREAD_SESSIONS, _FEATURE)
        return self._pages(parent, page_size, timeout)

    async def _pages(
        self, parent: str, page_size: int | None, timeout: float | None
    ) -> AsyncIterator[ThreadSession]:
        token = ""
        while True:
            params: dict[str, str] = {}
            if page_size is not None:
                params["pageSize"] = str(page_size)
            if token:
                params["pageToken"] = token
            response = await self._transport.request(
                "GET", f"{parent}/threads", params=params or None, timeout=timeout
            )
            threads = response.get("threads")
            if isinstance(threads, list):
                for item in threads:
                    if isinstance(item, Mapping):
                        yield ThreadSession.from_rest(item)
            next_token = response.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                return
            token = next_token

    async def update(
        self,
        thread: ThreadRef | str,
        *,
        title: str | None = None,
        icon: str | None = None,
        timeout: float | None = None,
    ) -> ThreadSession:
        """Set the session title and/or its Google Material icon name."""
        name = _thread_name(thread)
        if title is None and icon is None:
            raise ChatAPIError("update requires a title or an icon")
        metadata: dict[str, object] = {}
        paths: list[str] = []
        if title is not None:
            if not title.strip():
                raise ChatAPIError("title must be a non-empty string")
            if len(title) > _MAX_TITLE:
                raise ChatAPIError(
                    f"title is limited to {_MAX_TITLE} characters; got {len(title)}"
                )
            metadata["title"] = title
            paths.append("threadMetadata.title")
        if icon is not None:
            if not icon.strip():
                raise ChatAPIError("icon must be a Google Material icon name")
            metadata["icon"] = {"materialIcon": {"name": icon}}
            paths.append("threadMetadata.icon")
        await require_app_preview(self._bot, PreviewFeature.THREAD_SESSIONS, _FEATURE)
        return ThreadSession.from_rest(
            await self._transport.request(
                "PATCH",
                name,
                params={"updateMask": ",".join(paths)},
                body={"name": name, "threadMetadata": metadata},
                timeout=timeout,
            )
        )


def _thread_name(thread: ThreadRef | str) -> str:
    name = thread if isinstance(thread, str) else thread.name
    if not name or _THREAD_NAME.fullmatch(name) is None:
        raise ChatAPIError(
            "thread must be a canonical "
            f"'spaces/{{space}}/threads/{{thread}}' name; got {name!r}"
        )
    return name
