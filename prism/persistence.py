"""Persistência local do estado partilhado e do histórico de decisões."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .auth import normalize_user_id
from .providers import AI_PROVIDER_OPENAI, validate_ai_provider
from .session_schema import require_current_session_schema


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "prism.db"


class SQLiteSessionStore:
    """Armazena sessões CoerIA e respetivo rasto de auditoria em SQLite."""

    def __init__(self, database_path: Path | str | None = None) -> None:
        configured_path = os.getenv("COERIA_DATABASE_PATH", "").strip()
        selected_path = database_path or configured_path or DEFAULT_DATABASE_PATH
        self.database_path = Path(selected_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialise(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        session_id TEXT NOT NULL,
                        event_index INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        event TEXT NOT NULL,
                        feedback TEXT NOT NULL,
                        PRIMARY KEY (session_id, event_index),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );

                    CREATE TABLE IF NOT EXISTS session_attachments (
                        session_id TEXT NOT NULL,
                        attachment_id TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        data BLOB NOT NULL,
                        PRIMARY KEY (session_id, attachment_id),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                            ON DELETE CASCADE
                    );
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(sessions)")
                }
                if "owner_id" not in columns:
                    raise RuntimeError(
                        "A base de dados pertence a uma versão do CoerIA "
                        "que já não é suportada."
                    )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated "
                    "ON sessions(owner_id, updated_at DESC)"
                )
        finally:
            connection.close()

    def save(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        owner_id: str = "LOCAL",
    ) -> str:
        """Cria ou atualiza uma sessão e substitui o respetivo rasto de auditoria."""

        require_current_session_schema(state)
        owner = normalize_user_id(owner_id)
        if not owner:
            raise ValueError("A sessão necessita de um proprietário válido.")
        identifier = session_id or str(uuid4())
        updated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        audit = state.get("audit", [])
        stored_state = dict(state)
        stored_state["session_id"] = identifier
        attachment_metadata: list[dict[str, Any]] = []
        attachment_payloads: dict[str, bytes] = {}
        for item in state.get("source_attachments", []):
            if not isinstance(item, dict):
                raise ValueError("A sessão contém metadados de anexo inválidos.")
            metadata = dict(item)
            attachment_id = str(metadata.get("id", "") or "").strip()
            if not attachment_id:
                raise ValueError("A sessão contém um anexo sem identificador.")
            encoded = str(metadata.pop("data_base64", "") or "").strip()
            if encoded:
                try:
                    payload = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ValueError("A sessão contém um anexo inválido.") from error
                metadata["size_bytes"] = len(payload)
                metadata["sha256"] = hashlib.sha256(payload).hexdigest()
                attachment_payloads[attachment_id] = payload
            attachment_metadata.append(metadata)
        stored_state["source_attachments"] = attachment_metadata

        connection = self._connect()
        try:
            with connection:
                existing = connection.execute(
                    "SELECT owner_id FROM sessions WHERE session_id = ?",
                    (identifier,),
                ).fetchone()
                if existing and existing["owner_id"] != owner:
                    raise PermissionError("A sessão pertence a outro utilizador.")
                connection.execute(
                    """
                    INSERT INTO sessions(session_id, owner_id, updated_at, state_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        state_json=excluded.state_json
                    """,
                    (
                        identifier,
                        owner,
                        updated_at,
                        json.dumps(stored_state, ensure_ascii=False),
                    ),
                )
                existing_attachment_ids = {
                    str(row["attachment_id"])
                    for row in connection.execute(
                        "SELECT attachment_id FROM session_attachments "
                        "WHERE session_id = ?",
                        (identifier,),
                    )
                }
                requested_attachment_ids = {
                    str(item["id"])
                    for item in attachment_metadata
                }
                missing_payload_ids = (
                    requested_attachment_ids
                    - existing_attachment_ids
                    - set(attachment_payloads)
                )
                if missing_payload_ids:
                    raise ValueError(
                        "Não foi possível guardar um anexo sem os respetivos dados."
                    )
                for attachment_id, payload in attachment_payloads.items():
                    connection.execute(
                        """
                        INSERT INTO session_attachments(
                            session_id, attachment_id, size_bytes, sha256, data
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, attachment_id) DO UPDATE SET
                            size_bytes=excluded.size_bytes,
                            sha256=excluded.sha256,
                            data=excluded.data
                        """,
                        (
                            identifier,
                            attachment_id,
                            len(payload),
                            hashlib.sha256(payload).hexdigest(),
                            payload,
                        ),
                    )
                for attachment_id in (
                    existing_attachment_ids - requested_attachment_ids
                ):
                    connection.execute(
                        "DELETE FROM session_attachments "
                        "WHERE session_id = ? AND attachment_id = ?",
                        (identifier, attachment_id),
                    )
                connection.execute(
                    "DELETE FROM audit_events WHERE session_id = ?",
                    (identifier,),
                )
                connection.executemany(
                    """
                    INSERT INTO audit_events(
                        session_id, event_index, timestamp, stage, event, feedback
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            identifier,
                            index,
                            event["timestamp"],
                            event["stage"],
                            event["event"],
                            event["feedback"],
                        )
                        for index, event in enumerate(audit)
                    ],
                )
        finally:
            connection.close()
        return identifier

    def load(
        self,
        session_id: str,
        owner_id: str | None = None,
        *,
        include_source_attachments: bool = True,
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            if owner_id is None:
                row = connection.execute(
                    "SELECT state_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                owner = normalize_user_id(owner_id)
                row = connection.execute(
                    """
                    SELECT state_json FROM sessions
                    WHERE session_id = ? AND owner_id = ?
                    """,
                    (session_id, owner),
                ).fetchone()
            attachment_rows = (
                connection.execute(
                    """
                    SELECT attachment_id, size_bytes, sha256, data
                    FROM session_attachments
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchall()
                if row and include_source_attachments
                else []
            )
        finally:
            connection.close()
        if not row:
            return None
        state = json.loads(row["state_json"])
        payloads = {
            str(attachment["attachment_id"]): attachment
            for attachment in attachment_rows
        }
        for metadata in state.get("source_attachments", []):
            if not isinstance(metadata, dict):
                continue
            payload_row = payloads.get(str(metadata.get("id", "")))
            if payload_row is None:
                continue
            payload = bytes(payload_row["data"])
            if (
                int(payload_row["size_bytes"]) != len(payload)
                or not hashlib.sha256(payload).hexdigest()
                == str(payload_row["sha256"])
            ):
                raise ValueError("A integridade de um anexo guardado é inválida.")
            metadata["size_bytes"] = len(payload)
            metadata["sha256"] = str(payload_row["sha256"])
            metadata["data_base64"] = base64.b64encode(payload).decode("ascii")
        state["session_id"] = session_id
        return require_current_session_schema(state)

    def list_sessions(
        self,
        limit: int = 100,
        owner_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Lista sessões recentes sem expor o conteúdo integral na interface."""

        if limit <= 0:
            return []
        connection = self._connect()
        try:
            if owner_id is None:
                rows = connection.execute(
                    """
                    SELECT session_id, updated_at, state_json
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                owner = normalize_user_id(owner_id)
                rows = connection.execute(
                    """
                    SELECT session_id, updated_at, state_json
                    FROM sessions
                    WHERE owner_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (owner, limit),
                ).fetchall()
        finally:
            connection.close()

        summaries: list[dict[str, str]] = []
        for row in rows:
            try:
                state = json.loads(row["state_json"])
                require_current_session_schema(state)
                course = state.get("course", {})
                summaries.append(
                    {
                        "session_id": row["session_id"],
                        "updated_at": row["updated_at"],
                        "unit_name": str(course.get("unit_name", "Sessão sem título")),
                        "ai_provider": validate_ai_provider(
                            state.get("ai_provider", AI_PROVIDER_OPENAI)
                        ),
                        "current_stage": str(state.get("current_stage", "")),
                        "status": str(state.get("status", "")),
                    }
                )
            except (TypeError, json.JSONDecodeError):
                continue
        return summaries

    def delete(
        self,
        session_id: str,
        owner_id: str | None = None,
    ) -> bool:
        """Elimina uma sessão e o respetivo rasto de auditoria.

        Quando ``owner_id`` é fornecido, a operação só é executada se a
        sessão pertencer a esse utilizador.
        """

        identifier = str(session_id or "").strip()
        if not identifier:
            return False

        owner = normalize_user_id(owner_id) if owner_id is not None else None
        connection = self._connect()
        try:
            with connection:
                if owner is None:
                    row = connection.execute(
                        "SELECT 1 FROM sessions WHERE session_id = ?",
                        (identifier,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        SELECT 1 FROM sessions
                        WHERE session_id = ? AND owner_id = ?
                        """,
                        (identifier, owner),
                    ).fetchone()

                if row is None:
                    return False

                connection.execute(
                    "DELETE FROM audit_events WHERE session_id = ?",
                    (identifier,),
                )
                connection.execute(
                    "DELETE FROM session_attachments WHERE session_id = ?",
                    (identifier,),
                )
                if owner is None:
                    cursor = connection.execute(
                        "DELETE FROM sessions WHERE session_id = ?",
                        (identifier,),
                    )
                else:
                    cursor = connection.execute(
                        """
                        DELETE FROM sessions
                        WHERE session_id = ? AND owner_id = ?
                        """,
                        (identifier, owner),
                    )
        finally:
            connection.close()

        return cursor.rowcount > 0
