"""Relações curriculares derivadas dos artefactos aprovados.

As sessões atuais guardam as ligações aos resultados nos conteúdos. As sessões
anteriores à versão 12 podem ainda guardá-las nos próprios resultados; o fallback
abaixo mantém essas sessões consultáveis durante a migração.
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
