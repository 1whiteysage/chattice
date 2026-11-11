# Pre-1.0 stability

Current package: Chattice 0.4.0.

## Stable public surface

The documented stable API is the compatibility baseline. Stable package `__all__`
exports and the public members listed in the [public API inventory](public-api.md)
may grow additively within a minor release line. Existing names, call signatures,
and documented semantics remain compatible in patch releases. Bug and security fixes may make invalid
or unsafe behavior fail earlier.

Patch releases preserve this surface. Before 1.0, an incompatible change
requires a minor-version bump and upgrade notes.

## Experimental surface

Everything under `chattice.experimental` is outside the stable contract.
The `chattice.experimental` namespace is an optional integration layer:
stable core primitives remain the supported surface, while anything in the
experimental namespace (for example the optional AI integration
`chattice.experimental.ai`) can change or disappear before 1.0.

Google Developer Preview features are also explicitly opted into, for example:

```python
from chattice import Dispatcher
from chattice.capabilities import PreviewFeature
from chattice.client import Bot

bot = Bot(credentials=credentials, preview_features={PreviewFeature.MESSAGE_STREAMING})
dispatcher = Dispatcher(bot=bot)
```

The stable preview gate does not make Google's preview feature stable.

## Raw and advanced surface

`bot.raw.app()` / `bot.raw.user()` expose the official async Google Chat client
for the chosen identity. Event `.raw` preserves the incoming Google payload,
and `RawWidget` provides a card-widget escape hatch. These are intentional,
supported extension points for features the curated facade does not yet wrap.
Their fields and methods follow Google's SDK, discovery schema, and wire
payloads, not Chattice's stable-facade promise.

Prefer the typed facade for common operations; use raw access at a narrow
application boundary and test the exact Google schema you depend on.

## Version and deprecation policy

The latest pre-1.0 minor line receives normal and security fixes. Patch releases
remain backward compatible. After 1.0, deprecated symbols remain available for
at least one minor release cycle.

Next: [5-minute Quickstart](getting-started/quickstart.md).

## Removed legacy surface (0.3.0)

The pre-0.2 outbound surface and the `OutboundCapability` /
`OutboundCapabilities` facade were removed in 0.3.0. Every operation moved
through the same registry-to-executor path as the resource clients; the old
wrappers delegated one-way to that path, so behavior is unchanged. Migrate:

| Removed                            | Replacement                                       |
| ---------------------------------- | ------------------------------------------------- |
| `Bot.send_message` / `.update_message` | `bot.app.messages.create` / `.update` / `bot.user.messages` (attachments stay USER end to end) |
| `Bot.get_message` / `.delete_message`  | `bot.app.messages.get` / `.delete`                |
| `Bot.get_space` / `.list_spaces`       | `bot.app.spaces.get` / `.list`                    |
| `Bot.add_member` / `.get_member` / `.list_members` / `.remove_member` | `bot.app.memberships.create` / `.get` / `.list` / `.delete` |
| `Bot.get_attachment`               | `bot.app.attachments.get_metadata` / `bot.app.attachments.download` / `bot.user.attachments.download` |
| `Bot.upload_attachment`            | `bot.user.attachments.upload`                     |
| `Bot.download_attachment`          | `bot.app.attachments.download` / `bot.user.attachments.download` |
| `Bot.raw_client`                   | `await bot.raw.app()` / `await bot.raw.user()`    |
| `Bot.capabilities` / `OutboundCapabilities` | preflight runs inside every resource call |
| `OutboundCapability`               | `chattice.capabilities.Operation`                 |
