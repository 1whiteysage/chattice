"""System command interaction events sent by Google Chat itself."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Event


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemCommandEvent(Event):
    """Google Chat asked the app to do something on the user's behalf.

    Developer Preview. The only documented system command is a stream
    cancellation: the user pressed Stop on an active stream message, and
    ``cancel_stream`` holds its ``spaces/{space}/streamMessages/{id}``
    resource name. ``cancel_stream`` is ``None`` for a system command
    this version does not model; ``raw`` keeps the full payload.
    """

    event_type: str = field(default="system_command", init=False)
    cancel_stream: str | None = None


__all__ = ["SystemCommandEvent"]
