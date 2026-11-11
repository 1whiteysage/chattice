"""SYSTEM_COMMAND (stream cancellation): parsing and preview-gated routing."""

from __future__ import annotations

import json
from pathlib import Path

from chattice import Dispatcher, Router
from chattice.adapters.google_chat import parse_interaction
from chattice.capabilities import PreviewFeature
from chattice.events import Event, SystemCommandEvent
from chattice.testing import EventFactory

FIXTURE = Path("tests/fixtures/google_chat/interactions")
STREAM = "spaces/SPACE_ID/streamMessages/STREAM_ID"


def _payload() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(
        (FIXTURE / "system_command_cancel_stream.json").read_text()
    )
    return loaded


def test_cancel_stream_payload_parses_to_system_command_event() -> None:
    event = parse_interaction(_payload())
    assert isinstance(event, SystemCommandEvent)
    assert event.event_type == "system_command"
    assert event.cancel_stream == STREAM
    assert event.space is not None and event.space.name == "spaces/SPACE_ID"
    assert event.actor is not None and event.actor.name == "users/USER_ID"


def test_unmodeled_system_command_keeps_raw_payload() -> None:
    payload = _payload()
    payload["systemCommandMetadata"] = {"futureCommand": {"value": 1}}
    event = parse_interaction(payload)
    assert isinstance(event, SystemCommandEvent)
    assert event.cancel_stream is None
    assert event.raw == payload


def _router(calls: list[str]) -> Router:
    router = Router()

    @router.system_command()
    async def cancelled(event: SystemCommandEvent) -> None:
        calls.append(f"typed:{event.cancel_stream}")

    @router.event()
    async def fallback(event: Event) -> None:
        calls.append("fallback")

    return router


async def test_typed_routing_requires_preview_enrollment() -> None:
    calls: list[str] = []
    dispatcher = Dispatcher()
    dispatcher.include_router(_router(calls))
    await dispatcher.feed_update(parse_interaction(_payload()))
    assert calls == ["fallback"]


async def test_typed_routing_with_message_streaming_preview() -> None:
    calls: list[str] = []
    dispatcher = Dispatcher(preview_features={PreviewFeature.MESSAGE_STREAMING})
    dispatcher.include_router(_router(calls))
    await dispatcher.feed_update(parse_interaction(_payload()))
    assert calls == [f"typed:{STREAM}"]


async def test_handler_can_use_the_system_command_alias() -> None:
    seen: list[object] = []
    router = Router()

    @router.system_command()
    async def cancelled(system_command) -> None:  # type: ignore[no-untyped-def]
        seen.append(system_command)

    dispatcher = Dispatcher(preview_features={PreviewFeature.MESSAGE_STREAMING})
    dispatcher.include_router(router)
    event = EventFactory.system_command(cancel_stream=STREAM)
    await dispatcher.feed_update(event)
    assert seen == [event]
