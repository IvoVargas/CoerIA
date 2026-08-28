"""Cópias de segurança portáteis de uma sessão CoerIA."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .branding import APP_VERSION, config_value


BACKUP_FORMAT = "coeria-session-backup"
BACKUP_FORMAT_VERSION = 1
BACKUP_MANIFEST_NAME = "manifest.json"
BACKUP_STATE_NAME = "estado_sessao.json"
DEFAULT_SESSION_BACKUP_MAX_BYTES = 240 * 1024 * 1024
DEFAULT_SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES = 384 * 1024 * 1024


def _configured_positive_limit(name: str, default: int) -> int:
    try:
        value = int(config_value(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def configured_session_backup_max_bytes() -> int:
    """Limite do ficheiro ZIP recebido pela aplicação."""

    return _configured_positive_limit(
        "SESSION_BACKUP_MAX_BYTES",
        DEFAULT_SESSION_BACKUP_MAX_BYTES,
    )


def configured_session_backup_max_uncompressed_bytes() -> int:
    """Limite do JSON depois de descomprimido, protegendo contra ZIP bombs."""

    return _configured_positive_limit(
        "SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES",
        DEFAULT_SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES,
    )


def _safe_backup_stem(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").lower()
    return normalized[:60] or "sessao"


def create_session_backup(state: dict[str, Any]) -> str:
    """Cria um ZIP autocontido com manifesto e estado integral da sessão."""

    if not isinstance(state, dict):
        raise ValueError("Não foi possível preparar a cópia da sessão.")
    state_bytes = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    maximum_uncompressed = configured_session_backup_max_uncompressed_bytes()
    if len(state_bytes) > maximum_uncompressed:
        raise ValueError(
            "A sessão excede o limite da cópia de segurança "
            f"({maximum_uncompressed // (1024 * 1024)} MB descomprimidos)."
        )

    created_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": APP_VERSION,
        "created_at": created_at,
        "source_session_id": str(state.get("session_id", "")),
        "unit_name": str(state.get("course", {}).get("unit_name", "")),
        "state_file": BACKUP_STATE_NAME,
        "state_bytes": len(state_bytes),
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    unit_stem = _safe_backup_stem(str(manifest["unit_name"]))
    session_stem = _safe_backup_stem(str(manifest["source_session_id"]))[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with NamedTemporaryFile(
        prefix=f"coeria_backup_{unit_stem}_{session_stem}_",
        suffix=f"_{timestamp}.coeria-backup.zip",
        delete=False,
    ) as temporary_file:
        destination = Path(temporary_file.name)
    try:
        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(BACKUP_MANIFEST_NAME, manifest_bytes)
            archive.writestr(BACKUP_STATE_NAME, state_bytes)
        maximum_backup = configured_session_backup_max_bytes()
        if destination.stat().st_size > maximum_backup:
            raise ValueError(
                "A cópia de segurança excede o limite de "
                f"{maximum_backup // (1024 * 1024)} MB."
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)


def read_session_backup(data: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valida integralmente uma cópia antes de devolver o estado contido."""

    if not isinstance(data, bytes) or not data:
        raise ValueError("Selecione uma cópia de segurança válida.")
    maximum_backup = configured_session_backup_max_bytes()
    if len(data) > maximum_backup:
        raise ValueError(
            "A cópia de segurança excede o limite de "
            f"{maximum_backup // (1024 * 1024)} MB."
        )

    try:
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if len(entries) != 2 or names != {
                BACKUP_MANIFEST_NAME,
                BACKUP_STATE_NAME,
            }:
                raise ValueError(
                    "A cópia de segurança não contém a estrutura esperada do CoerIA."
                )
            if any(entry.is_dir() or entry.flag_bits & 0x1 for entry in entries):
                raise ValueError("A cópia de segurança contém entradas inválidas.")
            entry_by_name = {entry.filename: entry for entry in entries}
            manifest_info = entry_by_name[BACKUP_MANIFEST_NAME]
            state_info = entry_by_name[BACKUP_STATE_NAME]
            maximum_uncompressed = configured_session_backup_max_uncompressed_bytes()
            if manifest_info.file_size > 64 * 1024:
                raise ValueError("O manifesto da cópia de segurança é inválido.")
            if state_info.file_size > maximum_uncompressed:
                raise ValueError(
                    "A sessão excede o limite de restauro "
                    f"({maximum_uncompressed // (1024 * 1024)} MB descomprimidos)."
                )
            manifest_bytes = archive.read(BACKUP_MANIFEST_NAME)
            state_bytes = archive.read(BACKUP_STATE_NAME)
    except zipfile.BadZipFile as error:
        raise ValueError("O ficheiro não é uma cópia de segurança válida do CoerIA.") from error

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        state = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("A cópia de segurança contém JSON inválido.") from error
    if not isinstance(manifest, dict) or not isinstance(state, dict):
        raise ValueError("A cópia de segurança contém uma estrutura inválida.")
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("O ficheiro não pertence ao formato de backup do CoerIA.")
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ValueError("A versão do formato de backup não é suportada.")
    if manifest.get("state_file") != BACKUP_STATE_NAME:
        raise ValueError("O manifesto referencia um estado de sessão inválido.")
    if manifest.get("state_bytes") != len(state_bytes):
        raise ValueError("A dimensão do estado não corresponde ao manifesto.")
    expected_checksum = str(manifest.get("state_sha256", ""))
    actual_checksum = hashlib.sha256(state_bytes).hexdigest()
    if not hmac.compare_digest(expected_checksum, actual_checksum):
        raise ValueError("A integridade da cópia de segurança não pôde ser confirmada.")
    return state, manifest
