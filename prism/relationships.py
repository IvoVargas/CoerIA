"""Relações curriculares derivadas dos artefactos aprovados.

As sessões atuais guardam as ligações aos resultados nos conteúdos e objetivos.
As sessões anteriores à versão 12 podem ainda guardá-las nos próprios resultados;
os fallbacks abaixo mantêm essas sessões consultáveis durante a migração.
"""

from __future__ import annotations

from typing import Any


def content_ids_for_outcome(state: dict[str, Any], outcome_id: str) -> list[str]:
    """Devolve os conteúdos associados a um resultado, sem duplicados."""

    curriculum = state.get("curriculum_analysis")
    contents = curriculum.get("contents", []) if isinstance(curriculum, dict) else []
    identifiers = [
        str(content.get("id", ""))
        for content in contents
        if isinstance(content, dict)
        and outcome_id in content.get("outcome_ids", [])
        and content.get("id")
    ]
    if not identifiers:
        outcome = next(
            (
                item
                for item in state.get("learning_outcomes", [])
                if str(item.get("id", "")) == outcome_id
            ),
            {},
        )
        identifiers = [
            str(link.get("content_id", ""))
            for link in outcome.get("content_links", [])
            if link.get("content_id")
        ]
    return list(dict.fromkeys(identifiers))


def objective_ids_for_outcome(state: dict[str, Any], outcome_id: str) -> list[str]:
    """Devolve os objetivos associados a um resultado, sem duplicados."""

    curriculum = state.get("curriculum_analysis")
    objectives = (
        curriculum.get("objectives", []) if isinstance(curriculum, dict) else []
    )
    identifiers = [
        str(objective.get("id", ""))
        for objective in objectives
        if isinstance(objective, dict)
        and outcome_id in objective.get("outcome_ids", [])
        and objective.get("id")
    ]
    if not identifiers:
        outcome = next(
            (
                item
                for item in state.get("learning_outcomes", [])
                if str(item.get("id", "")) == outcome_id
            ),
            {},
        )
        identifiers = [
            str(identifier)
            for identifier in outcome.get("objective_ids", [])
            if identifier
        ]
    return list(dict.fromkeys(identifiers))
