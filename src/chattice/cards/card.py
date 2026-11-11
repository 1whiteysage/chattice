"""Card, CardHeader, Section facade builders."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from google.apps.card_v1.types.card import Card as ProtoCard
from google.apps.card_v1.types.card import Widget as ProtoWidget
from google.protobuf import json_format  # type: ignore[import-untyped]

from chattice._json_snapshot import deep_snapshot

from .actions import Action, OpenLink
from .raw import RawWidget
from .serialization import from_dict, to_dict
from .validation import TextInputType, Validation
from .widgets import (
    Button,
    ButtonList,
    DateTimePicker,
    Divider,
    Image,
    SelectionInput,
    TextInput,
    TextParagraph,
)

__all__ = ["Card", "CardHeader", "Section"]

Widget = (
    TextParagraph
    | Divider
    | ButtonList
    | TextInput
    | SelectionInput
    | DateTimePicker
    | Image
    | RawWidget
)

_SUPPORTED_WIDGET_KEYS = frozenset(
    {
        "textParagraph",
        "divider",
        "buttonList",
        "textInput",
        "selectionInput",
        "dateTimePicker",
        "image",
    }
)


def _button_type_name(type_proto: Any) -> str | None:
    """preserve the documented Button.type string (skip unspecified)."""
    name = type_proto.name if type_proto is not None else ""
    if not name or name in ("TYPE_UNSPECIFIED", "BUTTON_TYPE_UNSPECIFIED"):
        return None
    return name


def _color_to_mapping(color_proto: Any) -> dict[str, float]:
    """google.type.Color -> the RGB mapping the facade accepts."""
    return {
        "red": color_proto.red,
        "green": color_proto.green,
        "blue": color_proto.blue,
        "alpha": color_proto.alpha,
    }


@dataclass(frozen=True, slots=True)
class CardHeader:
    """The card header."""

    title: str
    subtitle: str | None = None
    image_url: str | None = None

    def to_proto(self) -> dict[str, Any]:
        """Build the header as a proto-plus dict (the SDK class is not exported)."""
        data: dict[str, Any] = {"title": self.title}
        if self.subtitle is not None:
            data["subtitle"] = self.subtitle
        if self.image_url is not None:
            data["image_url"] = self.image_url
        return data


def _proto_dict(proto: Any) -> dict[str, Any]:
    """Convert a proto message into a plain dict for nested construction."""
    # preserving_proto_field_name: proto-plus constructors reject camelCase keys.
    data = json_format.MessageToDict(proto._pb, preserving_proto_field_name=True)
    return data  # type: ignore[no-any-return]


def _proto_json(proto: Any) -> dict[str, object]:
    """Convert a proto message to its documented camelCase JSON."""
    data = json_format.MessageToDict(proto._pb)
    return cast(dict[str, object], data)


@dataclass(frozen=True, slots=True)
class Section:
    """A card section: optional header plus a widget list."""

    header: str | None = None
    widgets: Sequence[Widget] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Canonicalize the container so round-trips compare equal
        # regardless of whether the caller passed a list or a tuple.
        object.__setattr__(self, "widgets", tuple(self.widgets))

    def to_proto_dict(self) -> dict[str, Any]:
        """Build the section as a proto-plus dict (oneof dispatch)."""
        data: dict[str, Any] = {}
        if self.header is not None:
            data["header"] = self.header
        data["widgets"] = [self._widget_dict(w) for w in self.widgets]
        return data

    @staticmethod
    def _widget_dict(widget: Widget) -> dict[str, Any]:
        if isinstance(widget, TextParagraph):
            return {"text_paragraph": _proto_dict(widget.to_proto())}
        if isinstance(widget, Divider):
            return {"divider": _proto_dict(widget.to_proto())}
        if isinstance(widget, ButtonList):
            return {"button_list": _proto_dict(widget.to_proto())}
        if isinstance(widget, TextInput):
            return {"text_input": _proto_dict(widget.to_proto())}
        if isinstance(widget, SelectionInput):
            return {"selection_input": _proto_dict(widget.to_proto())}
        if isinstance(widget, DateTimePicker):
            return {"date_time_picker": _proto_dict(widget.to_proto())}
        if isinstance(widget, Image):
            return {"image": _proto_dict(widget.to_proto())}
        if isinstance(widget, RawWidget):
            # Escape hatch: parse the documented camelCase payload into a
            # proto and emit the proto-plus dict (unknown fields are
            # ignored on the SDK path — documented in RawWidget).
            parsed = ProtoWidget()
            json_format.ParseDict(
                widget.to_dict(), parsed._pb, ignore_unknown_fields=True
            )
            return _proto_dict(parsed)
        raise TypeError(f"Unsupported widget type {type(widget).__name__}")

    @classmethod
    def from_proto(cls, proto: Any) -> Section:
        """Rebuild the facade from an SDK Section proto (oneof dispatch).

        Unsupported SDK widget kinds become ``RawWidget`` instead of raising
        or being silently dropped.
        """
        widgets = [
            _WIDGET_REBUILDERS.get(widget._pb.WhichOneof("data"), _raw_widget)(widget)
            for widget in proto.widgets
        ]
        return cls(header=proto.header or None, widgets=widgets)


def _text_paragraph_from(widget: Any) -> Widget:
    paragraph = widget.text_paragraph
    return TextParagraph(paragraph.text, max_lines=paragraph.max_lines or None)


def _divider_from(widget: Any) -> Widget:
    del widget
    return Divider()


def _button_from(button: Any) -> Button:
    click_kind = button.on_click._pb.WhichOneof("data")
    if click_kind == "open_link":
        return Button(
            button.text,
            open_link=button.on_click.open_link.url,
            disabled=button.disabled or False,
            alt_text=button.alt_text or None,
            type=_button_type_name(button.type),
        )
    if click_kind != "action":
        raise NotImplementedError(
            f"Button onClick kind {click_kind!r} is not rebuildable"
        )
    action = button.on_click.action
    # Full round-trip: every facade-supported Button field is preserved.
    return Button(
        button.text,
        action=action.function or None,
        parameters={p.key: p.value for p in action.parameters},
        interaction=action.interaction.name if action.interaction else None,
        disabled=button.disabled or False,
        alt_text=button.alt_text or None,
        required_widgets=tuple(action.required_widgets),
        persist_values=bool(action.persist_values),
        load_indicator=action.load_indicator.name == "SPINNER",
        type=_button_type_name(button.type),
        color=(
            _color_to_mapping(button.color) if button._pb.HasField("color") else None
        ),
    )


def _button_list_from(widget: Any) -> Widget:
    return ButtonList(
        buttons=[_button_from(button) for button in widget.button_list.buttons]
    )


def _text_input_from(widget: Any) -> Widget:
    text_input = widget.text_input
    rule = text_input.validation
    validation = None
    if rule.character_limit or rule.input_type:
        validation = Validation(
            character_limit=rule.character_limit or None,
            input_type=TextInputType(rule.input_type.name) if rule.input_type else None,
        )
    return TextInput(
        name=text_input.name,
        label=text_input.label,
        hint_text=text_input.hint_text or None,
        value=text_input.value or None,
        validation=validation,
    )


def _selection_input_from(widget: Any) -> Widget:
    selection = widget.selection_input
    # Preserve the dynamic-selection surface.
    source = None
    if selection._pb.HasField("external_data_source"):
        source = Action(
            function=selection.external_data_source.function or None,
            parameters={
                p.key: p.value for p in selection.external_data_source.parameters
            },
        )
    return SelectionInput(
        name=selection.name,
        label=selection.label,
        items=tuple({"text": i.text, "value": i.value} for i in selection.items),
        external_data_source=source,
        multi_select_max_selected_items=(
            selection.multi_select_max_selected_items or None
        ),
        multi_select_min_query_length=selection.multi_select_min_query_length or None,
    )


def _date_time_picker_from(widget: Any) -> Widget:
    picker = widget.date_time_picker
    return DateTimePicker(
        name=picker.name,
        label=picker.label,
        value_ms_epoch=picker.value_ms_epoch or None,
        timezone_offset_date=picker.timezone_offset_date or None,
    )


def _image_from(widget: Any) -> Widget:
    image = widget.image
    on_click: Action | OpenLink | None = None
    click_kind = image.on_click._pb.WhichOneof("data")
    if click_kind == "action":
        on_click = Action.from_proto(image.on_click.action)
    elif click_kind == "open_link":
        on_click = OpenLink.from_proto(image.on_click.open_link)
    return Image(
        image_url=image.image_url,
        alt_text=image.alt_text or None,
        on_click=on_click,
    )


def _raw_widget(widget: Any) -> Widget:
    """An SDK widget kind the facade does not model, kept losslessly."""
    return RawWidget(_proto_json(widget))


# Widget oneof case -> facade rebuilder; any other case stays a RawWidget.
_WIDGET_REBUILDERS: dict[str | None, Callable[[Any], Widget]] = {
    "text_paragraph": _text_paragraph_from,
    "divider": _divider_from,
    "button_list": _button_list_from,
    "text_input": _text_input_from,
    "selection_input": _selection_input_from,
    "date_time_picker": _date_time_picker_from,
    "image": _image_from,
}


@dataclass(frozen=True, slots=True)
class Card:
    """A Google Chat Cards v2 card."""

    header: CardHeader | None = None
    sections: Sequence[Section] = field(default_factory=tuple)
    name: str | None = None
    _raw: Mapping[str, object] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))

    def to_proto(self) -> ProtoCard:
        """Build the SDK Card proto."""
        if self._raw is not None:
            parsed = ProtoCard()
            json_format.ParseDict(
                dict(self._raw), parsed._pb, ignore_unknown_fields=True
            )
            return parsed
        kwargs: dict[str, Any] = {}
        if self.header is not None:
            kwargs["header"] = self.header.to_proto()
        if self.name is not None:
            kwargs["name"] = self.name
        card = ProtoCard(**kwargs)
        for section in self.sections:
            card.sections.append(section.to_proto_dict())  # type: ignore[arg-type]
        return card

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the documented camelCase Cards v2 JSON."""
        if self._raw is not None:
            return cast(
                dict[str, Any],
                deep_snapshot(self._raw, where="Card._raw"),
            )
        return to_dict(self.to_proto())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Card:
        """Rebuild from Cards v2 JSON while preserving unknown fields."""
        snapshot = cast(
            dict[str, object],
            deep_snapshot(data, where="Card.from_dict"),
        )
        parsed = from_dict(snapshot, ignore_unknown_fields=True)
        card = cls.from_proto(parsed)

        # The protobuf parser cannot retain fields absent from its schema.
        # Replace unsupported widget facades with their original documented
        # JSON while the card-level raw snapshot preserves every field.
        raw_sections = snapshot.get("sections")
        if isinstance(raw_sections, list):
            rebuilt_sections: list[Section] = []
            for index, section in enumerate(card.sections):
                raw_section = raw_sections[index] if index < len(raw_sections) else None
                widgets = list(section.widgets)
                if isinstance(raw_section, Mapping):
                    raw_widgets = raw_section.get("widgets")
                    if isinstance(raw_widgets, list):
                        for widget_index, raw_widget in enumerate(raw_widgets):
                            if not isinstance(raw_widget, Mapping):
                                continue
                            if _SUPPORTED_WIDGET_KEYS & set(raw_widget):
                                continue
                            replacement = RawWidget(raw_widget)
                            if widget_index < len(widgets):
                                widgets[widget_index] = replacement
                            else:
                                widgets.append(replacement)
                rebuilt_sections.append(Section(header=section.header, widgets=widgets))
            object.__setattr__(card, "sections", tuple(rebuilt_sections))
        object.__setattr__(card, "_raw", snapshot)
        return card

    @classmethod
    def from_proto(cls, proto: ProtoCard) -> Card:
        """Rebuild the facade from an SDK proto."""
        header = None
        if proto.header.title or proto.header.subtitle or proto.header.image_url:
            header = CardHeader(
                title=proto.header.title,
                subtitle=proto.header.subtitle or None,
                image_url=proto.header.image_url or None,
            )
        sections = [Section.from_proto(s) for s in proto.sections]
        return cls(header=header, sections=sections, name=proto.name or None)
