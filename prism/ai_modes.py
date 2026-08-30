"""Modos de utilização da IA no alinhamento construtivo."""

from __future__ import annotations

from typing import Any, Iterable


AI_MODE_OFF = "AI-off"
AI_MODE_ON = "AI-on"
AI_MODE_ABOUT = "on-AI"

AI_MODES = (AI_MODE_OFF, AI_MODE_ON, AI_MODE_ABOUT)

AI_MODE_LABELS = {
    AI_MODE_OFF: "AI-off — aprendizagem sem IA",
    AI_MODE_ON: "AI-on — aprendizagem com IA",
    AI_MODE_ABOUT: "on-AI — aprendizagem sobre IA",
}

AI_MODE_DESCRIPTIONS = {
    AI_MODE_OFF: (
        "A competência é desenvolvida e demonstrada autonomamente, sem a IA "
        "executar a tarefa visada."
    ),
    AI_MODE_ON: (
        "A IA é um meio legítimo para realizar a tarefa; o estudante mantém "
        "responsabilidade pelo produto ou desempenho."
    ),
    AI_MODE_ABOUT: (
        "A utilização da IA é objeto de aprendizagem, incluindo prompting, "
        "orquestração, revisão crítica e decisão sobre a sua não utilização."
    ),
}


def canonical_ai_mode(value: Any, default: str = AI_MODE_OFF) -> str:
    """Normaliza um modo conhecido, usando AI-off como opção conservadora."""

    text = str(value or "").strip()
    for mode in AI_MODES:
        if text.casefold() == mode.casefold():
            return mode
    return default


def outcome_ai_mode_map(outcomes: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Indexa os modos explicitamente associados aos resultados."""

    return {
        str(outcome.get("id", "")).strip(): canonical_ai_mode(
            outcome.get("ai_mode")
        )
        for outcome in outcomes
        if isinstance(outcome, dict) and str(outcome.get("id", "")).strip()
    }


def linked_ai_mode(
    outcome_ids: Iterable[Any],
    outcomes: Iterable[dict[str, Any]],
) -> str | None:
    """Devolve o modo comum dos RA ligados ou ``None`` quando são incompatíveis."""

    mode_by_id = outcome_ai_mode_map(outcomes)
    identifiers = [str(identifier).strip() for identifier in outcome_ids]
    modes = {
        mode_by_id[identifier]
        for identifier in identifiers
        if identifier in mode_by_id
    }
    if not modes:
        return AI_MODE_OFF
    if len(modes) == 1:
        return next(iter(modes))
    return None


def sync_inherited_ai_mode(
    row: dict[str, Any],
    outcomes: Iterable[dict[str, Any]],
) -> str:
    """Atualiza uma AE/TA com o modo comum dos resultados associados."""

    outcome_ids = row.get("outcome_ids") or [row.get("outcome_id", "")]
    inherited = linked_ai_mode(outcome_ids, outcomes)
    row["ai_mode"] = inherited or ""
    return row["ai_mode"]


def ai_mode_alignment_issues(state: dict[str, Any]) -> list[str]:
    """Deteta desalinhamentos AI-mode nas relações RA–AE–TA."""

    outcomes = [
        item
        for item in state.get("learning_outcomes", [])
        if isinstance(item, dict)
    ]
    mode_by_outcome = outcome_ai_mode_map(outcomes)
    issues: list[str] = []

    for outcome in outcomes:
        identifier = str(outcome.get("id", "?")).strip() or "?"
        if str(outcome.get("ai_mode", "")).strip() not in AI_MODES:
            issues.append(f"{identifier}: modo de IA inválido")

    teaching_by_id: dict[str, dict[str, Any]] = {}
    for activity in state.get("teaching_activities", []):
        if not isinstance(activity, dict):
            continue
        identifier = str(activity.get("id", "?")).strip() or "?"
        teaching_by_id[identifier] = activity
        outcome_ids = [
            str(value).strip()
            for value in (
                activity.get("outcome_ids")
                or [activity.get("outcome_id", "")]
            )
            if str(value).strip()
        ]
        expected_modes = {
            mode_by_outcome[value]
            for value in outcome_ids
            if value in mode_by_outcome
        }
        received = str(activity.get("ai_mode", "")).strip()
        if len(expected_modes) > 1:
            issues.append(
                f"{identifier}: associa resultados com modos de IA diferentes"
            )
        elif expected_modes and received != next(iter(expected_modes)):
            issues.append(
                f"{identifier}: modo de IA diferente dos resultados associados"
            )
        elif received not in AI_MODES:
            issues.append(f"{identifier}: modo de IA inválido")

    for assessment in state.get("assessment_activities", []):
        if not isinstance(assessment, dict):
            continue
        identifier = str(assessment.get("id", "?")).strip() or "?"
        outcome_ids = [
            str(value).strip()
            for value in assessment.get("outcome_ids", [])
            if str(value).strip()
        ]
        expected_modes = {
            mode_by_outcome[value]
            for value in outcome_ids
            if value in mode_by_outcome
        }
        received = str(assessment.get("ai_mode", "")).strip()
        if len(expected_modes) > 1:
            issues.append(
                f"{identifier}: associa resultados com modos de IA diferentes"
            )
        elif expected_modes and received != next(iter(expected_modes)):
            issues.append(
                f"{identifier}: modo de IA diferente dos resultados associados"
            )
        elif received not in AI_MODES:
            issues.append(f"{identifier}: modo de IA inválido")

        teaching_modes = {
            str(teaching_by_id[value].get("ai_mode", "")).strip()
            for value in assessment.get("teaching_activity_ids", [])
            if value in teaching_by_id
        }
        if any(mode and mode != received for mode in teaching_modes):
            issues.append(
                f"{identifier}: modo de IA diferente das atividades de ensino associadas"
            )

    return list(dict.fromkeys(issues))
