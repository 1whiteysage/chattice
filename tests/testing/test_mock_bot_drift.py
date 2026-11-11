"""MockBot stays in step with the real client, and says what it omits."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from google.apps.chat_v1.types.message import Message
from google.apps.chat_v1.types.space import Space

from chattice.client.config import RequestConfig
from chattice.client.resources import Messages, Spaces
from chattice.testing import MockBot

# The whole mirrored surface: MockBot facade class -> real resource class.
_MIRRORED: dict[str, type] = {"messages": Messages, "spaces": Spaces}
_MIRRORED_METHODS = [
    ("messages", "create"),
    ("messages", "delete"),
    ("messages", "get"),
    ("messages", "replace_cards"),
    ("messages", "update"),
    ("spaces", "get"),
]
_POSITIONAL = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _facade(resource: str) -> Any:
    return getattr(MockBot().app, resource)


def _parameters(method: Callable[..., object]) -> dict[str, inspect.Parameter]:
    parameters = dict(inspect.signature(method).parameters)
    parameters.pop("self", None)
    return parameters


def test_drift_check_covers_every_mirrored_method() -> None:
    mirrored = [
        (resource, name)
        for resource in _MIRRORED
        for name, member in vars(type(_facade(resource))).items()
        if not name.startswith("_") and inspect.isfunction(member)
    ]
    assert sorted(mirrored) == _MIRRORED_METHODS


@pytest.mark.parametrize(("resource", "method"), _MIRRORED_METHODS)
def test_facade_accepts_every_parameter_of_the_real_method(
    resource: str, method: str
) -> None:
    real = _parameters(getattr(_MIRRORED[resource], method))
    mock = _parameters(getattr(_facade(resource), method))

    missing = sorted(set(real) - set(mock))
    assert not missing, (
        f"MockBot {resource}.{method}() does not accept {missing}; add them "
        "to the facade in chattice/testing/mock_bot.py"
    )
    kinds = {name: (real[name].kind, mock[name].kind) for name in real}
    assert all(ours == theirs for theirs, ours in kinds.values()), kinds
    assert [name for name in mock if mock[name].kind in _POSITIONAL] == [
        name for name in real if real[name].kind in _POSITIONAL
    ]


@pytest.mark.parametrize(("resource", "method"), _MIRRORED_METHODS)
def test_facade_accepts_nothing_the_real_method_rejects(
    resource: str, method: str
) -> None:
    real = _parameters(getattr(_MIRRORED[resource], method))
    mock = _parameters(getattr(_facade(resource), method))

    extra = sorted(set(mock) - set(real))
    assert not extra, (
        f"MockBot {resource}.{method}() accepts {extra}, which the real client "
        "rejects; a test would pass on a call that fails in production"
    )


@pytest.mark.parametrize(
    "resource",
    ["memberships", "reactions", "users", "message_pins", "custom_emojis"],
)
@pytest.mark.parametrize("identity", ["app", "user"])
def test_unmodelled_resource_names_itself_and_the_fake_bot(
    identity: str, resource: str
) -> None:
    namespace = getattr(MockBot(), identity)

    with pytest.raises(AttributeError) as raised:
        getattr(namespace, resource)

    message = str(raised.value)
    assert f"bot.{identity}.{resource}" in message
    assert "chattice.testing.fake_bot()" in message
    assert not hasattr(namespace, resource)


def test_unmodelled_method_names_itself_and_the_fake_bot() -> None:
    bot = MockBot()

    with pytest.raises(AttributeError, match=r"bot\.user\.messages\.search") as raised:
        _ = bot.user.messages.search  # type: ignore[attr-defined]
    assert "fake_bot()" in str(raised.value)
    with pytest.raises(AttributeError, match=r"bot\.app\.spaces\.list"):
        _ = bot.app.spaces.list  # type: ignore[attr-defined]


def test_private_lookups_keep_the_plain_attribute_error() -> None:
    with pytest.raises(AttributeError) as raised:
        _ = MockBot().app._missing  # type: ignore[attr-defined]

    assert str(raised.value) == "'_MockIdentity' object has no attribute '_missing'"


async def test_config_is_accepted_by_every_mirrored_read_and_write() -> None:
    bot = MockBot()
    config = RequestConfig(timeout=5.0)

    await bot.app.messages.get("spaces/AAA/messages/1", config=config)
    await bot.app.messages.update("spaces/AAA/messages/1", "new", config=config)
    await bot.app.messages.replace_cards("spaces/AAA/messages/1", [], config=config)
    await bot.app.messages.delete("spaces/AAA/messages/1", config=config)
    await bot.app.spaces.get("spaces/AAA", config=config)

    assert [kind for kind, _ in bot.calls] == [
        "get_message",
        "update_message",
        "replace_cards",
        "delete_message",
        "get_space",
    ]
    # Like timeout, config is transport plumbing: accepted, never recorded.
    assert all("config" not in args for _, args in bot.calls)


class _ExplicitSignatureBot(MockBot):
    """A user subclass overriding recorders with their published signatures."""

    async def update_message(
        self,
        name: str,
        text: str | None = None,
        *,
        card: Any = None,
        timeout: float | None = None,  # noqa: ASYNC109 — mirrors the recorder
    ) -> Message:
        return await super().update_message(name, text, card=card, timeout=timeout)

    async def get_space(
        self,
        name: str,
        *,
        timeout: float | None = None,  # noqa: ASYNC109 — mirrors the recorder
    ) -> Space:
        return await super().get_space(name, timeout=timeout)


async def test_recorder_overrides_keep_working_when_config_is_passed() -> None:
    bot = _ExplicitSignatureBot()
    config = RequestConfig(timeout=5.0)

    await bot.app.messages.update("spaces/AAA/messages/1", "new", config=config)
    await bot.app.spaces.get("spaces/AAA", config=config)

    bot.assert_updated("spaces/AAA/messages/1", "new")
    assert bot.calls[-1] == ("get_space", {"name": "spaces/AAA"})
