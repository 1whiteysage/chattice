# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Custom emoji resource client: USER-only organization emojis (ADR-012)."""

from __future__ import annotations

import re

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.reaction import (
    CreateCustomEmojiRequest,
    CustomEmoji,
    ListCustomEmojisRequest,
)

from chattice.capabilities.operations import Operation
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config

__all__ = ["CustomEmojis"]

# Google: starts and ends with a colon; lowercase alphanumerics separated
# by single hyphens or underscores.
_EMOJI_NAME = re.compile(r":[a-z0-9]+(?:[-_][a-z0-9]+)*:")
_EXTENSIONS = (".png", ".jpg", ".gif")
_MAX_PAYLOAD_BYTES = 256 * 1024


def _emoji_resource(name: str) -> str:
    """Canonicalize a custom emoji target.

    Accepts ``customEmojis/{id}``, ``customEmojis/:name:``, or the bare
    ``:name:`` alias Google documents for ``{customEmoji}``.
    """
    value = name.strip() if isinstance(name, str) else ""
    if _EMOJI_NAME.fullmatch(value):
        return f"customEmojis/{value}"
    if value.startswith("customEmojis/") and value.count("/") == 1 and value[13:]:
        return value
    raise ChatAPIError(
        "custom emoji must be a 'customEmojis/{id}' resource name or a "
        f"':emoji-name:' alias; got {name!r}"
    )


class CustomEmojis(ResourceClient):
    """Curated custom emoji surface bound to one identity (ADR-012).

    USER-only. Custom emojis exist only in Google Workspace
    organizations whose administrator turned them on.
    """

    async def create(
        self,
        emoji_name: str,
        image: bytes,
        *,
        filename: str,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> CustomEmoji:
        """Create ``:emoji_name:`` from a square PNG, JPG, or GIF image.

        Name, file extension, and the 256 KB size limit are checked
        locally; Google also requires a square image of 64 to 500 pixels.
        """
        if _EMOJI_NAME.fullmatch(emoji_name) is None:
            raise ChatAPIError(
                "emoji_name must start and end with a colon and contain "
                "lowercase letters and digits separated by single hyphens or "
                f"underscores, for example ':team-launch:'; got {emoji_name!r}"
            )
        if not filename.lower().endswith(_EXTENSIONS):
            raise ChatAPIError(
                f"filename must end with .png, .jpg, or .gif; got {filename!r}"
            )
        if not image:
            raise ChatAPIError("image must be non-empty bytes")
        if len(image) >= _MAX_PAYLOAD_BYTES:
            raise ChatAPIError(f"image must be under 256 KB; got {len(image)} bytes")
        request = CreateCustomEmojiRequest(
            custom_emoji=CustomEmoji(
                emoji_name=emoji_name,
                payload=CustomEmoji.CustomEmojiPayload(
                    file_content=image, filename=filename
                ),
            )
        )
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.CUSTOM_EMOJIS_CREATE, effective)(
            ChatServiceAsyncClient.create_custom_emoji, request=request
        )

    async def get(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> CustomEmoji:
        """Get one custom emoji by resource name or ``:name:`` alias."""
        target = _emoji_resource(name)
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.CUSTOM_EMOJIS_GET, effective)(
            ChatServiceAsyncClient.get_custom_emoji, name=target
        )

    async def list(
        self,
        *,
        created_by_me: bool | None = None,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[CustomEmoji]:
        """List custom emojis visible to the user, one page at a time.

        ``created_by_me`` narrows the list to emojis the user created
        (``True``) or did not create (``False``).
        """
        effective = _effective_config(config, timeout)
        request = ListCustomEmojisRequest()
        if created_by_me is not None:
            # The only filter Google accepts.
            creator = 'creator("users/me")'
            request.filter = creator if created_by_me else f"NOT {creator}"
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.CUSTOM_EMOJIS_LIST, effective)(
                ChatServiceAsyncClient.list_custom_emojis, request=request
            )

        return Pager(fetch=fetch)

    async def delete(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Delete one custom emoji by resource name or ``:name:`` alias."""
        target = _emoji_resource(name)
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.CUSTOM_EMOJIS_DELETE, effective)(
            ChatServiceAsyncClient.delete_custom_emoji, name=target
        )
