"""Outbound cards of a Chat app built as an HTTP Google Workspace add-on."""

from __future__ import annotations

import pytest

from chattice.cards import AccessoryWidget, Button, ButtonList, Card, Section
from chattice.cards.addon import ADDON_FUNCTION_PARAMETER
from chattice.client import Bot
from chattice.testing import fake_bot

ACTION_URL = "https://bot.example.com/chat"


def _buttons() -> ButtonList:
    return ButtonList(
        buttons=[
            Button(text="Approve", action="invoice.approve", parameters={"id": "7"})
        ]
    )


def _card() -> Card:
    return Card(sections=[Section(widgets=[_buttons()])])


def _parameters(action: object) -> dict[str, str]:
    return {item.key: item.value for item in action.parameters}  # type: ignore[attr-defined]


async def test_created_card_and_accessory_widget_call_the_addon_endpoint() -> None:
    bot, transport = fake_bot(addon_action_url=ACTION_URL)

    await bot.app.messages.create(
        "spaces/AAA",
        "Invoice 7",
        card=_card(),
        accessory_widgets=[AccessoryWidget(button_list=_buttons())],
    )

    message = transport.requests[-1].message
    card_action = (
        message.cards_v2[0].card.sections[0].widgets[0].button_list.buttons[0]
    ).on_click.action
    accessory_action = (
        message.accessory_widgets[0].button_list.buttons[0].on_click.action
    )
    for action in (card_action, accessory_action):
        assert action.function == ACTION_URL
        assert _parameters(action) == {
            "id": "7",
            ADDON_FUNCTION_PARAMETER: "invoice.approve",
        }


async def test_updated_and_replaced_cards_are_bound_too() -> None:
    bot, transport = fake_bot(addon_action_url=ACTION_URL)

    created = await bot.app.messages.create("spaces/AAA", "Invoice 7")
    await bot.app.messages.update(created.name, card=_card())
    await bot.app.messages.replace_cards(created.name, [_card()])

    updated = transport.updates[-1].message.cards_v2[0].card
    replaced = transport.card_replacements[-1].cards_v2[0].card
    for card in (updated, replaced):
        action = card.sections[0].widgets[0].button_list.buttons[0].on_click.action
        assert action.function == ACTION_URL


async def test_without_an_action_url_cards_are_sent_as_authored() -> None:
    bot, transport = fake_bot()

    await bot.app.messages.create("spaces/AAA", card=_card())

    action = (
        transport.requests[-1]
        .message.cards_v2[0]
        .card.sections[0]
        .widgets[0]
        .button_list.buttons[0]
        .on_click.action
    )
    assert action.function == "invoice.approve"
    assert _parameters(action) == {"id": "7"}


def test_action_url_must_be_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        Bot(addon_action_url="http://bot.example.com/chat")
