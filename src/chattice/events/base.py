"""Framework-owned event primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .common import DialogMetadata, TimeZone, WireFormat
from .references import SpaceRef, ThreadRef, UserRef


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Base class for transport-independent domain events."""

    event_type: str = "event"
    raw: object = field(default=None, repr=False, compare=False)
    event_time: datetime | None = None
    actor: UserRef | None = None
    space: SpaceRef | None = None
    thread: ThreadRef | None = None
    dialog: DialogMetadata | None = None
    locale: str | None = None
    timezone: TimeZone | None = None
    # The payload family the interaction arrived in; the synchronous
    # response is serialized in the same family.
    wire_format: WireFormat = WireFormat.CHAT_API
