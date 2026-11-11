"""Cached, signature-based handler dependency resolution."""

from __future__ import annotations

import inspect
import types
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, TypeAlias, Union, get_args, get_origin, get_type_hints

from chattice.events import (
    ActionEvent,
    AddedToSpaceEvent,
    AppHomeEvent,
    CommandEvent,
    DialogEventType,
    ErrorEvent,
    Event,
    FormSubmitEvent,
    MessageEvent,
    RemovedFromSpaceEvent,
    SystemCommandEvent,
    UnknownEvent,
    WidgetUpdatedEvent,
)
from chattice.exceptions import DependencyResolutionError, InvalidHandlerError

HandlerCallback: TypeAlias = Callable[..., object]


def handler_qualified_name(callback: HandlerCallback) -> str:
    """Return a stable, useful name for a registered handler."""
    module = getattr(callback, "__module__", None)
    qualified_name = getattr(callback, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualified_name, str):
        return f"{module}.{qualified_name}"
    if isinstance(qualified_name, str):
        return qualified_name
    return repr(callback)


@dataclass(frozen=True, slots=True)
class ParameterPlan:
    """How one handler parameter can be resolved."""

    name: str
    event_types: tuple[type[Event], ...]
    event_alias: bool
    has_default: bool


@dataclass(frozen=True, slots=True)
class HandlerPlan:
    """A cached callback signature without request-specific values."""

    callback: HandlerCallback
    parameters: tuple[ParameterPlan, ...]

    async def invoke(self, event: Event, data: Mapping[str, object]) -> object:
        """Resolve this invocation and await the callback result."""
        kwargs: dict[str, object] = {}
        aliases = _event_aliases(event)
        for parameter in self.parameters:
            if parameter.event_types:
                if not isinstance(event, parameter.event_types):
                    expected = ", ".join(cls.__name__ for cls in parameter.event_types)
                    raise DependencyResolutionError(
                        f"Parameter {parameter.name!r} for handler "
                        f"{handler_qualified_name(self.callback)!r} requires "
                        f"{expected}, received {type(event).__name__} while "
                        f"handling {type(event).__name__}."
                    )
                kwargs[parameter.name] = event
            elif parameter.event_alias and parameter.name in aliases:
                kwargs[parameter.name] = event
            elif parameter.name in data:
                kwargs[parameter.name] = data[parameter.name]
            elif not parameter.has_default:
                raise DependencyResolutionError(
                    f"Cannot resolve parameter {parameter.name!r} for handler "
                    f"{handler_qualified_name(self.callback)!r} while handling "
                    f"{type(event).__name__}. The dependency was not provided by "
                    "the event, dispatcher context, middleware, or dependency "
                    "injection."
                )

        result = self.callback(**kwargs)
        if not inspect.isawaitable(result):
            raise InvalidHandlerError(
                f"Handler {self.callback!r} returned a non-awaitable value; "
                "Handlers must be async"
            )
        return await _as_awaitable(result)


async def _as_awaitable(value: Awaitable[object]) -> object:
    return await value


def _is_async_callback(callback: HandlerCallback) -> bool:
    """True for async def, decorated async, and async-``__call__`` objects."""
    if inspect.iscoroutinefunction(callback):
        return True
    return inspect.iscoroutinefunction(type(callback).__call__)


# Handler parameter names that receive the event, by event class.
_EVENT_ALIASES: tuple[tuple[type[Event], tuple[str, ...]], ...] = (
    (MessageEvent, ("message",)),
    (ActionEvent, ("action",)),
    (CommandEvent, ("command",)),
    (AddedToSpaceEvent, ("added_to_space",)),
    (RemovedFromSpaceEvent, ("removed_from_space",)),
    (SystemCommandEvent, ("system_command",)),
    (WidgetUpdatedEvent, ("widget",)),
    (AppHomeEvent, ("app_home",)),
    (FormSubmitEvent, ("form",)),
    (UnknownEvent, ("unknown",)),
    (ErrorEvent, ("error", "error_event")),
)
_DIALOG_ALIASES: dict[str, str] = {
    DialogEventType.SUBMIT_DIALOG.value: "dialog_submit",
    DialogEventType.CANCEL_DIALOG.value: "dialog_cancel",
}


def _event_aliases(event: Event) -> frozenset[str]:
    aliases = {"event"}
    for event_type, names in _EVENT_ALIASES:
        if isinstance(event, event_type):
            aliases.update(names)
            break
    if isinstance(event, ActionEvent) and event.dialog is not None:
        dialog_alias = _DIALOG_ALIASES.get(str(event.dialog.type))
        if dialog_alias is not None:
            aliases.add(dialog_alias)
    return frozenset(aliases)


def _event_types(annotation: object) -> tuple[type[Event], ...]:
    if annotation is inspect.Signature.empty or annotation is Any:
        return ()
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        event_types: list[type[Event]] = []
        for argument in get_args(annotation):
            event_types.extend(_event_types(argument))
        return tuple(dict.fromkeys(event_types))
    if isinstance(annotation, type) and issubclass(annotation, Event):
        return (annotation,)
    return ()


@cache
def build_handler_plan(callback: HandlerCallback) -> HandlerPlan:
    """Inspect and cache a handler signature."""
    if not _is_async_callback(callback):
        raise InvalidHandlerError(
            f"Handler {handler_qualified_name(callback)!r} must be asynchronous. "
            "Declare it using 'async def'."
        )
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError) as error:
        raise InvalidHandlerError(f"Cannot inspect handler {callback!r}") from error

    try:
        hints = get_type_hints(callback)
    except (NameError, TypeError):
        hints = {}

    parameters: list[ParameterPlan] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise InvalidHandlerError(
                f"Handler {callback!r} parameter {parameter.name!r} uses unsupported "
                f"kind {parameter.kind.description}"
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        event_types = _event_types(annotation)
        event_alias = (
            not event_types
            and annotation in (inspect.Signature.empty, Any)
            and parameter.name
            in {
                "event",
                "message",
                "action",
                "command",
                "added_to_space",
                "removed_from_space",
                "system_command",
                "widget",
                "app_home",
                "form",
                "dialog_submit",
                "dialog_cancel",
                "unknown",
                "error",
                "error_event",
            }
        )
        parameters.append(
            ParameterPlan(
                name=parameter.name,
                event_types=event_types,
                event_alias=event_alias,
                has_default=parameter.default is not inspect.Signature.empty,
            )
        )
    return HandlerPlan(callback=callback, parameters=tuple(parameters))


__all__ = [
    "HandlerCallback",
    "HandlerPlan",
    "ParameterPlan",
    "build_handler_plan",
    "handler_qualified_name",
]
