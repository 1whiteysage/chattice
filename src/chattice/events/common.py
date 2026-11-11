"""Common interaction metadata values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WireFormat(StrEnum):
    """Which Google payload family delivered an interaction.

    Google sends the same user interaction in two JSON shapes, depending
    on how the Chat app is configured in the Google Cloud console. The
    synchronous response must use the matching shape, so the event keeps
    the family it arrived in.
    """

    # Chat API interaction events: a top-level ``type`` discriminator.
    CHAT_API = "chat_api"
    # Google Workspace add-on event objects: ``chat.<trigger>Payload``.
    ADDON = "addon"


class DialogEventType(StrEnum):
    """Stable documented Google Chat dialog interaction types."""

    REQUEST_DIALOG = "REQUEST_DIALOG"
    SUBMIT_DIALOG = "SUBMIT_DIALOG"
    CANCEL_DIALOG = "CANCEL_DIALOG"


@dataclass(frozen=True, slots=True, kw_only=True)
class DialogMetadata:
    """Incoming dialog state without any response-building behavior."""

    type: DialogEventType | str
    is_dialog_event: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeZone:
    """Locale-independent timezone metadata supplied by Google."""

    id: str | None = None
    offset_ms: int | None = None


__all__ = ["DialogEventType", "DialogMetadata", "TimeZone", "WireFormat"]
