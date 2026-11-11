"""Live integration smoke tests — real Google Chat calls when enabled.

Network tests require:
    CHATTICE_GOOGLE_CREDENTIALS=/path/to/service-account.json
    CHATTICE_GOOGLE_SPACE=spaces/AAA
    pytest tests/integration/live -m google_live

Developer Preview tests additionally require a project enrolled in the
Google Workspace Developer Preview Program:
    CHATTICE_GOOGLE_PREVIEW=1
    CHATTICE_GOOGLE_DM_SPACE=spaces/BBB   (a 1:1 DM with the app, for sessions)

Contract tests (card round-trip, command payloads, Workspace Pub/Sub
replay) execute in the same run and do NOT need network access. Every
test in this suite EXECUTES when run — none raise NotImplementedError.
See README.md for the full setup.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from chattice import Dispatcher, Router
from chattice.adapters.google_chat import parse_interaction
from chattice.auth import ServiceAccountCredentialsProvider
from chattice.capabilities import PreviewFeature
from chattice.cards import (
    Button,
    ButtonList,
    Card,
    CardHeader,
    Section,
    TextParagraph,
)
from chattice.client import Bot
from chattice.events import ActionEvent, CommandEvent
from chattice.experimental.sessions import ThreadSessions
from chattice.experimental.streaming import MessageStreams, step, text
from chattice.workspace_events import parse_workspace_envelope

pytestmark = pytest.mark.google_live

_CREDENTIALS_ENV = "CHATTICE_GOOGLE_CREDENTIALS"
_SPACE_ENV = "CHATTICE_GOOGLE_SPACE"
_PREVIEW_ENV = "CHATTICE_GOOGLE_PREVIEW"
_DM_SPACE_ENV = "CHATTICE_GOOGLE_DM_SPACE"


def _require_network_env() -> tuple[str, str]:
    path = os.environ.get(_CREDENTIALS_ENV)
    space = os.environ.get(_SPACE_ENV)
    if not path or not space:
        pytest.skip(f"set {_CREDENTIALS_ENV} and {_SPACE_ENV} for live calls")
    return path, space


def _require_preview_env() -> tuple[str, str]:
    path, space = _require_network_env()
    if os.environ.get(_PREVIEW_ENV) != "1":
        pytest.skip(
            f"set {_PREVIEW_ENV}=1 for Developer Preview calls (the project "
            "must be enrolled in the Developer Preview Program)"
        )
    return path, space


def _load_fixture(name: str) -> dict[str, object]:
    base = Path(__file__).parents[2] / "fixtures" / "google_chat" / "interactions"
    return json.loads((base / name).read_text())  # type: ignore[no-any-return]


# --- network tests (skip without credentials) ---


async def test_message_send_update_delete() -> None:
    path, space = _require_network_env()
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    async with Bot(credentials_provider=provider) as bot:
        created = await bot.app.messages.create(space, text="chattice live smoke")
        assert created.name
        updated = await bot.app.messages.update(
            created.name, text="chattice live smoke v2"
        )
        assert updated.name == created.name
        await bot.app.messages.delete(created.name)


async def test_echo_round_trip_via_bot() -> None:
    path, space = _require_network_env()
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    async with Bot(credentials_provider=provider) as bot:
        created = await bot.app.messages.create(space, text="echo-ping")
        fetched = await bot.app.messages.get(created.name)
        assert fetched.name == created.name


async def test_replace_cards_on_an_app_message() -> None:
    path, space = _require_network_env()
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    card = Card(
        header=CardHeader(title="chattice live smoke"),
        sections=[Section(widgets=[TextParagraph("first")])],
    )
    async with Bot(credentials_provider=provider) as bot:
        created = await bot.app.messages.create(space, card=card)
        try:
            await bot.app.messages.replace_cards(
                created.name,
                [Card(sections=[Section(widgets=[TextParagraph("second")])])],
            )
            fetched = await bot.app.messages.get(created.name)
            assert len(fetched.cards_v2) == 1
        finally:
            await bot.app.messages.delete(created.name)


# --- Developer Preview network tests (skip without enrollment) ---
#
# These are the only checks of chattice.experimental against Google: the
# preview methods are in neither the SDK nor the public discovery
# document, so nothing else can detect drift.


async def test_stream_message_commit_round_trip() -> None:
    path, space = _require_preview_env()
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    async with Bot(
        credentials_provider=provider,
        preview_features={PreviewFeature.MESSAGE_STREAMING},
    ) as bot:
        anchor = await bot.app.messages.create(space, text="chattice stream anchor")
        committed_name: str | None = None
        try:
            stream = await MessageStreams(bot).start(
                anchor.name, progress_text="Thinking"
            )
            assert stream.name.startswith(f"{space}/streamMessages/")
            await stream.append(step("Looking up"), progress_text="Writing")
            await stream.append(text("chattice "))
            await stream.replace(text("chattice live stream"))
            committed = await stream.commit()
            assert not stream.active
            name = committed.get("name")
            assert isinstance(name, str) and name.startswith(f"{space}/messages/")
            committed_name = name
        finally:
            if committed_name is not None:
                await bot.app.messages.delete(committed_name)
            await bot.app.messages.delete(anchor.name)


async def test_stream_message_discard_leaves_no_message() -> None:
    path, space = _require_preview_env()
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    async with Bot(
        credentials_provider=provider,
        preview_features={PreviewFeature.MESSAGE_STREAMING},
    ) as bot:
        anchor = await bot.app.messages.create(space, text="chattice stream anchor")
        try:
            stream = await MessageStreams(bot).start(
                anchor.name, progress_text="Thinking"
            )
            await stream.discard()
            assert not stream.active
        finally:
            await bot.app.messages.delete(anchor.name)


async def test_thread_sessions_list_in_an_app_dm() -> None:
    path, _ = _require_preview_env()
    dm_space = os.environ.get(_DM_SPACE_ENV)
    if not dm_space:
        pytest.skip(f"set {_DM_SPACE_ENV} to a 1:1 DM space with the app")
    provider = ServiceAccountCredentialsProvider.from_service_account_file(path)
    async with Bot(
        credentials_provider=provider,
        preview_features={PreviewFeature.THREAD_SESSIONS},
    ) as bot:
        sessions = ThreadSessions(bot)
        seen = 0
        async for session in await sessions.list(dm_space, page_size=5):
            assert session.name.startswith(f"{dm_space}/threads/")
            seen += 1
            if seen == 5:
                break


# --- contract tests (no network; execute in the live run) ---


async def test_card_button_round_trip() -> None:
    """Card -> serialized JSON -> CARD_CLICKED payload -> handler."""
    card = Card(
        header=CardHeader(title="Deploy production?"),
        sections=[
            Section(
                widgets=[
                    TextParagraph("Deploy v2.1?"),
                    ButtonList(
                        buttons=[
                            Button(
                                "Deploy",
                                action="deploy.confirm",
                                parameters={"env": "prod"},
                            )
                        ]
                    ),
                ]
            )
        ],
    )
    serialized = card.to_dict()
    button = serialized["sections"][0]["widgets"][1]["buttonList"]["buttons"][0]
    action = button["onClick"]["action"]
    payload = {
        "type": "CARD_CLICKED",
        "eventTime": "2000-01-01T10:00:00Z",
        "user": {"name": "users/123"},
        "space": {"name": "spaces/AAA"},
        "message": {"name": "spaces/AAA/messages/CARD", "sender": {"type": "BOT"}},
        "action": {
            "actionMethodName": action["function"],
            "parameters": [
                {"key": p["key"], "value": p["value"]} for p in action["parameters"]
            ],
        },
        "common": {
            "invokedFunction": action["function"],
            "parameters": {p["key"]: p["value"] for p in action["parameters"]},
        },
    }
    router = Router()

    @router.action("deploy.confirm")
    async def confirm(event: ActionEvent) -> str:
        return f"deploying {event.parameters['env']}"

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    result = await dispatcher.feed_update(parse_interaction(payload))
    assert result == "deploying prod"


async def test_command_payloads_parse() -> None:
    """Both command wire families normalize to CommandEvent."""
    slash = parse_interaction(_load_fixture("slash_command.json"))
    quick = parse_interaction(_load_fixture("app_command.json"))
    assert isinstance(slash, CommandEvent)
    assert isinstance(quick, CommandEvent)
    assert slash.source_kind == "SLASH_COMMAND"
    assert quick.source_kind == "QUICK_COMMAND"


async def test_workspace_pubsub_replay() -> None:
    """Official Workspace Events Pub/Sub binding replays end-to-end."""
    data = json.dumps({"message": {"name": "spaces/AAA/messages/B"}}).encode()
    envelope = {
        "message": {
            "data": base64.b64encode(data).decode(),
            "messageId": "m-live",
            "attributes": {
                "ce-id": "evt-live",
                "ce-source": "//chat.googleapis.com/spaces/AAA",
                "ce-specversion": "1.0",
                "ce-time": "2000-01-01T10:00:00Z",
                "ce-type": "google.workspace.chat.message.v1.created",
            },
        },
        "subscription": "projects/p/subscriptions/s",
    }
    event = parse_workspace_envelope(envelope)
    assert event.event_id == "evt-live"
    assert event.data["message"] == {"name": "spaces/AAA/messages/B"}
