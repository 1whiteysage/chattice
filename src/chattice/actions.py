"""Typed action data: a deterministic codec above Google action parameters.

Google card buttons carry ``action.function`` (the discriminator — used by
``@router.action(...)``) plus a flat ``parameters`` mapping of string
key/value pairs. ``ActionData`` turns those strings into typed Python
fields WITHOUT an aiogram-style packed callback string and WITHOUT a
registry: the action function name IS the discriminator.

Codec (deterministic, no eval):
- str stays as-is; int/float/bool/Enum encode to canonical strings;
- None (optional) fields are OMITTED from parameters and restored from
  their default on decode;
- unknown parameters are ignored (forward compatibility with new Google
  fields);
- malformed values raise ActionDataDecodeError on explicit decode and
  make the filter NOT match (no partial state);
- documented system parameters (e.g. ``autocomplete_widget_query``) are
  never interpreted by the codec.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import math
import types
from collections.abc import Callable, Mapping
from typing import (
    Any,
    ClassVar,
    Self,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from chattice.events import ActionEvent, Event
from chattice.filters import FilterValue

_logger = logging.getLogger("chattice.actions")

__all__ = ["ActionData", "ActionDataDecodeError", "ActionDataFilter"]


class ActionDataDecodeError(ValueError):
    """Action parameters cannot be decoded into the typed model."""


def _encode_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("ActionData float fields must be finite")
        return repr(value)
    if isinstance(value, enum.Enum):
        return str(value.value)
    raise TypeError(
        f"ActionData field values must be str/int/float/bool/Enum, "
        f"got {type(value).__name__}"
    )


def _decode_int(raw: str) -> object:
    try:
        return int(raw)
    except ValueError as error:
        raise ActionDataDecodeError(f"cannot decode {raw!r} as int") from error


def _decode_float(raw: str) -> object:
    try:
        parsed = float(raw)
    except ValueError as error:
        raise ActionDataDecodeError(f"cannot decode {raw!r} as float") from error
    if not math.isfinite(parsed):
        raise ActionDataDecodeError(f"cannot decode {raw!r} as finite float")
    return parsed


def _decode_bool(raw: str) -> object:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ActionDataDecodeError(
        f"cannot decode {raw!r} as bool (expected 'true'/'false')"
    )


def _decode_enum(raw: str, target: type[enum.Enum]) -> object:
    # Canonical Enum codec — decode through the member VALUE so
    # numeric-valued enums (IntEnum, value=1) round-trip as well.
    for member in target:
        if str(member.value) == raw:
            return member
    raise ActionDataDecodeError(f"cannot decode {raw!r} as {target.__name__}")


_SCALAR_DECODERS: dict[type[object], Callable[[str], object]] = {
    str: str,
    int: _decode_int,
    float: _decode_float,
    bool: _decode_bool,
}


def _decode_value(raw: str, target: type[object]) -> object:
    decode = _SCALAR_DECODERS.get(target)
    if decode is not None:
        return decode(raw)
    if isinstance(target, type) and issubclass(target, enum.Enum):
        return _decode_enum(raw, target)
    raise ActionDataDecodeError(f"unsupported ActionData field type {target!r}")


def _unwrap_optional(target: type[object]) -> type[object]:
    """Optional[X] / X | None -> X; any other generic passes through."""
    origin = get_origin(target)
    if origin in (Union, types.UnionType):
        args = get_args(target)
        if len(args) == 2 and type(None) in args:
            # pick the NON-None member regardless of union order
            return cast(type[object], args[0] if args[1] is type(None) else args[1])
    return target


def _required_field_names(model: type[ActionData]) -> set[str]:
    required: set[str] = set()
    fields = dataclasses.fields(cast(Any, model))
    for field in fields:
        if (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        ):
            required.add(field.name)
    return required


class ActionData:
    """Base class for typed action parameter models (dataclass subclasses)."""

    function: ClassVar[str | None] = None

    def __init_subclass__(
        cls, *, function: str | None = None, **kwargs: object
    ) -> None:
        """Optionally bind the model to Google's action function discriminator."""
        super().__init_subclass__(**kwargs)
        if function is not None and not function.strip():
            raise ValueError("ActionData function must be non-empty")
        if function is not None:
            cls.function = function

    @classmethod
    def _fields(cls) -> dict[str, type[object]]:
        if not hasattr(cls, "__dataclass_fields__"):
            raise TypeError(f"{cls.__name__} must be a dataclass ActionData model")
        hints = get_type_hints(cls)
        return {
            field.name: hints[field.name]
            for field in dataclasses.fields(cast(Any, cls))
            if field.name in hints
        }

    def to_parameters(self) -> dict[str, str]:
        """Encode the typed fields into Google action parameters."""
        parameters: dict[str, str] = {}
        for name in self._fields():
            value = getattr(self, name)
            if value is None:
                continue  # optional field: omitted -> default on decode
            parameters[name] = _encode_value(value)
        return parameters

    @classmethod
    def from_parameters(cls, parameters: Mapping[str, str]) -> Self:
        """Decode Google action parameters into an instance.

        Unknown parameters are ignored (forward compatibility). Missing
        optional fields fall back to their dataclass defaults; missing
        REQUIRED fields raise ActionDataDecodeError.
        """
        fields = cls._fields()
        values: dict[str, object] = {}
        for name, target in fields.items():
            if name not in parameters:
                if name in _required_field_names(cls):
                    raise ActionDataDecodeError(
                        f"missing required parameter {name!r} for {cls.__name__}"
                    )
                continue  # optional: dataclass default applies
            values[name] = _decode_value(parameters[name], _unwrap_optional(target))
        return cls(**values)

    @classmethod
    def filter(cls) -> ActionDataFilter:
        """An async filter matching when parameters decode into this model.

        On a match the decoded instance is injected into the handler
        context under the name ``data``:

        @router.action("deploy.confirm", DeployAction.filter())
        async def confirm(event: ActionEvent, data: DeployAction): ...
        """
        return ActionDataFilter(cls)


class ActionDataFilter:
    """Decode-based filter: returns ``{"data": instance}`` or False."""

    def __init__(self, model: type[ActionData]) -> None:
        self.model = model

    async def __call__(
        self, event: Event, context: Mapping[str, object]
    ) -> FilterValue:
        if not isinstance(event, ActionEvent):
            return False
        parameters = {
            key: value
            for key, value in event.parameters.items()
            if isinstance(value, str)
        }
        try:
            instance = self.model.from_parameters(parameters)
        except ActionDataDecodeError as error:
            _logger.debug(
                "action data decode failed for %s: %s",
                self.model.__name__,
                error,
            )
            return False
        return {"data": instance}
