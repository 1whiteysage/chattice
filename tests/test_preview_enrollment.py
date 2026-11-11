# ruff: noqa: ASYNC109 — timeout kwarg mirrors the PreviewTransport protocol
"""One Developer Preview enrollment for the Bot and the Dispatcher."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chattice import Dispatcher, Router
from chattice.capabilities import (
    DEVELOPER_PREVIEW_FEATURES,
    CapabilityNotSupported,
    PreviewCapabilities,
    PreviewFeature,
)
from chattice.client import Bot
from chattice.events import SystemCommandEvent
from chattice.experimental.sessions import ThreadSessions
from chattice.experimental.streaming import MessageStreams
from chattice.testing import EventFactory, fake_bot

STREAM = "spaces/AAA/streamMessages/s1"


class _Transport:
    """Answers every preview REST call with a minimal valid body."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        self.paths.append(path)
        if path.endswith("/streamMessages"):
            return {"name": STREAM, "nextChunkToken": "t1"}
        return {"name": path}


def _bot(*features: PreviewFeature, enable_preview: bool = False) -> Bot:
    bot, _ = fake_bot(preview_features=features, enable_preview=enable_preview)
    return bot


def test_enable_preview_enrolls_in_every_preview_feature() -> None:
    assert _bot(enable_preview=True).preview_capabilities == PreviewCapabilities.all()
    assert set(PreviewCapabilities.all()) == set(DEVELOPER_PREVIEW_FEATURES)
    assert not _bot().preview_capabilities


def test_generally_available_features_are_not_preview() -> None:
    assert PreviewFeature.PINNED_MESSAGES not in DEVELOPER_PREVIEW_FEATURES
    assert PreviewFeature.REPLACE_CARDS not in DEVELOPER_PREVIEW_FEATURES


async def test_a_named_feature_enrolls_in_that_feature_only() -> None:
    bot = _bot(PreviewFeature.MESSAGE_STREAMING)
    transport = _Transport()

    stream = await MessageStreams(bot, transport=transport).start(
        "spaces/AAA/messages/m1", progress_text="Thinking"
    )

    assert stream.name == STREAM
    with pytest.raises(CapabilityNotSupported, match="THREAD_SESSIONS"):
        await ThreadSessions(bot, transport=transport).get("spaces/DM/threads/t1")
    assert transport.paths == ["spaces/AAA/streamMessages"]


async def test_relevance_ordering_names_its_feature() -> None:
    bot, transport = fake_bot()
    with pytest.raises(CapabilityNotSupported, match="RELEVANCE_SEARCH_ORDERING"):
        await bot.user.messages.search("report", order_by="relevance desc")
    assert transport.message_searches == []


def _dispatcher(calls: list[str], **options: object) -> Dispatcher:
    router = Router()

    @router.system_command()
    async def cancelled(event: SystemCommandEvent) -> None:
        calls.append("typed")

    dispatcher = Dispatcher(**options)  # type: ignore[arg-type]
    dispatcher.include_router(router)
    return dispatcher


async def test_dispatcher_uses_the_enrollment_of_its_bot() -> None:
    calls: list[str] = []
    dispatcher = _dispatcher(calls, bot=_bot(PreviewFeature.MESSAGE_STREAMING))

    await dispatcher.feed_update(EventFactory.system_command(cancel_stream=STREAM))

    assert calls == ["typed"]
    assert PreviewFeature.MESSAGE_STREAMING in dispatcher.preview_capabilities


async def test_dispatcher_combines_its_own_features_with_the_bot() -> None:
    dispatcher = Dispatcher(
        bot=_bot(PreviewFeature.THREAD_SESSIONS),
        preview_features={PreviewFeature.MESSAGE_STREAMING},
    )
    assert set(dispatcher.preview_capabilities) == {
        PreviewFeature.THREAD_SESSIONS,
        PreviewFeature.MESSAGE_STREAMING,
    }


async def test_a_bot_passed_per_update_does_not_enroll_the_dispatcher() -> None:
    calls: list[str] = []
    dispatcher = _dispatcher(calls)

    await dispatcher.feed_update(
        EventFactory.system_command(cancel_stream=STREAM),
        bot=_bot(enable_preview=True),
    )

    assert calls == []


async def test_a_bot_without_enrollment_keeps_preview_routing_off() -> None:
    calls: list[str] = []
    dispatcher = _dispatcher(calls, bot=_bot())

    await dispatcher.feed_update(EventFactory.system_command(cancel_stream=STREAM))

    assert calls == []
