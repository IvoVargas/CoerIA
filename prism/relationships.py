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

    O triângulo é explícito na tabela de avaliação: cada tarefa indica as
    atividades que a preparam e os resultados que avalia diretamente.
    """

    taxonomy = str(state.get("course", {}).get("taxonomy_type", "SOLO") or "SOLO")
    assessment_by_id = {
        str(item.get("id", "")): item
        for item in state.get("assessment_activities", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    rows: list[dict[str, Any]] = []
    for outcome in state.get("learning_outcomes", []):
        if not isinstance(outcome, dict):
            continue
        outcome_id = str(outcome.get("id", ""))
        teaching = [
            item
            for item in state.get("teaching_activities", [])
            if isinstance(item, dict)
            and outcome_id in (item.get("outcome_ids") or [item.get("outcome_id")])
        ]
        content_ids = content_ids_for_outcome(state, outcome_id)
        teaching_ids = sorted(
            {
                str(item.get("id", "")).strip()
                for item in teaching
                if str(item.get("id", "")).strip()
            }
        )
        assessment_ids = list(
            dict.fromkeys(
                str(item.get("id", "")).strip()
                for item in state.get("assessment_activities", [])
                if isinstance(item, dict)
                and outcome_id in item.get("outcome_ids", [])
                and str(item.get("id", "")).strip()
            )
        )
        assessments = [
            assessment_by_id[identifier]
            for identifier in assessment_ids
            if identifier in assessment_by_id
        ]
        unknown_assessment_ids = [
            identifier for identifier in assessment_ids if identifier not in assessment_by_id
        ]
        incompatible_assessment_ids = [
            str(item.get("id", ""))
            for item in assessments
            if not set(item.get("teaching_activity_ids", [])) & set(teaching_ids)
        ]
        coherent = bool(content_ids and assessment_ids and teaching_ids)
        coherent = coherent and not unknown_assessment_ids and not incompatible_assessment_ids
        if coherent:
            rationale = (
                "O resultado está ligado diretamente à avaliação e essa tarefa partilha "
                "uma atividade de ensino-aprendizagem que desenvolve o resultado."
            )
        else:
            issues: list[str] = []
            if not content_ids:
                issues.append("sem conteúdo")
            if not teaching_ids:
                issues.append("sem atividade de ensino-aprendizagem")
            if not assessment_ids:
                issues.append("sem ligação direta a tarefa de avaliação")
            if unknown_assessment_ids:
                issues.append(
                    "tarefas desconhecidas: " + ", ".join(unknown_assessment_ids)
                )
            if incompatible_assessment_ids:
                issues.append(
                    "tarefas sem atividade comum ao resultado: "
                    + ", ".join(incompatible_assessment_ids)
                )
            rationale = "; ".join(issues) + "."
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
                "rationale": rationale,
            }
        )
    return rows
