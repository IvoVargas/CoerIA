"""Versão suportada do estado persistente das sessões CoerIA."""

from __future__ import annotations

from typing import Any

from .curriculum import canonical_outcome_type


SESSION_SCHEMA_VERSION = 33


def _normalize_outcome_types(value: Any) -> None:
    """Atualiza designações conhecidas sem reintroduzir migrações de esquema."""

    if isinstance(value, dict):
        if "outcome_type" in value:
            try:
                value["outcome_type"] = canonical_outcome_type(
                    value.get("outcome_type")
                )
            except ValueError:
                # Um valor desconhecido permanece visível para a validação o rejeitar.
                pass
        for child in value.values():
            _normalize_outcome_types(child)
    elif isinstance(value, list):
        for child in value:
            _normalize_outcome_types(child)


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
    _normalize_outcome_types(state)
    return state
