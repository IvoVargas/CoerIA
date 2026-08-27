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


def derive_alignment_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Produz uma síntese de alinhamento sem criar uma etapa editável.

    As relações são sempre calculadas a partir dos conteúdos, das atividades de
    ensino-aprendizagem e das tarefas de avaliação atuais. Desta forma, a
    síntese usada na validação e na exportação nunca fica desatualizada.
    """

    taxonomy = str(state.get("course", {}).get("taxonomy_type", "SOLO") or "SOLO")
    rows: list[dict[str, Any]] = []
    for outcome in state.get("learning_outcomes", []):
        if not isinstance(outcome, dict):
            continue
        outcome_id = str(outcome.get("id", ""))
        assessments = [
            item
            for item in state.get("assessment_activities", [])
            if isinstance(item, dict)
            and outcome_id in (item.get("outcome_ids") or [item.get("outcome_id")])
        ]
        teaching = [
            item
            for item in state.get("teaching_activities", [])
            if isinstance(item, dict)
            and outcome_id in (item.get("outcome_ids") or [item.get("outcome_id")])
        ]
        content_ids = content_ids_for_outcome(state, outcome_id)
        assessment_ids = sorted(
            {
                str(item.get("id", "")).strip()
                for item in assessments
                if str(item.get("id", "")).strip()
            }
        )
        teaching_ids = sorted(
            {
                str(item.get("id", "")).strip()
                for item in teaching
                if str(item.get("id", "")).strip()
            }
        )
        coherent = bool(content_ids and assessment_ids and teaching_ids)
        rows.append(
            {
                "outcome_id": outcome_id,
                "result": str(outcome.get("statement", "")),
                "content_ids": content_ids,
                "taxonomy": taxonomy,
                "taxonomy_level": str(outcome.get("taxonomy_level", "")),
                "assessment_ids": assessment_ids,
                "assessment_purposes": sorted(
                    {
                        str(item.get("assessment_purpose", "")).strip()
                        for item in assessments
                        if str(item.get("assessment_purpose", "")).strip()
                    }
                ),
                "teaching_activity_ids": teaching_ids,
                "status": "Coerente" if coherent else "Requer revisão",
                "rationale": (
                    "O resultado está ligado a conteúdo, atividade de "
                    "ensino-aprendizagem e tarefa de avaliação."
                    if coherent
                    else "Falta pelo menos uma ligação obrigatória a conteúdo, "
                    "atividade de ensino-aprendizagem ou tarefa de avaliação."
                ),
            }
        )
    return rows
