"""Seleção, âmbitos e recursos determinísticos da etapa de recursos."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import (
    RESOURCE_ASSESSMENT_GRID,
    RESOURCE_LESSON_PLAN,
    RESOURCE_LESSON_PRESENTATIONS,
    RESOURCE_TEST,
)


def slide_outcome_ids(
    slide: dict[str, Any],
    allowed_ids: set[str] | None = None,
) -> list[str]:
    """Normaliza os resultados associados a um slide no esquema atual.

    As ligações são lidas apenas de ``outcome_ids``: mencionar ``RA1`` num
    título ou bullet não cria, por si só, uma relação pedagógica.
    """

    identifiers: list[str] = []
    raw_identifiers = slide.get("outcome_ids", [])
    if isinstance(raw_identifiers, list):
        identifiers.extend(str(value).strip().upper() for value in raw_identifiers)
    normalized: list[str] = []
    for identifier in identifiers:
        if not identifier or (allowed_ids is not None and identifier not in allowed_ids):
            continue
        if identifier not in normalized:
            normalized.append(identifier)
    return normalized


def lesson_scope(state: dict[str, Any], lesson_number: int) -> dict[str, Any]:
    """Devolve o contexto curricular de uma aula (numeração iniciada em 1)."""

    lessons = state.get("pedagogical_design", {}).get("lessons", [])
    if lesson_number < 1 or lesson_number > len(lessons):
        raise ValueError(f"A aula {lesson_number} não existe no planeamento atual.")
    lesson = lessons[lesson_number - 1]
    component_ids = [
        str(value).strip()
        for value in lesson.get("component_ids", [])
        if str(value).strip()
    ]
    teaching = {
        str(item.get("id", "")): item
        for item in state.get("teaching_activities", [])
        if str(item.get("id", "")).strip()
    }
    assessments = {
        str(item.get("id", "")): item
        for item in state.get("assessment_activities", [])
        if str(item.get("id", "")).strip()
    }
    teaching_ids: list[str] = [
        component_id for component_id in component_ids if component_id in teaching
    ]
    for component_id in component_ids:
        task = assessments.get(component_id, {})
        for activity_id in task.get("teaching_activity_ids", []):
            clean_id = str(activity_id).strip()
            if clean_id in teaching and clean_id not in teaching_ids:
                teaching_ids.append(clean_id)
    outcome_ids: list[str] = []
    for component_id in [*teaching_ids, *component_ids]:
        component = teaching.get(component_id) or assessments.get(component_id) or {}
        for outcome_id in component.get("outcome_ids", []):
            clean_id = str(outcome_id).strip()
            if clean_id and clean_id not in outcome_ids:
                outcome_ids.append(clean_id)
    outcomes = {
        str(item.get("id", "")): item
        for item in state.get("learning_outcomes", [])
        if str(item.get("id", "")).strip()
    }
    return {
        "kind": "lesson",
        "lesson_number": lesson_number,
        "label": f"Aula {lesson_number}",
        "duration_minutes": int(lesson.get("duration_minutes", 0) or 0),
        "session_type": str(lesson.get("session_type", "")),
        "component_ids": component_ids,
        "notes": str(lesson.get("notes", "")),
        "outcome_ids": outcome_ids,
        "learning_outcomes": [
            deepcopy(outcomes[outcome_id])
            for outcome_id in outcome_ids
            if outcome_id in outcomes
        ],
        "teaching_activities": [
            deepcopy(teaching[activity_id])
            for activity_id in teaching_ids
        ],
        "assessment_activities": [
            deepcopy(assessments[component_id])
            for component_id in component_ids
            if component_id in assessments
        ],
    }


def assessment_scope(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    """Devolve o contexto de uma tarefa usada para gerar um teste autónomo."""

    clean_id = str(task_id).strip()
    task = next(
        (
            item
            for item in state.get("assessment_activities", [])
            if str(item.get("id", "")).strip() == clean_id
        ),
        None,
    )
    if task is None:
        raise ValueError(f"A tarefa de avaliação {clean_id or '?'} não existe.")
    outcome_ids = [
        str(value).strip()
        for value in task.get("outcome_ids", [])
        if str(value).strip()
    ]
    outcomes = {
        str(item.get("id", "")): item
        for item in state.get("learning_outcomes", [])
        if str(item.get("id", "")).strip()
    }
    teaching = {
        str(item.get("id", "")): item
        for item in state.get("teaching_activities", [])
        if str(item.get("id", "")).strip()
    }
    return {
        "kind": "assessment_task",
        "assessment_task_id": clean_id,
        "label": clean_id,
        "outcome_ids": outcome_ids,
        "assessment_task": deepcopy(task),
        "learning_outcomes": [
            deepcopy(outcomes[outcome_id])
            for outcome_id in outcome_ids
            if outcome_id in outcomes
        ],
        "teaching_activities": [
            deepcopy(teaching[activity_id])
            for activity_id in task.get("teaching_activity_ids", [])
            if activity_id in teaching
        ],
    }


def validate_resource_scopes(
    state: dict[str, Any],
    selected_types: list[str],
    scopes: dict[str, Any] | None,
) -> dict[str, list[Any]]:
    """Normaliza alvos explícitos e rejeita referências desatualizadas.

    Nunca expande uma seleção vazia para todas as aulas ou tarefas: cada
    instância generativa deve resultar de uma escolha consciente do docente.
    """

    raw = scopes if isinstance(scopes, dict) else {}
    lesson_count = len(state.get("pedagogical_design", {}).get("lessons", []))
    allowed_lessons = list(range(1, lesson_count + 1))
    allowed_tasks = [
        str(item.get("id", "")).strip()
        for item in state.get("assessment_activities", [])
        if str(item.get("id", "")).strip()
    ]
    lesson_numbers: list[int] = []
    for value in raw.get("lesson_presentations", []):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number in allowed_lessons and number not in lesson_numbers:
            lesson_numbers.append(number)
    task_ids = [
        str(value).strip()
        for value in raw.get("tests", [])
        if str(value).strip() in allowed_tasks
    ]
    task_ids = list(dict.fromkeys(task_ids))

    if (
        RESOURCE_LESSON_PRESENTATIONS in selected_types
        and allowed_lessons
        and not lesson_numbers
    ):
        raise ValueError(
            "Selecione pelo menos uma aula para produzir apresentações das aulas."
        )
    if RESOURCE_TEST in selected_types and allowed_tasks and not task_ids:
        raise ValueError(
            "Selecione pelo menos uma tarefa de avaliação para produzir testes."
        )
    return {
        "lesson_presentations": lesson_numbers,
        "tests": task_ids,
    }


def build_lesson_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Cria uma fotografia legível do planeamento aprovado, sem usar IA."""

    return {
        "lessons": [
            {
                "lesson_number": index,
                "duration_minutes": int(item.get("duration_minutes", 0) or 0),
                "session_type": str(item.get("session_type", "")),
                "component_ids": list(item.get("component_ids", []) or []),
                "notes": str(item.get("notes", "")),
            }
            for index, item in enumerate(
                state.get("pedagogical_design", {}).get("lessons", []), start=1
            )
        ]
    }


def build_assessment_grid(state: dict[str, Any]) -> dict[str, Any]:
    """Materializa a relação RA↔AE↔TA num documento de apoio ao docente."""

    return {
        "rows": [
            {
                "assessment_task_id": str(item.get("id", "")),
                "teaching_activity_ids": list(
                    item.get("teaching_activity_ids", []) or []
                ),
                "outcome_ids": list(item.get("outcome_ids", []) or []),
                "assessment_purpose": str(item.get("assessment_purpose", "")),
                "work_type": str(item.get("work_type", "")),
                "activity": str(item.get("activity", "")),
                "evidence": str(item.get("evidence", "")),
                "criterion": str(item.get("criterion", "")),
            }
            for item in state.get("assessment_activities", [])
        ]
    }


def blank_extended_resources(selected_types: list[str]) -> dict[str, Any]:
    """Estrutura comum dos recursos nas sessões atuais."""

    return {
        "selected_types": list(selected_types),
        "presentation_outline": [],
        "lesson_presentations": [],
        "lesson_worksheet": {
            "title": "",
            "overview": "",
            "instructions": "",
            "sections": [],
        },
        "tests": [],
        "practical_activity": {
            "title": "",
            "context": "",
            "duration_minutes": 0,
            "materials": [],
            "steps": [],
            "deliverables": [],
            "criteria": [],
        },
        "lesson_plan": {"lessons": []},
        "assessment_grid": {"rows": []},
        "feedback_considered": None,
    }


def apply_deterministic_resources(
    state: dict[str, Any], resources: dict[str, Any]
) -> dict[str, Any]:
    """Atualiza os recursos derivados selecionados e esvazia os não selecionados."""

    result = deepcopy(resources)
    selected = set(result.get("selected_types", []))
    result["lesson_plan"] = (
        build_lesson_plan(state)
        if RESOURCE_LESSON_PLAN in selected
        else {"lessons": []}
    )
    result["assessment_grid"] = (
        build_assessment_grid(state)
        if RESOURCE_ASSESSMENT_GRID in selected
        else {"rows": []}
    )
    return result
