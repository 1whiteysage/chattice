# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Message resource client: explicit-identity message operations (ADR-012).

``create``/``update`` carry the full curated surface (validation,
assets, attachments, thread options, citations).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, TypeVar

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.attachment import Attachment
from google.apps.chat_v1.types.citation import Citation
from google.apps.chat_v1.types.cited_source import CitedSource
from google.apps.chat_v1.types.elements import Elements
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax
from google.apps.chat_v1.types.message import (
    CardWithId,
    CreateMessageNotificationOptions,
    CreateMessageRequest,
    ListMessagesRequest,
    Message,
    ReplaceMessageCardsRequest,
    SearchMessageResult,
    SearchMessagesRequest,
)
from google.apps.chat_v1.types.user import User as ProtoUser
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported, PreviewFeature
from chattice.capabilities.operations import Operation
from chattice.cards import AccessoryWidget, Card
from chattice.cards._assets import resolve_card_assets, validate_card_assets
from chattice.cards.addon import bind_addon_actions_proto
from chattice.client._names import (
    _canonical_message,
    _canonical_space,
    _canonical_user,
)
from chattice.client._proto_helpers import _attachment_data_ref_proto
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef, ThreadRef, UserRef
from chattice.media import InputFile, UploadedAttachment

__all__ = ["Messages"]

_ProtoT = TypeVar("_ProtoT")

# Google: a citation id is alphanumeric (underscores allowed, as in the
# official examples) and shorter than 63 characters.
_CITATION_ID = re.compile(r"[A-Za-z0-9_]{1,62}")


def _validate_sources(
    markup_syntax: MarkupSyntax | None,
    citations: Sequence[Citation] | None,
    cited_sources: Sequence[CitedSource] | None,
) -> None:
    """Deterministic local checks for citations and footer sources."""
    if not citations and not cited_sources:
        return
    # ``None`` defers to the app-level default markup syntax configured
    # in the Google Cloud console, so only an explicit non-Markdown
    # syntax is a local error.
    if (
        markup_syntax is not None
        and markup_syntax != MarkupSyntax.MARKUP_SYNTAX_MARKDOWN
    ):
        raise ChatAPIError(
            "citations and cited_sources require "
            "markup_syntax=MarkupSyntax.MARKUP_SYNTAX_MARKDOWN."
        )
    seen: set[str] = set()
    for citation in citations or ():
        if _CITATION_ID.fullmatch(citation.id) is None:
            raise ChatAPIError(
                "citation id must contain only ASCII letters, numbers, and "
                f"underscores and be shorter than 63 characters; got {citation.id!r}"
            )
        if citation.id in seen:
            raise ChatAPIError(f"duplicate citation id {citation.id!r}")
        seen.add(citation.id)


def _check_attachment_combination(
    identity: AuthMode,
    private_to: UserRef | str | None,
    accessory_widgets: Sequence[AccessoryWidget] | None,
) -> None:
    if private_to is not None:
        raise ChatAPIError(
            "private_to cannot be combined with attachments "
            "(Google: private messages omit attachments)."
        )
    if accessory_widgets:
        raise ChatAPIError(
            "attachments cannot be combined with accessory widgets "
            "(Google restriction)."
        )
    if identity is not AuthMode.USER:
        raise CapabilityNotSupported(
            "attachment messages are USER-authenticated; call "
            "bot.user.messages.create(...) to send attachments."
        )


def _check_notify(
    notify: str | None, actual_mode: AuthMode | None, *, has_attachments: bool
) -> None:
    if notify is None:
        return
    if notify not in ("force", "silent"):
        raise ChatAPIError(f"notify must be 'force', 'silent', or None; got {notify!r}")
    if has_attachments:
        raise CapabilityNotSupported(
            "notify (createMessageNotificationOptions) requires app "
            "authentication and cannot be combined with attachments: "
            "attachment messages are USER-authenticated."
        )
    if actual_mode is not AuthMode.APP:
        raise CapabilityNotSupported(
            "createMessageNotificationOptions requires app authentication (chat.bot)."
        )


def _private_viewer(
    private_to: UserRef | str | None,
    actual_mode: AuthMode | None,
    accessory_widgets: Sequence[AccessoryWidget] | None,
) -> str | None:
    """Canonical ``users/...`` name of the private message viewer, if any."""
    if private_to is None:
        return None
    viewer = _canonical_user(private_to)
    if actual_mode is not AuthMode.APP:
        raise CapabilityNotSupported(
            "Private messages (privateMessageViewer) require app "
            "authentication (chat.bot)."
        )
    if accessory_widgets:
        raise ChatAPIError(
            "private_to cannot be combined with accessory widgets "
            "(Google: privateMessageViewer is not compatible with "
            "accessory widgets)."
        )
    return viewer


def _check_attachment_items(
    attachments: Sequence[InputFile | UploadedAttachment], parent: str
) -> None:
    for item in attachments:
        if not isinstance(item, UploadedAttachment):
            item.validate()
        elif _canonical_space(item.space) != parent:
            raise ChatAPIError(
                "UploadedAttachment is scoped to space "
                f"{item.space!r}; cannot send it in {parent!r}"
            )


def _check_create_mode(
    actual_mode: AuthMode | None,
    accessory_widgets: Sequence[AccessoryWidget] | None,
) -> None:
    if accessory_widgets and actual_mode is not AuthMode.APP:
        raise CapabilityNotSupported(
            "Accessory widgets require app authentication (chat.bot)."
        )
    if actual_mode is AuthMode.NONE:
        raise CapabilityNotSupported(
            "MESSAGE_CREATE is not supported in this configuration. "
            "Creating messages requires app or user authentication and "
            "an admissible OAuth scope."
        )


def _text_message(
    text: str | None,
    markup_syntax: MarkupSyntax | None,
    citations: Sequence[Citation] | None,
    cited_sources: Sequence[CitedSource] | None,
) -> Message:
    """The text part of a new message: text, markup, and its sources."""
    message = Message(text=text or "")
    if markup_syntax is not None:
        message.markup_syntax = markup_syntax
    if citations or cited_sources:
        message.elements = Elements(
            citations=list(citations or ()),
            cited_sources=list(cited_sources or ()),
        )
    return message


def _apply_thread(
    message: Message, thread: ThreadRef | None, reply_option: object
) -> Any:
    """Set the thread on ``message`` and return the reply option to send.

    Without a thread the message starts a new one, so a reply option has
    nothing to apply to and is not sent.
    """
    has_thread = False
    if thread is not None and thread.name is not None:
        message.thread.name = thread.name
        has_thread = True
    if thread is not None and thread.thread_key is not None:
        message.thread.thread_key = thread.thread_key
        has_thread = True
    if reply_option is not None and has_thread:
        return reply_option
    return CreateMessageRequest.MessageReplyOption.MESSAGE_REPLY_OPTION_UNSPECIFIED


def _notification_options(notify: str) -> CreateMessageNotificationOptions:
    notification = CreateMessageNotificationOptions.NotificationType
    options = CreateMessageNotificationOptions()
    options.notification_type = notification(
        notification.NOTIFICATION_TYPE_FORCE_NOTIFY
        if notify == "force"
        else notification.NOTIFICATION_TYPE_SILENT
    )
    return options


class Messages(ResourceClient):
    """Curated message surface bound to one identity (ADR-012)."""

    async def get(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Message:
        """Get one message by canonical ``spaces/.../messages/...`` name."""
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.MESSAGES_GET, effective)(
            ChatServiceAsyncClient.get_message, name=name
        )

    async def create(
        self,
        space: SpaceRef | str,
        text: str | None = None,
        *,
        markup_syntax: MarkupSyntax | None = None,
        thread: ThreadRef | None = None,
        reply_option: object = None,
        request_id: str | None = None,
        message_id: str | None = None,
        timeout: float | None = None,
        accessory_widgets: Sequence[AccessoryWidget] | None = None,
        card: Card | None = None,
        notify: str | None = None,
        private_to: UserRef | str | None = None,
        attachments: Sequence[InputFile | UploadedAttachment] | None = None,
        citations: Sequence[Citation] | None = None,
        cited_sources: Sequence[CitedSource] | None = None,
    ) -> Message:
        """Create a message with THIS identity (APP or USER — caller's choice).

        All deterministic constraints are validated before any client
        work; attachment sends require the USER identity and run the
        whole send (upload and create) on the USER client.

        ``citations`` are inline sources referenced from the text with
        ``<chat-citation data-id="{id}">...</chat-citation>`` tags;
        ``cited_sources`` render as footer links. Both need Markdown
        markup: pass ``markup_syntax=MARKUP_SYNTAX_MARKDOWN`` unless
        Markdown is the app-level default.

        A card sent with the USER identity requires the Chat app to be
        a member of the space (Google restriction).
        """
        validate_card_assets(card, self._bot._asset_publisher)
        _validate_sources(markup_syntax, citations, cited_sources)
        attachment_list = tuple(attachments or ())
        has_attachments = bool(attachment_list)
        # The EFFECTIVE identity guards:
        # USER for attachment sends, the bot's actual primary identity
        # otherwise (never the resource's declared identity alone).
        actual_mode = (
            AuthMode.USER if has_attachments else await self._bot._auth_mode_async()
        )
        if has_attachments:
            # Combination guards first: identity-independent, must reject
            # before any identity resolution.
            _check_attachment_combination(self._identity, private_to, accessory_widgets)
        _check_notify(notify, actual_mode, has_attachments=has_attachments)
        viewer = _private_viewer(private_to, actual_mode, accessory_widgets)
        parent = _canonical_space(space)
        _check_attachment_items(attachment_list, parent)
        _check_create_mode(actual_mode, accessory_widgets)
        if has_attachments:
            # Fail locally BEFORE any media I/O (upload) when the USER
            # identity or its scopes are absent — media work must never
            # run for a send that will be rejected.
            await self._require_user_attachment_auth(attachment_list)

        message = _text_message(text, markup_syntax, citations, cited_sources)
        if card is not None:
            message.cards_v2.append(await self._card_with_id(card, "card"))
        for entry in await self._attach(parent, attachment_list, timeout):
            message.attachment.append(entry)
        if viewer is not None:
            message.private_message_viewer = ProtoUser(name=viewer)
        for widget in accessory_widgets or ():
            message.accessory_widgets.append(self._bind_actions(widget.to_proto()))
        request = CreateMessageRequest(
            parent=parent,
            message=message,
            request_id=request_id,
            message_id=message_id,
            message_reply_option=_apply_thread(message, thread, reply_option),
        )
        if notify is not None:
            request.create_message_notification_options = _notification_options(notify)
        effective = _effective_config(None, timeout)
        return await self._rpc(Operation.MESSAGES_CREATE, effective)(
            ChatServiceAsyncClient.create_message, request=request
        )

    def _bind_actions(self, proto: _ProtoT) -> _ProtoT:
        """Point card actions at the add-on endpoint, when one is configured."""
        action_url = self._bot._addon_action_url
        if action_url is None:
            return proto
        return bind_addon_actions_proto(proto, action_url)

    async def _card_with_id(self, card: Card, card_id: str) -> CardWithId:
        """Publish the card's local images and build its wire entry."""
        resolved = await resolve_card_assets(card, self._bot._asset_publisher)
        return CardWithId(card_id=card_id, card=self._bind_actions(resolved.to_proto()))

    async def _require_user_attachment_auth(
        self, attachments: Sequence[InputFile | UploadedAttachment]
    ) -> None:
        """Attachment sends run entirely on the USER identity."""
        user_credentials = await self._bot._resolve_user_credentials_async()
        if user_credentials is None:
            raise CapabilityNotSupported(
                "Sending message attachments requires USER authentication "
                "for both media.upload and messages.create. Configure "
                "user_credentials_provider=... — UserCredentialsProvider, "
                "or DelegatedUserCredentialsProvider for domain-wide "
                "delegation."
            )
        if self._bot._classify(user_credentials) is AuthMode.APP:
            raise CapabilityNotSupported(
                "the user credentials provider returned service-account "
                "credentials; Google treats attachment sends as "
                "USER-authenticated calls — use "
                "DelegatedUserCredentialsProvider (with_subject) to "
                "impersonate a Workspace user through domain-wide delegation."
            )
        await self._preflight(Operation.MESSAGES_CREATE)
        if any(isinstance(item, InputFile) for item in attachments):
            await self._preflight(Operation.MEDIA_UPLOAD)

    async def _attach(
        self,
        parent: str,
        attachments: Sequence[InputFile | UploadedAttachment],
        timeout: float | None,
    ) -> list[Attachment]:
        """Upload the files that are not uploaded yet; keep the given order."""
        attached: list[Attachment] = []
        for item in attachments:
            uploaded = (
                item
                if isinstance(item, UploadedAttachment)
                else await self._bot.user.attachments.upload(
                    parent, item, timeout=timeout
                )
            )
            attached.append(
                Attachment(
                    attachment_data_ref=_attachment_data_ref_proto(
                        uploaded.attachment_data_ref
                    )
                )
            )
        return attached

    async def update(
        self,
        name: str,
        text: str | None = None,
        *,
        card: Card | None = None,
        markup_syntax: MarkupSyntax | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Message:
        """Update text and/or card of one message with THIS identity.

        ``markup_syntax`` selects how Google interprets the new ``text``
        and is only valid together with it; it overrides the app-level
        default for this request.
        """
        if text is None and card is None:
            raise ChatAPIError("update_message requires text or card")
        if markup_syntax is not None and text is None:
            raise ChatAPIError("markup_syntax requires text")
        actual_mode = await self._bot._auth_mode_async()
        if actual_mode is AuthMode.NONE:
            raise CapabilityNotSupported(
                "MESSAGE_UPDATE is not supported in this configuration. "
                "Updating messages requires app or user authentication and "
                "an admissible OAuth scope."
            )
        validate_card_assets(card, self._bot._asset_publisher)
        message = Message(name=name)
        update_paths: list[str] = []
        if text is not None:
            message.text = text
            update_paths.append("text")
            if markup_syntax is not None:
                # Google: markup_syntax travels on the resource; the
                # update mask names only ``text``.
                message.markup_syntax = markup_syntax
        if card is not None:
            message.cards_v2.append(await self._card_with_id(card, "card"))
            update_paths.append("cards_v2")
        update_mask = field_mask_pb2.FieldMask(paths=update_paths)
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.MESSAGES_UPDATE, effective)(
            ChatServiceAsyncClient.update_message,
            message=message,
            update_mask=update_mask,
        )

    async def replace_cards(
        self,
        name: str,
        cards: Sequence[Card],
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Replace the app-owned cards of one message (APP-only).

        Works without a user interaction and targets cards this app
        attached, including cards on a message created with the USER
        identity. An empty ``cards`` removes them, and Google does not
        allow adding cards back to that message afterwards.
        """
        target = _canonical_message(name, parameter="name")
        for card in cards:
            validate_card_assets(card, self._bot._asset_publisher)
        request = ReplaceMessageCardsRequest(name=target)
        for index, card in enumerate(cards):
            card_id = "card" if index == 0 else f"card-{index + 1}"
            request.cards_v2.append(await self._card_with_id(card, card_id))
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.MESSAGES_REPLACE_CARDS, effective)(
            ChatServiceAsyncClient.replace_message_cards, request=request
        )

    async def list(
        self,
        *,
        parent: str,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Message]:
        """List messages of one space, one page at a time."""
        effective = _effective_config(config, timeout)
        request = ListMessagesRequest(parent=parent)
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.MESSAGES_LIST, effective)(
                ChatServiceAsyncClient.list_messages, request=request
            )

        return Pager(fetch=fetch)

    async def search(
        self,
        query: str,
        *,
        order_by: str | None = None,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[SearchMessageResult]:
        """Search messages across every space the user can access (USER-only).

        ``query`` is Google's search filter (keywords plus field
        filters such as ``create_time`` or ``sender.name``). Google does
        not return private messages, messages posted by Chat apps,
        messages in app DMs, or messages in muted spaces. Ordering by
        ``relevance`` is a Developer Preview
        (``PreviewFeature.RELEVANCE_SEARCH_ORDERING``).
        """
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            raise ChatAPIError("search query must be a non-empty string")
        if order_by is not None and "relevance" in order_by:
            self._bot.preview_capabilities.require(
                PreviewFeature.RELEVANCE_SEARCH_ORDERING,
                what="Ordering message search by relevance",
            )
        effective = _effective_config(config, timeout)
        # Google accepts only the all-spaces wildcard as the parent.
        request = SearchMessagesRequest(parent="spaces/-", filter=text)
        if order_by is not None:
            request.order_by = order_by
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.MESSAGES_SEARCH, effective)(
                ChatServiceAsyncClient.search_messages, request=request
            )

        return Pager(fetch=fetch)

    async def delete(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Delete one message by canonical name."""
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.MESSAGES_DELETE, effective)(
            ChatServiceAsyncClient.delete_message, name=name
        )
