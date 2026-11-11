"""Card actions for Chat apps built as Google Workspace add-ons (HTTP).

A Chat app that Google calls through Chat API interaction events names a
card action by an arbitrary ``function`` string. An HTTP add-on must put
the HTTPS endpoint that handles the click into ``function`` instead:
https://developers.google.com/workspace/add-ons/chat/dialogs

To keep ``@router.action("name")`` working in both configurations, a
bound action sends the handler name in one reserved parameter next to
the endpoint URL. The inbound adapter moves it back, so handlers never
see the parameter.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from google.protobuf import json_format  # type: ignore[import-untyped]

from .card import Card

__all__ = [
    "ADDON_FUNCTION_PARAMETER",
    "bind_addon_actions",
    "bind_addon_actions_json",
    "bind_addon_actions_proto",
]

_ProtoT = TypeVar("_ProtoT")

# Reserved action parameter that carries the handler name.
ADDON_FUNCTION_PARAMETER = "chattice_function"


def _is_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def _validate_action_url(action_url: str) -> None:
    if not isinstance(action_url, str) or not action_url.startswith("https://"):
        raise ValueError(
            "The add-on action URL must be the absolute HTTPS endpoint that "
            f"receives card interactions; got {action_url!r}"
        )


def _bind(value: Any, action_url: str) -> Any:
    if isinstance(value, list):
        return [_bind(item, action_url) for item in value]
    if not isinstance(value, dict):
        return value
    bound = {key: _bind(item, action_url) for key, item in value.items()}
    function = bound.get("function")
    # In Cards v2 JSON only an Action object has a string ``function``.
    if not isinstance(function, str) or not function or _is_url(function):
        return bound
    parameters = list(bound.get("parameters") or [])
    for parameter in parameters:
        if isinstance(parameter, dict) and (
            parameter.get("key") == ADDON_FUNCTION_PARAMETER
        ):
            raise ValueError(
                f"The action parameter {ADDON_FUNCTION_PARAMETER!r} is "
                "reserved for add-on action binding"
            )
    parameters.append({"key": ADDON_FUNCTION_PARAMETER, "value": function})
    bound["function"] = action_url
    bound["parameters"] = parameters
    return bound


def bind_addon_actions_json(payload: Any, action_url: str) -> Any:
    """Return a copy of Cards v2 JSON with every action bound to a URL.

    Each action whose ``function`` is a handler name gets ``action_url``
    as its function and the name in the reserved parameter. Actions that
    already point at a URL are left unchanged, so binding twice is safe.
    """
    _validate_action_url(action_url)
    return _bind(payload, action_url)


def bind_addon_actions(card: Card, action_url: str) -> Card:
    """Return a copy of ``card`` whose actions call an HTTP add-on endpoint."""
    return Card.from_dict(bind_addon_actions_json(card.to_dict(), action_url))


def bind_addon_actions_proto(proto: _ProtoT, action_url: str) -> _ProtoT:
    """Return a copy of a card-carrying SDK proto with its actions bound.

    Accepts the proto-plus messages that hold card actions, such as a
    Card or an AccessoryWidget.
    """
    cls: Any = type(proto)
    data = json.loads(json_format.MessageToJson(proto._pb))  # type: ignore[attr-defined]
    bound = bind_addon_actions_json(data, action_url)
    return cls(json_format.Parse(json.dumps(bound), cls.pb()()))  # type: ignore[no-any-return]
