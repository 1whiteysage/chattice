"""Request verification for Chat apps built as Google Workspace add-ons."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from google.auth import exceptions as google_auth_exceptions

import chattice.transports.http.verifier as verifier_module
from chattice.transports.http import (
    AddOnTokenVerifier,
    IncomingRequest,
    VerificationError,
)

AUDIENCE = "https://bot.example.com/chat"
SERVICE_ACCOUNT = "service-123@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"


def _request(token: str | None = "token") -> IncomingRequest:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return IncomingRequest(method="POST", path="/chat", headers=headers)


def _verifier() -> AddOnTokenVerifier:
    return AddOnTokenVerifier(
        audience=AUDIENCE,
        service_account_email=SERVICE_ACCOUNT,
        request=object(),  # type: ignore[arg-type]
    )


def _claims(**overrides: object) -> dict[str, object]:
    return {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": SERVICE_ACCOUNT,
        "email_verified": True,
        **overrides,
    }


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    result: dict[str, object] | Exception,
) -> dict[str, object]:
    calls: dict[str, object] = {}

    def fake(token: str, request: object, *, audience: str) -> dict[str, object]:
        calls.update(token=token, audience=audience)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(verifier_module, "verify_oauth2_token", fake)
    return calls


def test_addon_service_account_token_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, _claims())

    _verifier().verify(_request("signed"))

    assert calls == {"token": "signed", "audience": AUDIENCE}


@pytest.mark.parametrize(
    "claims",
    [
        # The Google Chat service account is the identity of the OTHER
        # payload family and must not pass for an add-on endpoint.
        _claims(email="chat@system.gserviceaccount.com"),
        _claims(email_verified=False),
        _claims(email=None),
    ],
)
def test_wrong_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]
) -> None:
    _stub(monkeypatch, claims)
    with pytest.raises(VerificationError):
        _verifier().verify(_request())


@pytest.mark.parametrize(
    "error",
    [
        ValueError("wrong audience"),
        google_auth_exceptions.GoogleAuthError("bad signature"),  # type: ignore[no-untyped-call]
        google_auth_exceptions.TransportError("certificates unreachable"),  # type: ignore[no-untyped-call]
    ],
)
def test_verification_failures_fail_closed(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _stub(monkeypatch, error)
    with pytest.raises(VerificationError):
        _verifier().verify(_request())


def test_missing_bearer_is_rejected_before_any_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub(monkeypatch, _claims())
    with pytest.raises(VerificationError):
        _verifier().verify(_request(None))
    assert calls == {}


@pytest.mark.parametrize(
    "build",
    [
        lambda: AddOnTokenVerifier(
            audience="1234567890", service_account_email=SERVICE_ACCOUNT
        ),
        lambda: AddOnTokenVerifier(audience=AUDIENCE, service_account_email=""),
        lambda: AddOnTokenVerifier(audience=AUDIENCE, service_account_email="nobody"),
    ],
)
def test_configuration_is_validated(build: Callable[[], AddOnTokenVerifier]) -> None:
    with pytest.raises(ValueError):
        build()
