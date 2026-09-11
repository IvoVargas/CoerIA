"""Relações curriculares derivadas dos artefactos aprovados."""

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
    return list(dict.fromkeys(identifiers))


def outcome_ids_for_assessments(
    state: dict[str, Any],
    assessment_ids: list[Any] | tuple[Any, ...] | None,
) -> list[str]:
    """Deriva os RA das tarefas selecionadas, preservando a ordem curricular."""

    selected = {
        str(identifier).strip()
        for identifier in (assessment_ids or [])
        if str(identifier).strip()
    }
    linked = {
        str(outcome_id).strip()
        for assessment in state.get("assessment_activities", [])
        if isinstance(assessment, dict)
        and str(assessment.get("id", "")).strip() in selected
        for outcome_id in assessment.get("outcome_ids", [])
        if str(outcome_id).strip()
    }
    ordered = [
        str(outcome.get("id", "")).strip()
        for outcome in state.get("learning_outcomes", [])
        if isinstance(outcome, dict)
        and str(outcome.get("id", "")).strip() in linked
    ]
    return list(dict.fromkeys(ordered))


def synchronize_teaching_outcomes(
    state: dict[str, Any],
    activities: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Mantém ``outcome_ids`` como projeção informativa de ``assessment_ids``.

    A relação editável da atividade é AE→TA. Os resultados associados não são
    uma segunda decisão do docente: são sempre recalculados a partir das tarefas.
    """

    rows = activities if activities is not None else state.get("teaching_activities", [])
    if not isinstance(rows, list):
        return []
    for activity in rows:
        if isinstance(activity, dict):
            activity["outcome_ids"] = outcome_ids_for_assessments(
                state,
                activity.get("assessment_ids", []),
            )
    return rows


def derive_alignment_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Produz uma síntese de alinhamento sem criar uma etapa editável.

    A cadeia segue o backward design: cada tarefa indica os resultados que
    avalia e cada atividade indica as tarefas para as quais prepara o estudante.
    A relação AE→RA é derivada, nunca uma segunda fonte de verdade.
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
        content_ids = content_ids_for_outcome(state, outcome_id)
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
        teaching = [
            item
            for item in state.get("teaching_activities", [])
            if isinstance(item, dict)
            and set(item.get("assessment_ids", [])) & set(assessment_ids)
        ]
        teaching_ids = sorted(
            {
                str(item.get("id", "")).strip()
                for item in teaching
                if str(item.get("id", "")).strip()
            }
        )
        unsupported_assessment_ids = [
            identifier
            for identifier in assessment_ids
            if not any(identifier in item.get("assessment_ids", []) for item in teaching)
        ]
        coherent = bool(content_ids and assessment_ids and teaching_ids)
        coherent = coherent and not unknown_assessment_ids and not unsupported_assessment_ids
        if coherent:
            rationale = (
                "O resultado está ligado diretamente à avaliação e essa tarefa está "
                "ligada a uma atividade de ensino-aprendizagem que prepara a evidência."
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
            if unsupported_assessment_ids:
                issues.append(
                    "tarefas sem atividade de preparação: "
                    + ", ".join(unsupported_assessment_ids)
                )
            rationale = "; ".join(issues) + "."
        rows.append(
            {
                "outcome_id": outcome_id,
                "result": str(outcome.get("statement", "")),
                "content_ids": content_ids,
                "taxonomy": taxonomy,
                "taxonomy_level": str(outcome.get("taxonomy_level", "")),
                "ai_mode": str(outcome.get("ai_mode", "AI-off")),
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
