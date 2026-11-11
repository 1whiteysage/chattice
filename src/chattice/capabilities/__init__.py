"""Capability model: response channel, outbound operations, preview features."""

from .matrix import (
    DEVELOPER_PREVIEW_FEATURES,
    PREVIEW_APP_COMMAND_TYPES,
    CapabilityNotSupported,
    PreviewCapabilities,
    PreviewFeature,
    ResponseCapabilities,
    ResponseCapability,
    can_open_dialog,
)
from .operations import AuthPath, ExecutionVariant, Operation, OperationSpec, scopes
from .registry import REGISTRY, OperationRegistry

__all__ = [
    "DEVELOPER_PREVIEW_FEATURES",
    "PREVIEW_APP_COMMAND_TYPES",
    "REGISTRY",
    "AuthPath",
    "CapabilityNotSupported",
    "ExecutionVariant",
    "Operation",
    "OperationRegistry",
    "OperationSpec",
    "PreviewCapabilities",
    "PreviewFeature",
    "ResponseCapabilities",
    "ResponseCapability",
    "can_open_dialog",
    "scopes",
]
