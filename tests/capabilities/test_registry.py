"""Tests for the operation registry and its invariants."""

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported
from chattice.capabilities.operations import (
    AuthPath,
    ExecutionVariant,
    Operation,
    OperationSpec,
    scopes,
)
from chattice.capabilities.registry import REGISTRY, OperationRegistry


def test_preflight_passes_when_any_scope_matches() -> None:
    assert REGISTRY.preflight(
        Operation.SPACES_LIST,
        identity=AuthMode.APP,
        scopes=scopes("chat.bot"),
    )


def test_preflight_fails_for_wrong_identity() -> None:
    assert not REGISTRY.preflight(
        Operation.SPACES_LIST,
        identity=AuthMode.USER,
        scopes=scopes("chat.messages"),
    )


def test_preflight_unknown_scopes_preserves_identity_baseline() -> None:
    assert REGISTRY.preflight(
        Operation.MESSAGES_CREATE, identity=AuthMode.APP, scopes=None
    )


def test_preflight_admin_variant_is_selected_explicitly() -> None:
    registry = OperationRegistry(
        [
            OperationSpec(
                operation=Operation.MEMBERSHIPS_UPDATE,
                google_method="spaces.members.patch",
                auth_paths=(
                    AuthPath(AuthMode.APP, scopes("chat.app.memberships")),
                    AuthPath(
                        AuthMode.USER,
                        scopes("chat.admin.memberships"),
                        variant=ExecutionVariant.ADMIN,
                        request_flag="use_admin_access",
                    ),
                ),
            )
        ]
    )
    assert not registry.preflight(
        Operation.MEMBERSHIPS_UPDATE,
        identity=AuthMode.USER,
        scopes=scopes("chat.admin.memberships"),
    )
    assert registry.preflight(
        Operation.MEMBERSHIPS_UPDATE,
        identity=AuthMode.USER,
        scopes=scopes("chat.admin.memberships"),
        variant=ExecutionVariant.ADMIN,
    )


def test_require_raises_capability_error() -> None:
    try:
        REGISTRY.require(
            Operation.SPACES_LIST,
            identity=AuthMode.USER,
            scopes=scopes("chat.messages"),
        )
    except CapabilityNotSupported as exc:
        assert "SPACES_LIST" in str(exc)
    else:
        raise AssertionError("CapabilityNotSupported not raised")


def test_duplicate_registration_raises() -> None:
    spec = OperationSpec(
        operation=Operation.SPACES_LIST,
        google_method="spaces.list",
        auth_paths=(AuthPath(AuthMode.APP, scopes("chat.bot")),),
    )
    try:
        OperationRegistry([spec, spec])
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("ValueError not raised")


def test_unknown_operation_raises() -> None:
    from chattice.capabilities.registry import UnknownOperation

    try:
        # Every Operation is registered in REGISTRY; an empty registry
        # exercises the unknown-operation path.
        OperationRegistry([]).spec(Operation.SPACES_SEARCH)
    except UnknownOperation as exc:
        assert "spaces.search" in str(exc)
    else:
        raise AssertionError("UnknownOperation not raised")


def test_registry_invariants_hold() -> None:
    from chattice.capabilities.registry import SPECS

    for spec in SPECS:
        assert spec.google_method, spec
        for path in spec.auth_paths:
            assert path.identity in (AuthMode.APP, AuthMode.USER), spec
            assert all(s.startswith("https://") for s in path.any_scope), spec
            if path.variant is ExecutionVariant.ADMIN:
                assert path.request_flag == "use_admin_access", spec


def test_paginated_flag_covers_all_list_operations() -> None:
    from chattice.capabilities.registry import SPECS

    paginated = {spec.operation for spec in SPECS if spec.paginated}
    assert Operation.MESSAGES_LIST in paginated
    assert Operation.SPACES_LIST in paginated
    assert Operation.MEMBERSHIPS_LIST in paginated
