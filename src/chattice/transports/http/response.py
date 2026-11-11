"""One-shot synchronous interaction response."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .errors import DoubleResponseError


class ResponseState(Enum):
    """Whether the synchronous response has already been produced."""

    NOT_RESPONDED = "not_responded"
    RESPONDED = "responded"


@dataclass(slots=True)
class InteractionResponse:
    """Request-scoped mutable response plan; guards against double responses.

    This is intentionally not frozen: it is per-request mutable state, never
    shared between requests.
    """

    payload: object = None
    state: ResponseState = ResponseState.NOT_RESPONDED

    def respond(self, payload: object) -> None:
        """Set the synchronous response payload exactly once."""
        if self.state is ResponseState.RESPONDED:
            raise DoubleResponseError(
                "This interaction already has a synchronous response"
            )
        self.payload = payload
        self.state = ResponseState.RESPONDED


@dataclass(frozen=True, slots=True)
class RawInteractionResponse:
    """Explicit raw-response escape hatch: an arbitrary response mapping.

    Still validated against event/channel invariants (e.g. a
    REMOVED_FROM_SPACE event can never receive a response) — only the
    payload shape is the caller's responsibility.
    """

    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class WidgetAutocomplete:
    """Typed UPDATE_WIDGET response: autocomplete suggestions for a widget.

    Google's UPDATE_WIDGET response type answers a WIDGET_UPDATED
    autocomplete query. Each suggestion becomes a SelectionItem with the
    given text. In the add-on payload family the suggestion text is also
    the item's submitted value, and ``widget_id`` is not sent (the
    response applies to the widget that asked).
    """

    widget_id: str
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "actionResponse": {
                "type": "UPDATE_WIDGET",
                "updatedWidget": {
                    "widget": self.widget_id,
                    "suggestions": {
                        "items": [{"text": text} for text in self.suggestions]
                    },
                },
            }
        }


@dataclass(frozen=True, slots=True)
class RequestConfigResponse:
    """Typed REQUEST_CONFIG response: ask the user to open an auth URL.

    The missing typed DX for a wire shape previously reachable only
    through RawInteractionResponse.

    ``resource`` is the display name of the service the user connects
    (for example ``"Example Account"``). Only the add-on payload family
    shows it, in the basic authorization prompt, and requires it there.
    """

    auth_url: str
    resource: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "actionResponse": {
                "type": "REQUEST_CONFIG",
                "authUrl": self.auth_url,
            }
        }


__all__ = [
    "InteractionResponse",
    "RawInteractionResponse",
    "RequestConfigResponse",
    "ResponseState",
    "WidgetAutocomplete",
]
