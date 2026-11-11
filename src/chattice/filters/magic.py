"""A small, safe expression-tree filtering DSL."""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeAlias, cast

from chattice.events import Event

from .base import BaseFilter, FilterValue


class _Missing:
    __slots__ = ()


MISSING: Final = _Missing()
PathStep: TypeAlias = tuple[Literal["attr", "item"], object]


class MagicExpression(BaseFilter):
    """Base class for immutable boolean expression nodes."""

    async def __call__(
        self, event: Event, context: Mapping[str, object]
    ) -> FilterValue:
        del context
        return self.evaluate(event)

    def evaluate(self, event: Event) -> bool:
        """Evaluate this expression against an event."""
        raise NotImplementedError

    def __and__(self, other: MagicExpression) -> MagicExpression:
        return _BooleanExpression("and", self, other)

    def __or__(self, other: MagicExpression) -> MagicExpression:
        return _BooleanExpression("or", self, other)

    def __invert__(self) -> MagicExpression:
        return _NotExpression(self)

    def __bool__(self) -> bool:
        raise TypeError("Magic-filter expressions cannot be used as Python booleans")


@dataclass(frozen=True, slots=True)
class MagicField(MagicExpression):
    """A safely traversed event attribute/item path."""

    path: tuple[PathStep, ...] = ()

    def __getattr__(self, name: str) -> MagicField:
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicField((*self.path, ("attr", name)))

    def __getitem__(self, key: object) -> MagicField:
        return MagicField((*self.path, ("item", key)))

    def __eq__(self, other: object) -> MagicExpression:  # type: ignore[override]
        return _ComparisonExpression("eq", self, other)

    def __ne__(self, other: object) -> MagicExpression:  # type: ignore[override]
        return _ComparisonExpression("ne", self, other)

    def __lt__(self, other: object) -> MagicExpression:
        return _ComparisonExpression("lt", self, other)

    def __le__(self, other: object) -> MagicExpression:
        return _ComparisonExpression("le", self, other)

    def __gt__(self, other: object) -> MagicExpression:
        return _ComparisonExpression("gt", self, other)

    def __ge__(self, other: object) -> MagicExpression:
        return _ComparisonExpression("ge", self, other)

    def contains(self, value: object) -> MagicExpression:
        """Match when the resolved field contains ``value``."""
        return _MethodExpression("contains", self, value)

    def startswith(self, value: object) -> MagicExpression:
        """Match when the resolved field starts with ``value``."""
        return _MethodExpression("startswith", self, value)

    def endswith(self, value: object) -> MagicExpression:
        """Match when the resolved field ends with ``value``."""
        return _MethodExpression("endswith", self, value)

    def in_(self, value: object) -> MagicExpression:
        """Match when the resolved field is a member of ``value``."""
        return _MethodExpression("in", self, value)

    def is_(self, value: object) -> MagicExpression:
        """Match by object identity."""
        return _MethodExpression("is", self, value)

    def exists(self) -> MagicExpression:
        """Match when the complete path can be resolved."""
        return _MethodExpression("exists", self, None)

    def regexp(self, pattern: str | re.Pattern[str], flags: int = 0) -> MagicExpression:
        """Match a string field with a Python regular expression.

        Uses ``re.match`` semantics — the pattern must match FROM THE
        START of the value. Accepts a pattern string (compiled once, at
        filter construction) or a pre-compiled ``re.Pattern``. Invalid
        patterns raise ``ValueError`` at construction, never at
        evaluation time. ``flags`` cannot be combined with a compiled
        pattern. Missing fields and non-string values never match.

        Do not wrap patterns in ``/.../`` — this is Python regex syntax.
        """
        if isinstance(pattern, re.Pattern):
            if flags:
                raise ValueError("flags cannot be combined with a compiled re.Pattern")
            # cast: re.Pattern[bytes] flows in from untyped callers even
            # though the annotation says str — reject it explicitly.
            if isinstance(cast(Any, pattern).pattern, bytes):
                raise ValueError(
                    "bytes regex patterns cannot match string fields; "
                    "compile a str pattern instead"
                )
            compiled: re.Pattern[str] = pattern
        else:
            try:
                compiled = re.compile(pattern, flags)
            except re.error as error:
                raise ValueError(f"invalid regex pattern: {error}") from error
        return _MethodExpression("regexp", self, compiled)

    def resolve(self, event: Event) -> object:
        """Resolve this path, returning a private missing sentinel on absence."""
        current: object = event
        for operation, value in self.path:
            try:
                if operation == "attr":
                    current = getattr(current, str(value))
                else:
                    current = current[value]  # type: ignore[index]
            except (AttributeError, KeyError, IndexError, TypeError):
                return MISSING
        return current

    def evaluate(self, event: Event) -> bool:
        value = self.resolve(event)
        return value is not MISSING and bool(value)


_COMPARISONS: dict[str, Callable[[Any, Any], object]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}
# (actual, expected) -> match; a wrong operand type means "no match".
_METHODS: dict[str, Callable[[Any, Any], object]] = {
    "contains": lambda actual, expected: expected in actual,
    "in": lambda actual, expected: actual in expected,
    "startswith": lambda actual, expected: actual.startswith(expected),
    "endswith": lambda actual, expected: actual.endswith(expected),
}


@dataclass(frozen=True, slots=True)
class _ComparisonExpression(MagicExpression):
    operation: Literal["eq", "ne", "lt", "le", "gt", "ge"]
    field: MagicField
    expected: object

    def evaluate(self, event: Event) -> bool:
        actual = self.field.resolve(event)
        if actual is MISSING:
            return False
        try:
            return bool(_COMPARISONS[self.operation](actual, self.expected))
        except TypeError:
            return False


@dataclass(frozen=True, slots=True)
class _MethodExpression(MagicExpression):
    operation: Literal[
        "contains", "startswith", "endswith", "in", "is", "exists", "regexp"
    ]
    field: MagicField
    expected: object

    def evaluate(self, event: Event) -> bool:
        actual = self.field.resolve(event)
        if self.operation == "exists":
            return actual is not MISSING
        if actual is MISSING:
            return False
        if self.operation == "is":
            return actual is self.expected
        if self.operation == "regexp":
            pattern = self.expected
            if not isinstance(actual, str) or not isinstance(pattern, re.Pattern):
                return False
            # re.match semantics: anchored at the start of the value.
            return pattern.match(actual) is not None
        try:
            return bool(_METHODS[self.operation](actual, self.expected))
        except (AttributeError, TypeError):
            return False


@dataclass(frozen=True, slots=True)
class _BooleanExpression(MagicExpression):
    operation: Literal["and", "or"]
    left: MagicExpression
    right: MagicExpression

    def evaluate(self, event: Event) -> bool:
        if self.operation == "and":
            return self.left.evaluate(event) and self.right.evaluate(event)
        return self.left.evaluate(event) or self.right.evaluate(event)


@dataclass(frozen=True, slots=True)
class _NotExpression(MagicExpression):
    expression: MagicExpression

    def evaluate(self, event: Event) -> bool:
        return not self.expression.evaluate(event)


F: Final = MagicField()

__all__ = ["F", "MagicExpression", "MagicField"]
