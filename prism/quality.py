"""Validações pedagógicas determinísticas e independentes do modelo generativo."""

from __future__ import annotations

import unicodedata
import re
from collections import Counter
from copy import deepcopy
from typing import Any

from .curriculum import (
    ASSESSMENT_PURPOSES,
    MAX_OUTCOMES,
    MIN_OUTCOMES,
    has_single_action_verb,
    taxonomy_verb_allowed,
    validate_taxonomy_choice,
)
from .models import (
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
)
from .relationships import derive_alignment_rows


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def _check(check_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "detail": detail}


def _quality_navigation_target(check: dict[str, str]) -> dict[str, str]:
    """Associa cada controlo ao artefacto que o docente pode corrigir."""

    check_id = check["id"]
    detail = check.get("detail", "")
    target_stage = "resources"
    target_key = "__stage__"
    if check_id in {"unique_outcomes", "taxonomy_outcomes"}:
        target_stage = "learning_outcomes"
        references = re.findall(r"\bRA\d+\b", detail, flags=re.IGNORECASE)
        target_key = references[0].upper() if references else "__stage__"
    elif check_id.startswith("assessment_"):
        target_stage = "assessment_activities"
        references = re.findall(r"\bTA\d+\b", detail, flags=re.IGNORECASE)
        target_key = references[0].upper() if references else "__stage__"
    elif check_id.startswith("teaching_") or check_id == "formative_activity_structure":
        target_stage = "teaching_activities"
        references = re.findall(r"\bAE\d+\b", detail, flags=re.IGNORECASE)
        target_key = references[0].upper() if references else "__stage__"
    elif check_id == "constructive_alignment":
        target_stage = "pedagogical_design"
        references = re.findall(r"\bRA\d+\b", detail, flags=re.IGNORECASE)
        target_key = references[0].upper() if references else "__stage__"
    elif check_id == "presentation_visuals":
        slides = re.findall(r"\bslide\s+(\d+)\b", detail, flags=re.IGNORECASE)
        target_key = f"SLIDE:{slides[0]}" if slides else "RESOURCE:presentation"
    elif "nao selecionado" in _normalise(detail):
        target_key = "__stage__"
    elif "apresentacao_powerpoint" in check_id:
        target_key = "RESOURCE:presentation"
    elif "ficha_de_aula" in check_id:
        target_key = "RESOURCE:worksheet"
    elif "atividade_pratica" in check_id or check_id == "practical_weights":
        target_key = "RESOURCE:practical"
    elif "teste" in check_id or check_id == "test_points":
        target_key = "RESOURCE:test"
    return {"target_stage": target_stage, "target_key": target_key}


def _many_to_many_coverage_check(
    check_id: str,
    label: str,
    expected: set[str],
    items: list[dict[str, Any]],
) -> dict[str, str]:
    if not expected:
        return _check(
            check_id,
            label,
            "warning",
            "Não existem resultados de aprendizagem; a cobertura não pode ser avaliada.",
        )
    if not items:
        return _check(
            check_id,
            label,
            "error",
            "Não existem atividades para cobrir os resultados de aprendizagem.",
        )
    received = {
        str(identifier)
        for item in items
        for identifier in (item.get("outcome_ids") or [item.get("outcome_id", "")])
        if identifier
    }
    identifiers = [str(item.get("id", "")) for item in items]
    duplicate_ids = sorted(
        item for item, count in Counter(identifiers).items() if item and count > 1
    )
    missing = sorted(expected - received)
    extra = sorted(received - expected)
    if missing or extra or duplicate_ids or any(not item for item in identifiers):
        details = []
        if missing:
            details.append("em falta: " + ", ".join(missing))
        if extra:
            details.append("desconhecidos: " + ", ".join(extra))
        if duplicate_ids:
            details.append("IDs duplicados: " + ", ".join(duplicate_ids))
        if any(not item for item in identifiers):
            details.append("existem atividades sem ID")
        return _check(check_id, label, "error", "; ".join(details))
    return _check(
        check_id,
        label,
        "pass",
        f"Cobertura muitos-para-muitos de {len(expected)} resultados.",
    )


def presentation_visual_issues(
    state: dict[str, Any],
    slide: dict[str, Any],
) -> list[str]:
    """Explica cada falha da especificação visual de um slide."""

    issues: list[str] = []
    allowed_visual_kinds = {
        "capa",
        "conceito",
        "processo",
        "comparacao",
        "sintese",
    }
    visual_kind = str(slide.get("visual_kind", "")).strip()
    visual_title = str(slide.get("visual_title", "")).strip()
    raw_visual_items = slide.get("visual_items", [])
    visual_items = raw_visual_items if isinstance(raw_visual_items, list) else []
    visual_mode = str(slide.get("visual_mode", "")).strip()
    visual_asset_id = str(slide.get("visual_asset_id", "")).strip()
    visual_prompt = str(slide.get("visual_prompt", "")).strip()

    if visual_kind not in allowed_visual_kinds:
        issues.append("tipo visual ausente ou inválido")
    if not visual_title:
        issues.append("título do elemento visual em falta")
    if not isinstance(raw_visual_items, list) or not 2 <= len(visual_items) <= 4:
        issues.append(
            f"{len(visual_items)} elementos; o diagrama admite 2 a 4"
        )
    else:
        empty_positions = [
            str(index)
            for index, item in enumerate(visual_items, start=1)
            if not str(item).strip()
        ]
        if empty_positions:
            issues.append(
                "elementos vazios nas posições " + ", ".join(empty_positions)
            )
    if not str(slide.get("visual_source", "")).strip():
        issues.append("origem visual em falta")
    if not str(slide.get("alt_text", "")).strip():
        issues.append("descrição acessível em falta")

    source_asset_ids = {
        str(item.get("id", ""))
        for item in state.get("source_images", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    generated_assets = {
        str(item.get("id", "")): item
        for item in state.get("generated_images", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    pending_ai_allowed = bool(
        state.get("resource_generation_scope")
        and state.get("ai_image_generation_enabled")
    )
    if visual_mode not in {"diagrama", "documento", "ia"}:
        issues.append("modo visual ausente ou inválido")
    elif visual_mode == "diagrama" and visual_asset_id:
        issues.append("um diagrama editável não pode ter uma imagem associada")
    elif visual_mode == "documento" and visual_asset_id not in source_asset_ids:
        issues.append("imagem documental ausente ou desconhecida")
    elif visual_mode == "ia":
        generated_asset = generated_assets.get(visual_asset_id)
        generated_ready = bool(
            generated_asset
            and str(generated_asset.get("prompt", "")).strip()
        )
        pending_generation = bool(
            pending_ai_allowed and not visual_asset_id and visual_prompt
        )
        if not (generated_ready or pending_generation):
            issues.append("imagem de IA ausente ou sem instrução válida")
    return issues


def evaluate_quality(state: dict[str, Any], resources: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produz um relatório de qualidade calculado apenas a partir dos artefactos."""

    checks: list[dict[str, str]] = []
    outcomes = state.get("learning_outcomes", [])
    expected_ids = {str(item.get("id", "")) for item in outcomes if item.get("id")}

    if (
        not MIN_OUTCOMES <= len(outcomes) <= MAX_OUTCOMES
        or len(expected_ids) != len(outcomes)
    ):
        checks.append(
            _check(
                "unique_outcomes",
                "Resultados de aprendizagem únicos",
                "error",
                "Devem existir entre 4 e 10 resultados com identificadores únicos.",
            )
        )
    else:
        checks.append(
            _check(
                "unique_outcomes",
                "Resultados de aprendizagem únicos",
                "pass",
                f"Foram encontrados {len(outcomes)} resultados com identificadores únicos.",
            )
        )

    selected_taxonomy = validate_taxonomy_choice(
        state.get("course", {}).get("taxonomy_type", "SOLO")
    )
    taxonomy_issues: list[str] = []
    for outcome in outcomes:
        if not taxonomy_verb_allowed(
            selected_taxonomy,
            str(outcome.get("taxonomy_level", "")),
            str(outcome.get("action_verb", "")),
        ):
            taxonomy_issues.append(
                f"{outcome.get('id', '?')}: verbo incompatível com o nível"
            )
        if not has_single_action_verb(
            str(outcome.get("statement", "")),
            str(outcome.get("action_verb", "")),
            selected_taxonomy,
        ):
            taxonomy_issues.append(
                f"{outcome.get('id', '?')}: deve conter um único verbo de ação principal"
            )
    checks.append(
        _check(
            "taxonomy_outcomes",
            f"Coerência entre Taxonomia {selected_taxonomy} e resultados",
            "warning" if not outcomes else "error" if taxonomy_issues else "pass",
            (
                "Não existem resultados de aprendizagem; a coerência taxonómica não pode ser avaliada."
                if not outcomes
                else "; ".join(taxonomy_issues)
                if taxonomy_issues
                else "Resultados, níveis e verbos mantêm-se coerentes."
            ),
        )
    )

    checks.append(
        _many_to_many_coverage_check(
            "assessment_coverage",
            "Cobertura das atividades de avaliação",
            expected_ids,
            state.get("assessment_activities", []),
        )
    )
    invalid_assessment_purposes = [
        item.get("id", "?")
        for item in state.get("assessment_activities", [])
        if item.get("assessment_purpose") not in ASSESSMENT_PURPOSES
    ]
    checks.append(
        _check(
            "assessment_purposes",
            "Finalidade das avaliações",
            (
                "warning"
                if not state.get("assessment_activities", [])
                else "error"
                if invalid_assessment_purposes
                else "pass"
            ),
            (
                "Não existem tarefas de avaliação; a finalidade não pode ser avaliada."
                if not state.get("assessment_activities", [])
                else "Finalidade inválida em: "
                + ", ".join(invalid_assessment_purposes)
                if invalid_assessment_purposes
                else "Cada avaliação é exclusivamente Formativa ou Sumativa."
            ),
        )
    )
    checks.append(
        _many_to_many_coverage_check(
            "teaching_coverage",
            "Cobertura das atividades de ensino-aprendizagem",
            expected_ids,
            state.get("teaching_activities", []),
        )
    )
    incomplete_formative_activities = [
        item.get("id", "?")
        for item in state.get("teaching_activities", [])
        if not item.get("practice")
        or not item.get("support")
        or not item.get("feedback_strategy")
    ]
    checks.append(
        _check(
            "formative_activity_structure",
            "Estrutura das atividades de ensino-aprendizagem",
            (
                "warning"
                if not state.get("teaching_activities", [])
                else "error"
                if incomplete_formative_activities
                else "pass"
            ),
            (
                "Não existem atividades de ensino-aprendizagem; a estrutura não pode ser avaliada."
                if not state.get("teaching_activities", [])
                else "Estrutura incompleta em: "
                + ", ".join(incomplete_formative_activities)
                if incomplete_formative_activities
                else "Prática, acompanhamento e feedback estão explícitos."
            ),
        )
    )
    alignment_rows = derive_alignment_rows(state)
    incomplete_alignment = []
    for row in alignment_rows:
        missing_links = []
        if not row.get("content_ids"):
            missing_links.append("conteúdo")
        if not row.get("teaching_activity_ids"):
            missing_links.append("atividade de ensino-aprendizagem")
        if not row.get("assessment_ids"):
            missing_links.append("tarefa de avaliação")
        if missing_links:
            incomplete_alignment.append(
                f"{row.get('outcome_id', '?')}: " + ", ".join(missing_links)
            )
    checks.append(
        _check(
            "constructive_alignment",
            "Cobertura do alinhamento pedagógico",
            (
                "warning"
                if not expected_ids
                else "error"
                if incomplete_alignment
                else "pass"
            ),
            (
                "Não existem resultados de aprendizagem; o alinhamento não pode ser avaliado."
                if not expected_ids
                else "Ligações em falta — " + "; ".join(incomplete_alignment)
                if incomplete_alignment
                else (
                    "Todos os resultados estão ligados a conteúdo, atividade de "
                    "ensino-aprendizagem e tarefa de avaliação."
                )
            ),
        )
    )

    resource_data = resources if resources is not None else state.get("resources", {})
    requested = set(state.get("resource_types", []))
    selected = set(resource_data.get("selected_types", []))
    checks.append(
        _check(
            "resource_selection",
            "Correspondência dos recursos selecionados",
            "pass" if requested == selected else "error",
            (
                "A seleção foi respeitada."
                if requested == selected
                else f"Pedido: {sorted(requested)}; recebido: {sorted(selected)}."
            ),
        )
    )

    resource_rules = {
        RESOURCE_PRESENTATION: bool(resource_data.get("presentation_outline")),
        RESOURCE_WORKSHEET: bool(resource_data.get("lesson_worksheet", {}).get("sections")),
        RESOURCE_TEST: bool(resource_data.get("test", {}).get("questions")),
        RESOURCE_PRACTICAL: bool(resource_data.get("practical_activity", {}).get("steps")),
    }
    for resource_type, populated in resource_rules.items():
        requested_resource = resource_type in requested
        valid = populated if requested_resource else not populated
        checks.append(
            _check(
                "resource_" + _normalise(resource_type).replace(" ", "_"),
                f"Conteúdo de {resource_type}",
                "pass" if valid else "error",
                (
                    "Recurso gerado conforme solicitado."
                    if requested_resource and populated
                    else "Recurso não selecionado permaneceu vazio."
                    if not requested_resource and not populated
                    else "O conteúdo não corresponde à seleção do docente."
                ),
            )
        )

    if RESOURCE_PRESENTATION in requested:
        presentation_slides = resource_data.get("presentation_outline", [])
        invalid_visual_slides: list[str] = []
        for index, slide in enumerate(presentation_slides, start=1):
            issues = presentation_visual_issues(state, slide)
            if issues:
                invalid_visual_slides.append(
                    f"slide {index}: " + "; ".join(issues)
                )
        checks.append(
            _check(
                "presentation_visuals",
                "Elementos visuais da apresentação",
                "pass" if presentation_slides and not invalid_visual_slides else "error",
                (
                    "Todos os slides incluem um elemento visual válido (diagrama "
                    "editável, imagem documental ou imagem gerada por IA), com fonte "
                    "e texto alternativo."
                    if presentation_slides and not invalid_visual_slides
                    else "Especificação visual incompleta — "
                    + (" | ".join(invalid_visual_slides) or "não existem slides")
                    + "."
                ),
            )
        )

    resource_outcomes: dict[str, set[str]] = {
        RESOURCE_PRESENTATION: {
            str(item.get("outcome_id", ""))
            for item in resource_data.get("presentation_outline", [])
            if item.get("outcome_id")
        },
        RESOURCE_WORKSHEET: {
            str(outcome_id)
            for section in resource_data.get("lesson_worksheet", {}).get("sections", [])
            for outcome_id in section.get("outcome_ids", [])
        },
        RESOURCE_TEST: {
            str(item.get("outcome_id", ""))
            for item in resource_data.get("test", {}).get("questions", [])
            if item.get("outcome_id")
        },
        RESOURCE_PRACTICAL: {
            str(outcome_id)
            for step in resource_data.get("practical_activity", {}).get("steps", [])
            for outcome_id in step.get("outcome_ids", [])
        },
    }
    for resource_type in requested:
        covered = resource_outcomes.get(resource_type, set())
        coverage_status = (
            "warning"
            if not expected_ids
            else "pass"
            if covered == expected_ids
            else "error"
        )
        checks.append(
            _check(
                "coverage_" + _normalise(resource_type).replace(" ", "_"),
                f"Resultados cobertos por {resource_type}",
                coverage_status,
                (
                    "Não existem resultados de aprendizagem; a cobertura do recurso não pode ser avaliada."
                    if not expected_ids
                    else "Todos os resultados estão associados ao recurso."
                    if covered == expected_ids
                    else f"Esperados: {sorted(expected_ids)}; cobertos: {sorted(covered)}."
                ),
            )
        )

    if RESOURCE_TEST in requested:
        test_data = resource_data.get("test", {})
        calculated_points = sum(item.get("points", 0) for item in test_data.get("questions", []))
        declared_points = test_data.get("total_points", 0)
        checks.append(
            _check(
                "test_points",
                "Cotação total do teste",
                "pass" if calculated_points == declared_points and declared_points > 0 else "error",
                f"Cotação declarada: {declared_points}; soma das questões: {calculated_points}.",
            )
        )

    if RESOURCE_PRACTICAL in requested:
        criteria = resource_data.get("practical_activity", {}).get("criteria", [])
        total_weight = sum(item.get("weight", 0) for item in criteria)
        checks.append(
            _check(
                "practical_weights",
                "Ponderação da atividade prática",
                "pass" if criteria and total_weight == 100 else "error",
                f"A soma das ponderações é {total_weight}%.",
            )
        )

    for check in checks:
        check.update(_quality_navigation_target(check))

    statuses = Counter(item["status"] for item in checks)
    status = "Requer revisão" if statuses["error"] else "Avisos" if statuses["warning"] else "OK"
    return {
        "status": status,
        "passed": statuses["error"] == 0,
        "summary": {
            "passed": statuses["pass"],
            "warnings": statuses["warning"],
            "errors": statuses["error"],
        },
        "checks": checks,
    }


def attach_quality_report(state: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(resources)
    result["quality"] = evaluate_quality(state, result)
    return result
