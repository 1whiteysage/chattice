"""Identity-bound resource clients over the curated outbound facade."""

from chattice.client.resources.attachments import Attachments
from chattice.client.resources.availability import Availability
from chattice.client.resources.base import ResourceClient
from chattice.client.resources.custom_emojis import CustomEmojis
from chattice.client.resources.memberships import Memberships
from chattice.client.resources.message_pins import MessagePins
from chattice.client.resources.messages import Messages
from chattice.client.resources.reactions import Reactions
from chattice.client.resources.sections import Sections
from chattice.client.resources.spaces import Spaces
from chattice.client.resources.users import Users

__all__ = [
    "Attachments",
    "Availability",
    "CustomEmojis",
    "Memberships",
    "MessagePins",
    "Messages",
    "Reactions",
    "ResourceClient",
    "Sections",
    "Spaces",
    "Users",
]
