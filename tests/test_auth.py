import json
from pathlib import Path

import pytest

from prism.auth import (
    CredentialConfigurationError,
    CredentialStore,
    Identity,
    LoginThrottle,
    configured_storage_secret,
    credential_record,
    identity_from_session,
    safe_redirect_path,
)


def _write_credentials(path: Path, access_code: str = "ABCD-EFGH-JKLM-NPQR") -> None:
    payload = {
        "version": 1,
        "credentials": [
            credential_record(
                "d01",
                "Docente 01",
                "participant",
                access_code,
                salt=b"0123456789abcdef",
            )
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_credentials_authenticate_without_storing_plaintext(tmp_path: Path) -> None:
    source = tmp_path / "access.json"
    access_code = "ABCD-EFGH-JKLM-NPQR"
    _write_credentials(source, access_code)

    assert access_code not in source.read_text(encoding="utf-8")
    identity = CredentialStore.from_path(source).authenticate(" d01 ", access_code)

    assert identity == Identity("D01", "Docente 01", "participant")


def test_invalid_and_unknown_credentials_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "access.json"
    _write_credentials(source)
    store = CredentialStore.from_path(source)

    assert store.authenticate("D01", "código-incorreto") is None
    assert store.authenticate("D99", "ABCD-EFGH-JKLM-NPQR") is None


def test_malformed_credentials_file_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "access.json"
    source.write_text('{"version": 1, "credentials": []}', encoding="utf-8")

    with pytest.raises(CredentialConfigurationError):
        CredentialStore.from_path(source)


def test_non_object_credentials_file_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "access.json"
    source.write_text("[]", encoding="utf-8")

    with pytest.raises(CredentialConfigurationError):
        CredentialStore.from_path(source)


def test_session_identity_requires_complete_signed_values() -> None:
    identity = Identity("D01", "Docente 01", "participant")

    assert identity_from_session(identity.as_session()) == identity
    assert identity_from_session({"authenticated": True, "user_id": "D01"}) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/", "/"),
        ("/workspace?session=1", "/workspace?session=1"),
        ("https://example.org", "/"),
        ("//example.org", "/"),
    ],
)
def test_redirects_are_restricted_to_local_paths(value: str, expected: str) -> None:
    assert safe_redirect_path(value) == expected


def test_login_throttle_temporarily_blocks_repeated_failures() -> None:
    throttle = LoginThrottle(max_attempts=2, lock_seconds=60)

    assert throttle.record_failure("D01") == 0
    assert throttle.record_failure("D01") > 0
    assert throttle.retry_after("D01") > 0
    throttle.clear("D01")
    assert throttle.retry_after("D01") == 0


def test_storage_secret_is_required_when_authentication_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("COERIA_AUTH_MODE", "required")
    monkeypatch.delenv("COERIA_STORAGE_SECRET", raising=False)

    with pytest.raises(CredentialConfigurationError):
        configured_storage_secret()


def test_storage_secret_can_be_omitted_for_explicit_local_mode(monkeypatch) -> None:
    monkeypatch.setenv("COERIA_AUTH_MODE", "disabled")
    monkeypatch.delenv("COERIA_STORAGE_SECRET", raising=False)

    assert configured_storage_secret() is None
