"""Versão suportada do estado persistente das sessões CoerIA."""

from __future__ import annotations

from typing import Any


SESSION_SCHEMA_VERSION = 33


def require_current_session_schema(state: dict[str, Any]) -> dict[str, Any]:
    """Rejeita estados que não pertençam exatamente ao esquema atual."""

    if not isinstance(state, dict):
        raise ValueError("O estado da sessão é inválido.")
    raw_version = state.get("schema_version")
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ValueError("A versão do estado da sessão é inválida.")
    if raw_version != SESSION_SCHEMA_VERSION:
        raise ValueError(
            "A sessão pertence a uma versão do CoerIA que já não é suportada."
        )
    return state
