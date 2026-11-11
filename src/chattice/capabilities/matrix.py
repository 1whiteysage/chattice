"""Capability model: ingress response channel and preview features.

- :class:`ResponseCapabilities` — derived from the transport plus the
  concrete interaction event (dialogs, App Home, matched URL, bot/human
  sender, widget autocomplete).
- :class:`PreviewFeature` — Developer Preview Google features, a stability
  flag, not an auth capability.

Outbound authorization lives in the OperationRegistry (the single
source of outbound auth truth); every outbound call preflights through
it via the OperationExecutor.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import Enum, auto

from chattice.events import (
    ActionEvent,
    ActionSource,
    AppHomeEvent,
    CommandEvent,
    DialogEventType,
    Event,
    FormSubmitEvent,
    MessageEvent,
    WidgetUpdatedEvent,
    WireFormat,
)

__all__ = [
    "DEVELOPER_PREVIEW_FEATURES",
    "PREVIEW_APP_COMMAND_TYPES",
    "CapabilityNotSupported",
    "PreviewCapabilities",
    "PreviewFeature",
    "ResponseCapabilities",
    "ResponseCapability",
    "can_open_dialog",
]


def can_open_dialog(event: Event | None) -> bool:
    """Return whether an event may open a dialog.

    Commands always can; actions only when Google delivered them WITH
    REQUEST_DIALOG metadata. SUBMIT/CANCEL actions cannot return a new
    dialog, and a plain Message cannot open one either.
    """
    if isinstance(event, CommandEvent):
        return True
    if isinstance(event, ActionEvent) and event.dialog is not None:
        return event.dialog.type == DialogEventType.REQUEST_DIALOG
    return False


_TRANSPORTS = ("http", "pubsub")


class CapabilityNotSupported(RuntimeError):
    """An operation was attempted without its required capability."""


class ResponseCapability(Enum):
    """What the synchronous ingress response channel can do."""

    SYNC_RESPONSE = auto()
    DIALOGS = auto()
    APP_HOME = auto()
    CARD_UPDATE_BOT = auto()
    CARD_UPDATE_USER = auto()
    UPDATE_WIDGET = auto()


_RESPONSE_DESCRIPTIONS: dict[ResponseCapability, str] = {
    ResponseCapability.SYNC_RESPONSE: (
        "The HTTP interaction transport provides a 30-second synchronous "
        "response channel."
    ),
    ResponseCapability.DIALOGS: "Dialogs require the HTTP interaction transport.",
    ResponseCapability.APP_HOME: (
        "App Home responses require an APP_HOME or SUBMIT_FORM interaction."
    ),
    ResponseCapability.CARD_UPDATE_BOT: (
        "UPDATE_MESSAGE responses require a CARD_CLICKED on a bot message "
        "(message sender type BOT)."
    ),
    ResponseCapability.CARD_UPDATE_USER: (
        "UPDATE_USER_MESSAGE_CARDS responses require a CARD_CLICKED on a "
        "human message or a MESSAGE with a matched URL."
    ),
    ResponseCapability.UPDATE_WIDGET: (
        "UPDATE_WIDGET autocomplete responses require a WIDGET_UPDATED event."
    ),
}


def _action_capabilities(event: ActionEvent) -> set[ResponseCapability]:
    """How a card click can be answered, from where the card lives."""
    capabilities: set[ResponseCapability] = set()
    if event.wire_format is WireFormat.ADDON and event.source is ActionSource.HOME:
        # Add-on homepage card click: answered with updateCard.
        capabilities.add(ResponseCapability.APP_HOME)
    if event.sender_type == "BOT":
        capabilities.add(ResponseCapability.CARD_UPDATE_BOT)
    elif event.sender_type == "HUMAN":
        capabilities.add(ResponseCapability.CARD_UPDATE_USER)
    return capabilities


class ResponseCapabilities:
    """An immutable response-channel capability set with require() guards."""

    def __init__(
        self, capabilities: frozenset[ResponseCapability] | set[ResponseCapability]
    ) -> None:
        self._capabilities = frozenset(capabilities)

    def __contains__(self, capability: ResponseCapability) -> bool:
        return capability in self._capabilities

    def __iter__(self) -> Iterator[ResponseCapability]:
        return iter(self._capabilities)

    def require(self, capability: ResponseCapability) -> None:
        """Raise CapabilityNotSupported when the capability is missing."""
        if capability in self._capabilities:
            return
        detail = _RESPONSE_DESCRIPTIONS.get(capability, "")
        message = f"{capability.name} is not supported in this configuration. {detail}"
        raise CapabilityNotSupported(message.rstrip())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResponseCapabilities):
            return NotImplemented
        return self._capabilities == other._capabilities

    @classmethod
    def resolve(
        cls, *, transport: str = "http", event: Event | None = None
    ) -> ResponseCapabilities:
        """Resolve the response-channel capabilities for a transport + event.

        HTTP provides the sync response channel and dialogs; Pub/Sub push
        provides NO response channel (ack-only). Event-specific response
        rules are derived from the concrete event, never guessed.
        """
        if transport not in _TRANSPORTS:
            raise ValueError(
                f"Unknown transport {transport!r}; supported: {', '.join(_TRANSPORTS)}"
            )
        if transport == "pubsub":
            return cls(set())
        capabilities: set[ResponseCapability] = {ResponseCapability.SYNC_RESPONSE}
        # DIALOGS only for events that can actually open a dialog
        # (command / REQUEST_DIALOG action) — a plain Message advertising
        # DIALOGS produced 500s at serialization.
        if can_open_dialog(event):
            capabilities.add(ResponseCapability.DIALOGS)
        if isinstance(event, (AppHomeEvent, FormSubmitEvent)):
            capabilities.add(ResponseCapability.APP_HOME)
        if isinstance(event, WidgetUpdatedEvent):
            capabilities.add(ResponseCapability.UPDATE_WIDGET)
        if isinstance(event, ActionEvent):
            capabilities.update(_action_capabilities(event))
        if isinstance(event, MessageEvent) and event.matched_url is not None:
            capabilities.add(ResponseCapability.CARD_UPDATE_USER)
        return cls(capabilities)


class PreviewFeature(Enum):
    """Developer Preview Google features (stability flags, not auth).

    Sources: Google Chat release notes. These exist
    so documentation and code reference ONE list of preview surfaces.
    """

    # Generally available; the values remain accepted for compatibility.
    MESSAGE_ACTION = auto()  # APP_COMMAND message actions
    REPLACE_CARDS = auto()  # messages.replaceCards
    USER_AUTH_CARDS = auto()  # card creation with user auth
    CUSTOMER_LEVEL_SUBSCRIPTIONS = auto()  # Workspace Events customer-level
    PINNED_MESSAGES = auto()  # spaces.messagePins
    # Developer Preview.
    RELEVANCE_SEARCH_ORDERING = auto()  # messages search ordered by relevance
    MESSAGE_STREAMING = auto()  # spaces.streamMessages and SYSTEM_COMMAND
    THREAD_SESSIONS = auto()  # 1:1 DM sessions through spaces.threads


# Features that are in Developer Preview today. ``enable_preview=True``
# enrolls in exactly these.
DEVELOPER_PREVIEW_FEATURES: frozenset[PreviewFeature] = frozenset(
    {
        PreviewFeature.RELEVANCE_SEARCH_ORDERING,
        PreviewFeature.MESSAGE_STREAMING,
        PreviewFeature.THREAD_SESSIONS,
    }
)


class PreviewCapabilities:
    """The Developer Preview features an application has enrolled in.

    One set governs both directions: outbound preview calls on the
    ``Bot`` and typed routing of preview events in the ``Dispatcher``.
    Configure it once on the Bot (``enable_preview=True`` or
    ``preview_features=...``); a ``Dispatcher(bot=bot)`` uses the same
    enrollment.
    """

    def __init__(self, features: Iterable[PreviewFeature] = ()) -> None:
        self._features = frozenset(features)

    @classmethod
    def all(cls) -> PreviewCapabilities:
        """Enrollment in every feature that is in Developer Preview."""
        return cls(DEVELOPER_PREVIEW_FEATURES)

    def __contains__(self, feature: PreviewFeature) -> bool:
        return feature in self._features

    def __iter__(self) -> Iterator[PreviewFeature]:
        return iter(self._features)

    def __bool__(self) -> bool:
        return bool(self._features)

    def __or__(self, other: PreviewCapabilities) -> PreviewCapabilities:
        if not isinstance(other, PreviewCapabilities):
            return NotImplemented
        return PreviewCapabilities(self._features | other._features)

    def require(self, feature: PreviewFeature, *, what: str | None = None) -> None:
        """Raise ``CapabilityNotSupported`` unless ``feature`` is enrolled.

        ``what`` names the attempted action in the error message.
        """
        if feature in self._features:
            return
        subject = what or feature.name
        raise CapabilityNotSupported(
            f"{subject} is a Google Developer Preview and requires explicit "
            "opt-in: Bot(..., enable_preview=True) or "
            f"preview_features={{PreviewFeature.{feature.name}}}."
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PreviewCapabilities):
            return NotImplemented
        return self._features == other._features

    def __hash__(self) -> int:
        return hash(self._features)


# APP_COMMAND types that are Developer Preview: the adapter accepts them
# forward-compatibly (CommandEvent.source_kind carries the wire string) but
# they are not advertised as stable.
PREVIEW_APP_COMMAND_TYPES: frozenset[str] = frozenset()
