# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Attachment resource client: media operations with explicit identity.

Upload is USER-only (media.upload); download accepts APP or USER — the
caller chooses the identity namespace; metadata get is APP-only
(spaces.messages.attachments.get). All three run through the
OperationExecutor; the media REST calls sit inside the executor closure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from google.apps.chat_v1 import ChatServiceAsyncClient

from chattice.auth import AuthMode
from chattice.capabilities.operations import Operation
from chattice.client._names import _canonical_space
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef
from chattice.media import AttachmentRef, InputFile, UploadedAttachment

__all__ = ["Attachments"]


class Attachments(ResourceClient):
    """Curated attachment surface bound to one identity (ADR-012)."""

    async def upload(
        self,
        space: SpaceRef | str,
        file: InputFile,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> UploadedAttachment:
        """Upload a local file as a Chat attachment (USER auth only).

        All deterministic constraints (file kind, size, filename) are
        validated before any network call; the synchronous REST client
        runs off the event loop. A USER-authenticated call acts on
        behalf of that user — this Google auth semantic is never hidden.
        """
        effective = _effective_config(config, timeout)
        parent = _canonical_space(space)
        file.validate()
        from chattice.media._rest import upload_media

        async def _call(client: object, cfg: RequestConfig) -> dict[str, Any]:
            del client  # REST media: resolved USER credentials do the work
            data = await asyncio.to_thread(file.read)
            return await asyncio.to_thread(
                upload_media,
                await self._bot._resolve_user_credentials_async(),
                parent,
                file.filename,
                file.content_type,
                data,
                cfg.timeout,
            )

        response = cast(
            dict[str, Any],
            await self._executor.execute(
                Operation.MEDIA_UPLOAD,
                identity=self._identity,
                call=_call,
                config=effective,
            ),
        )
        data_ref = response.get("attachmentDataRef")
        if not isinstance(data_ref, dict):
            raise ChatAPIError(
                f"media.upload returned no attachmentDataRef; got {response!r}"
            )
        return UploadedAttachment(
            space=parent,
            filename=file.filename,
            attachment_data_ref=dict(data_ref),
            raw=dict(response),
        )

    async def download(
        self,
        attachment: AttachmentRef | str,
        *,
        destination: str | Path | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> bytes | Path:
        """Download Chat-uploaded attachment data with THIS identity.

        A string is treated as an ``attachmentDataRef.resourceName``.
        Drive-backed references are rejected locally with an actionable
        message: media.download serves Chat-uploaded content only.
        """
        if isinstance(attachment, AttachmentRef):
            if attachment.is_drive:
                raise ChatAPIError(
                    "Drive-backed attachments cannot be downloaded through "
                    "Chat media.download; use the Google Drive API with "
                    "this attachment's drive_file_id."
                )
            resource_name = attachment.resource_name
        else:
            resource_name = attachment
        if not resource_name:
            raise ChatAPIError(
                "attachment has no attachmentDataRef.resourceName; nothing to download"
            )
        effective = _effective_config(config, timeout)
        from chattice.media._rest import download_media

        async def _call(client: object, cfg: RequestConfig) -> bytes:
            del client  # REST media: resolved identity credentials
            credentials = (
                await self._bot._resolve_user_credentials_async()
                if self._identity is AuthMode.USER
                else await self._bot._resolve_credentials_async()
            )
            return await asyncio.to_thread(
                download_media, credentials, resource_name, cfg.timeout
            )

        data = cast(
            bytes,
            await self._executor.execute(
                Operation.MEDIA_DOWNLOAD,
                identity=self._identity,
                call=_call,
                config=effective,
            ),
        )
        if destination is None:
            return data
        path = Path(destination)
        await asyncio.to_thread(path.write_bytes, data)
        return path

    async def get_metadata(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AttachmentRef:
        """Fetch attachment metadata (APP auth + chat.bot only)."""
        effective = _effective_config(config, timeout)
        proto = await self._rpc(Operation.ATTACHMENT_METADATA_GET, effective)(
            ChatServiceAsyncClient.get_attachment, name=name
        )
        return AttachmentRef.from_proto(proto)
