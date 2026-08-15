"""Autenticação local por códigos de acesso sem guardar segredos em claro."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 32
VALID_ROLES = {"participant", "admin"}


class CredentialConfigurationError(RuntimeError):
    """Indica que a configuração externa de autenticação não é utilizável."""


@dataclass(frozen=True)
class Identity:
    """Identidade pseudónima autenticada na aplicação."""

    user_id: str
    display_name: str
    role: str

    def as_session(self) -> dict[str, str | bool]:
        return {
            "authenticated": True,
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role": self.role,
        }


@dataclass(frozen=True)
class _Credential:
    identity: Identity
    salt: bytes
    digest: bytes


def authentication_disabled() -> bool:
    """Permite execução local explícita sem autenticação; produção nega por omissão."""

    return os.getenv("COERIA_AUTH_MODE", "required").strip().casefold() == "disabled"


def configured_storage_secret() -> str | None:
    """Obtém o segredo de sessão e falha cedo quando a autenticação o exige."""

    secret = os.getenv("COERIA_STORAGE_SECRET", "").strip()
    if authentication_disabled():
        return secret or None
    if len(secret) < 32:
        raise CredentialConfigurationError(
            "COERIA_STORAGE_SECRET deve conter pelo menos 32 caracteres."
        )
    return secret


def normalize_user_id(value: str) -> str:
    """Normaliza identificadores sem introduzir dados pessoais."""

    return str(value or "").strip().upper()[:80]


def _derive_digest(access_code: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        access_code.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LENGTH,
    )


def credential_record(
    user_id: str,
    display_name: str,
    role: str,
    access_code: str,
    *,
    salt: bytes,
) -> dict[str, str]:
    """Cria o registo seguro que pode ser colocado no ficheiro de acesso."""

    normalized_id = normalize_user_id(user_id)
    normalized_role = str(role).strip().casefold()
    if not normalized_id or not display_name.strip() or normalized_role not in VALID_ROLES:
        raise ValueError("Credencial inválida.")
    if len(access_code) < 12:
        raise ValueError("O código de acesso deve conter pelo menos 12 caracteres.")
    digest = _derive_digest(access_code, salt)
    return {
        "user_id": normalized_id,
        "display_name": display_name.strip(),
        "role": normalized_role,
        "algorithm": "scrypt-v1",
        "salt": base64.b64encode(salt).decode("ascii"),
        "digest": base64.b64encode(digest).decode("ascii"),
    }


class CredentialStore:
    """Carrega e verifica credenciais com comparação resistente a temporização."""

    _DUMMY_SALT = b"CoerIA-invalid!"
    _DUMMY_DIGEST = _derive_digest("invalid-access-code", _DUMMY_SALT)

    def __init__(self, credentials: Mapping[str, _Credential]) -> None:
        self._credentials = dict(credentials)

    @classmethod
    def from_path(cls, path: Path | str) -> "CredentialStore":
        source = Path(path).expanduser()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CredentialConfigurationError(
                "Não foi possível carregar o ficheiro de acessos."
            ) from error

        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(payload.get("credentials"), list)
        ):
            raise CredentialConfigurationError("Formato do ficheiro de acessos inválido.")

        credentials: dict[str, _Credential] = {}
        try:
            for item in payload["credentials"]:
                user_id = normalize_user_id(item["user_id"])
                display_name = str(item["display_name"]).strip()
                role = str(item["role"]).strip().casefold()
                if (
                    not user_id
                    or not display_name
                    or role not in VALID_ROLES
                    or item.get("algorithm") != "scrypt-v1"
                    or user_id in credentials
                ):
                    raise ValueError
                salt = base64.b64decode(item["salt"], validate=True)
                digest = base64.b64decode(item["digest"], validate=True)
                if len(salt) < 16 or len(digest) != SCRYPT_LENGTH:
                    raise ValueError
                credentials[user_id] = _Credential(
                    Identity(user_id, display_name, role),
                    salt,
                    digest,
                )
        except (KeyError, TypeError, ValueError) as error:
            raise CredentialConfigurationError(
                "Uma ou mais credenciais têm formato inválido."
            ) from error

        if not credentials:
            raise CredentialConfigurationError("O ficheiro de acessos está vazio.")
        return cls(credentials)

    @classmethod
    def from_environment(cls) -> "CredentialStore":
        path = os.getenv("COERIA_ACCESS_FILE", "").strip()
        if not path:
            raise CredentialConfigurationError("COERIA_ACCESS_FILE não está configurado.")
        return cls.from_path(path)

    def authenticate(self, user_id: str, access_code: str) -> Identity | None:
        normalized_id = normalize_user_id(user_id)
        credential = self._credentials.get(normalized_id)
        salt = credential.salt if credential else self._DUMMY_SALT
        expected = credential.digest if credential else self._DUMMY_DIGEST
        candidate = _derive_digest(str(access_code or ""), salt)
        if credential and hmac.compare_digest(candidate, expected):
            return credential.identity
        return None


def identity_from_session(storage: Mapping[str, Any]) -> Identity | None:
    """Reconstrói apenas identidades completas e com função conhecida."""

    if storage.get("authenticated") is not True:
        return None
    user_id = normalize_user_id(str(storage.get("user_id", "")))
    display_name = str(storage.get("display_name", "")).strip()
    role = str(storage.get("role", "")).strip().casefold()
    if not user_id or not display_name or role not in VALID_ROLES:
        return None
    return Identity(user_id, display_name, role)


def safe_redirect_path(value: str) -> str:
    """Impede que o formulário de login seja usado como redirecionamento externo."""

    candidate = str(value or "/").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    return candidate


class LoginThrottle:
    """Bloqueio temporário por identificador após tentativas repetidas."""

    def __init__(self, max_attempts: int = 5, lock_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self._attempts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, user_id: str) -> int:
        key = normalize_user_id(user_id) or "<EMPTY>"
        now = time.monotonic()
        with self._lock:
            count, locked_until = self._attempts.get(key, (0, 0.0))
            if locked_until <= now:
                if locked_until:
                    self._attempts.pop(key, None)
                return 0
            return max(1, int(locked_until - now + 0.999))

    def record_failure(self, user_id: str) -> int:
        key = normalize_user_id(user_id) or "<EMPTY>"
        now = time.monotonic()
        with self._lock:
            count, locked_until = self._attempts.get(key, (0, 0.0))
            if locked_until > now:
                return max(1, int(locked_until - now + 0.999))
            count += 1
            if count >= self.max_attempts:
                locked_until = now + self.lock_seconds
                count = 0
            self._attempts[key] = (count, locked_until)
            return max(0, int(locked_until - now + 0.999))

    def clear(self, user_id: str) -> None:
        key = normalize_user_id(user_id) or "<EMPTY>"
        with self._lock:
            self._attempts.pop(key, None)
