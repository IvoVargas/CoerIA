"""Validações pedagógicas determinísticas e independentes do modelo generativo."""

from __future__ import annotations

import unicodedata
import re
from collections import Counter
from copy import deepcopy
from typing import Any

from .ai_modes import ai_mode_alignment_issues
from .curriculum import (
    ASSESSMENT_PURPOSES,
    MAX_OUTCOMES,
    MIN_OUTCOMES,
    has_single_action_verb,
    taxonomy_verb_allowed,
    validate_taxonomy_choice,
)
from .models import (
    RESOURCE_ASSESSMENT_GRID,
    RESOURCE_LESSON_PLAN,
    RESOURCE_LESSON_PRESENTATIONS,
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
)
from .resource_catalog import (
    assessment_scope,
    build_assessment_grid,
    build_lesson_plan,
    lesson_scope,
    slide_outcome_ids,
)
from .relationships import derive_alignment_rows


PRESENTATION_ASSESSMENT_TITLE = "Avaliação da unidade curricular"

_GENERIC_LESSON_SLIDE_TITLES = {
    "objetivo da unidade curricular",
    "conteudos da unidade curricular",
    "metodologia de ensino",
}
_AGENDA_TITLE_TERMS = (
    "agenda",
    "roteiro da aula",
    "plano da aula",
    "percurso da aula",
)
_SYNTHESIS_TITLE_TERMS = (
    "sintese",
    "resumo",
    "conclusao",
    "fecho",
)
_LESSON_TOKEN_STOPWORDS = {
    "aula",
    "alunos",
    "aprendizagem",
    "atividade",
    "atividades",
    "atraves",
    "avaliacao",
    "conteudo",
    "conteudos",
    "devera",
    "deverao",
    "docente",
    "ensino",
    "grupo",
    "inteligencia",
    "resultado",
    "resultados",
    "serao",
    "sobre",
    "utilizacao",
    "utilizar",
}


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def _check(check_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "detail": detail}


def _presentation_slide_text(slide: dict[str, Any]) -> str:
    bullets = slide.get("bullets", [])
    bullet_texts = (
        [str(item) for item in bullets if str(item).strip()]
        if isinstance(bullets, list)
        else []
    )
    return " ".join(
        [
            str(slide.get("title", "")),
            *bullet_texts,
        ]
    ).strip()


def _presentation_slide_signature(slide: dict[str, Any]) -> str:
    return " ".join(_normalise(_presentation_slide_text(slide)).split())


def _lesson_content_slides(
    slides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    assessment_title = _normalise(PRESENTATION_ASSESSMENT_TITLE)
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict) or index == 0:
            continue
        title = _normalise(str(slide.get("title", "")))
        if title.startswith(assessment_title):
            continue
        if any(term in title for term in _AGENDA_TITLE_TERMS):
            continue
        if any(term in title for term in _SYNTHESIS_TITLE_TERMS):
            continue
        content.append(slide)
    return content


def _lesson_keywords(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalise(value))
        if len(token) >= 5 and token not in _LESSON_TOKEN_STOPWORDS
    }


def lesson_presentation_specificity_issues(
    lesson: dict[str, Any],
    slides: list[dict[str, Any]],
) -> list[str]:
    """Valida apenas a estrutura objetiva de uma apresentação de aula."""

    if not slides:
        return ["não existem slides"]

    issues: list[str] = []
    titles = [
        _normalise(str(slide.get("title", "")))
        for slide in slides
        if isinstance(slide, dict)
    ]
    if not any(
        any(term in title for term in _AGENDA_TITLE_TERMS)
        for title in titles
    ):
        issues.append("falta uma agenda específica da aula")
    if not any(
        any(term in title for term in _SYNTHESIS_TITLE_TERMS)
        for title in titles
    ):
        issues.append("falta uma síntese ou fecho específico da aula")

    content_slides = _lesson_content_slides(slides)
    if len(content_slides) < 2:
        issues.append(
            "são necessários pelo menos dois slides de desenvolvimento "
            "específico (explicação e prática da aula)"
        )

    return issues


def lesson_presentation_specificity_warnings(
    lesson: dict[str, Any],
    slides: list[dict[str, Any]],
) -> list[str]:
    """Assinala heurísticas úteis sem as transformar em erros bloqueantes."""

    if not slides:
        return []

    warnings: list[str] = []
    lesson_number = int(lesson.get("lesson_number", 0) or 0)
    first_title = _normalise(str(slides[0].get("title", "")))
    lesson_marker = re.compile(rf"\b(?:aula|sessao)\s*0*{lesson_number}\b")
    if lesson_number > 0 and not lesson_marker.search(first_title):
        warnings.append(
            f'o primeiro slide não identifica claramente a aula ou sessão {lesson_number}'
        )

    generic_titles = sorted(
        {
            str(slide.get("title", "")).strip()
            for slide in slides
            if isinstance(slide, dict)
            and _normalise(str(slide.get("title", "")))
            in _GENERIC_LESSON_SLIDE_TITLES
        }
    )
    if generic_titles:
        warnings.append(
            "contém títulos habitualmente globais da unidade curricular: "
            + ", ".join(generic_titles)
        )

    notes = str(lesson.get("notes", "")).strip()
    note_keywords = _lesson_keywords(notes)
    content_slides = _lesson_content_slides(slides)
    content_keywords = _lesson_keywords(
        " ".join(_presentation_slide_text(slide) for slide in content_slides)
    )
    if note_keywords and not note_keywords.intersection(content_keywords):
        warnings.append(
            "não foi possível confirmar por correspondência lexical o tema das notas da aula"
        )
    return warnings


def lesson_presentation_repetition_issues(
    lesson_presentations: list[dict[str, Any]],
) -> list[str]:
    """Deteta repetição substantiva entre apresentações de aulas diferentes."""

    issues: list[str] = []
    prepared: list[tuple[int, dict[str, str]]] = []
    assessment_title = _normalise(PRESENTATION_ASSESSMENT_TITLE)
    for item in lesson_presentations:
        lesson_number = int(item.get("lesson_number", 0) or 0)
        signatures: dict[str, str] = {}
        for index, slide in enumerate(item.get("presentation_outline", [])):
            if not isinstance(slide, dict) or index == 0:
                continue
            title = str(slide.get("title", "")).strip()
            if _normalise(title).startswith(assessment_title):
                continue
            # Um RA pode legitimamente ser desenvolvido em mais do que uma aula.
            # A repetição problemática é a de secções globais, sem ligação a
            # resultados concretos (objetivos da UC, metodologia, sínteses genéricas).
            if slide_outcome_ids(slide):
                continue
            signature = _presentation_slide_signature(slide)
            if signature:
                signatures.setdefault(signature, title or f"slide {index + 1}")
        prepared.append((lesson_number, signatures))

    for index, (lesson_number, signatures) in enumerate(prepared):
        for peer_number, peer_signatures in prepared[index + 1 :]:
            repeated = sorted(set(signatures).intersection(peer_signatures))
            if len(repeated) < 2:
                continue
            repeated_titles = [signatures[signature] for signature in repeated]
            issues.append(
                f"Aulas {lesson_number} e {peer_number}: repetem "
                f"{len(repeated)} slides ("
                + ", ".join(repeated_titles[:4])
                + ("…" if len(repeated_titles) > 4 else "")
                + ")"
            )
    if len(issues) > 5:
        return [
            *issues[:5],
            f"{len(issues) - 5} outros pares de aulas repetem secções globais",
        ]
    return issues


def lesson_presentation_general_overlap_issues(
    general_slides: list[dict[str, Any]],
    lesson_presentations: list[dict[str, Any]],
) -> list[str]:
    """Assinala sobreposição literal entre o PPT geral e os PPT das aulas."""

    def unscoped_signatures(slides: list[dict[str, Any]]) -> dict[str, str]:
        signatures: dict[str, str] = {}
        assessment_title = _normalise(PRESENTATION_ASSESSMENT_TITLE)
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict) or index == 0:
                continue
            title = str(slide.get("title", "")).strip()
            if _normalise(title).startswith(assessment_title):
                continue
            if slide_outcome_ids(slide):
                continue
            signature = _presentation_slide_signature(slide)
            if signature:
                signatures.setdefault(signature, title or f"slide {index + 1}")
        return signatures

    general = unscoped_signatures(general_slides)
    if not general:
        return []
    issues: list[str] = []
    for item in lesson_presentations:
        lesson_number = int(item.get("lesson_number", 0) or 0)
        current = unscoped_signatures(item.get("presentation_outline", []))
        repeated = sorted(set(general).intersection(current))
        if len(repeated) < 2:
            continue
        titles = [general[signature] for signature in repeated]
        issues.append(
            f"Aula {lesson_number}: repete {len(repeated)} slides do PPT geral ("
            + ", ".join(titles[:4])
            + ("…" if len(titles) > 4 else "")
            + ")"
        )
    return issues


def presentation_assessment_overview_issues(
    state: dict[str, Any],
    slides: list[dict[str, Any]],
) -> list[str]:
    """Valida a secção da apresentação dedicada às tarefas de avaliação."""

    expected_ids = {
        str(item.get("id", "")).strip().upper()
        for item in state.get("assessment_activities", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    if not expected_ids:
        return [
            "não existem tarefas de avaliação aprovadas para apresentar"
        ]

    normalized_title = _normalise(PRESENTATION_ASSESSMENT_TITLE)
    overview_slides = [
        slide
        for slide in slides
        if isinstance(slide, dict)
        and _normalise(str(slide.get("title", ""))).startswith(normalized_title)
    ]
    if not overview_slides:
        return [
            f'nenhum slide com o título «{PRESENTATION_ASSESSMENT_TITLE}»'
        ]

    overview_text = " ".join(
        text
        for slide in overview_slides
        for text in [
            str(slide.get("title", "")),
            *[
                str(item)
                for item in slide.get("bullets", [])
                if str(item).strip()
            ],
        ]
    )
    received_ids = {
        identifier.upper()
        for identifier in re.findall(
            r"\bTA[1-9][0-9]*\b",
            overview_text,
            flags=re.IGNORECASE,
        )
    }
    issues: list[str] = []
    missing = sorted(expected_ids - received_ids)
    unknown = sorted(received_ids - expected_ids)
    if missing:
        issues.append("tarefas em falta: " + ", ".join(missing))
    if unknown:
        issues.append("tarefas desconhecidas: " + ", ".join(unknown))
    return issues


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
    elif check_id == "lesson_plan_freshness":
        target_stage = "pedagogical_design"
        target_key = "__stage__"
    elif check_id == "assessment_coverage":
        target_stage = "assessment_activities"
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
        target_stage = "assessment_activities"
        references = re.findall(r"\bRA\d+\b", detail, flags=re.IGNORECASE)
        target_key = references[0].upper() if references else "__stage__"
    elif check_id == "ai_mode_alignment":
        lesson = re.search(r"\bAula\s+(\d+)\b", detail, flags=re.IGNORECASE)
        assessment = re.search(r"\bTA\d+\b", detail, flags=re.IGNORECASE)
        teaching = re.search(r"\bAE\d+\b", detail, flags=re.IGNORECASE)
        outcome = re.search(r"\bRA\d+\b", detail, flags=re.IGNORECASE)
        if lesson:
            target_stage = "pedagogical_design"
            target_key = f"LESSON:{lesson.group(1)}"
        elif assessment:
            target_stage = "assessment_activities"
            target_key = assessment.group(0).upper()
        elif teaching:
            target_stage = "teaching_activities"
            target_key = teaching.group(0).upper()
        else:
            target_stage = "learning_outcomes"
            target_key = outcome.group(0).upper() if outcome else "__stage__"
    elif check_id in {
        "presentation_visuals",
        "presentation_assessment_overview",
        "lesson_presentation_specificity",
        "lesson_presentation_identity",
        "lesson_presentation_overlap",
    }:
        slides = re.findall(r"\bslide\s+(\d+)\b", detail, flags=re.IGNORECASE)
        target_key = (
            f"SLIDE:{slides[0]}"
            if slides
            else "RESOURCE:lesson-presentations"
            if check_id in {
                "lesson_presentation_specificity",
                "lesson_presentation_identity",
                "lesson_presentation_overlap",
            }
            else "RESOURCE:presentation"
        )
    elif "nao selecionado" in _normalise(detail):
        target_key = "__stage__"
    elif "apresentacao_powerpoint" in check_id:
        target_key = "RESOURCE:presentation"
    elif "apresentacoes_das_aulas" in check_id or check_id == "lesson_presentations":
        target_key = "RESOURCE:lesson-presentations"
    elif "plano_de_aulas" in check_id:
        target_key = "RESOURCE:lesson-plan"
    elif "grelha_de_avaliacao" in check_id:
        target_key = "RESOURCE:assessment-grid"
    elif "ficha_de_aula" in check_id:
        target_key = "RESOURCE:worksheet"
    elif "atividade_pratica" in check_id or check_id == "practical_weights":
        target_key = "RESOURCE:practical"
    elif "teste" in check_id or check_id == "test_points":
        target_key = "RESOURCE:tests"
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
        for identifier in item.get("outcome_ids", [])
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


def assessment_teaching_alignment_issues(
    state: dict[str, Any],
    assessments: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Deteta ligações TA→AE ausentes ou desconhecidas."""

    teaching_by_id = {
        str(item.get("id", "")): item
        for item in state.get("teaching_activities", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    rows = assessments if assessments is not None else state.get(
        "assessment_activities", []
    )
    issues: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            issues.append("Tarefa de avaliação com estrutura inválida")
            continue
        task_id = str(item.get("id", "?")) or "?"
        raw_links = item.get("teaching_activity_ids", [])
        linked_ids = list(
            dict.fromkeys(
                str(identifier)
                for identifier in raw_links
                if str(identifier).strip()
            )
        ) if isinstance(raw_links, list) else []
        if not linked_ids:
            issues.append(
                f"{task_id}: sem atividades de ensino-aprendizagem associadas"
            )
            continue
        unknown = [identifier for identifier in linked_ids if identifier not in teaching_by_id]
        if unknown:
            issues.append(
                f"{task_id}: atividades desconhecidas: {', '.join(unknown)}"
            )
    return issues


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
    alignment_rows = derive_alignment_rows(state)

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

    ai_mode_issues = ai_mode_alignment_issues(state)
    ai_mode_chain_complete = bool(
        outcomes
        and state.get("teaching_activities")
        and state.get("assessment_activities")
    )
    checks.append(
        _check(
            "ai_mode_alignment",
            "Alinhamento dos modos de utilização da IA",
            (
                "warning"
                if not ai_mode_chain_complete
                else "error"
                if ai_mode_issues
                else "pass"
            ),
            (
                "A cadeia RA–AE–TA está incompleta; os modos de IA não podem ser avaliados."
                if not ai_mode_chain_complete
                else "; ".join(ai_mode_issues)
                if ai_mode_issues
                else (
                    "AI-off, AI-on e on-AI mantêm-se coerentes entre resultados, "
                    "atividades de ensino-aprendizagem e avaliação."
                )
            ),
        )
    )

    uncovered_assessment_outcomes = [
        str(row.get("outcome_id", "?"))
        for row in alignment_rows
        if not row.get("assessment_ids")
    ]
    checks.append(
        _check(
            "assessment_coverage",
            "Cobertura das atividades de avaliação",
            (
                "warning"
                if not expected_ids
                else "error"
                if uncovered_assessment_outcomes
                else "pass"
            ),
            (
                "Não existem resultados de aprendizagem; a cobertura não pode ser avaliada."
                if not expected_ids
                else "Resultados sem ligação direta a uma tarefa de avaliação: "
                + ", ".join(uncovered_assessment_outcomes)
                if uncovered_assessment_outcomes
                else (
                    "Todos os resultados têm uma ligação direta a uma tarefa de avaliação."
                )
            ),
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
    assessment_rows = state.get("assessment_activities", [])
    assessment_teaching_issues = assessment_teaching_alignment_issues(state)
    checks.append(
        _check(
            "assessment_teaching_alignment",
            "Ligação entre ensino-aprendizagem e avaliação",
            (
                "warning"
                if not assessment_rows
                else "error"
                if assessment_teaching_issues
                else "pass"
            ),
            (
                "Não existem tarefas de avaliação; a ligação às atividades de "
                "ensino-aprendizagem não pode ser avaliada."
                if not assessment_rows
                else "; ".join(assessment_teaching_issues)
                if assessment_teaching_issues
                else (
                    "Cada tarefa de avaliação está associada às atividades de "
                    "ensino-aprendizagem que preparam os respetivos resultados."
                )
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
        elif row.get("status") != "Coerente":
            incomplete_alignment.append(
                f"{row.get('outcome_id', '?')}: {row.get('rationale', 'ligações incoerentes')}"
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
                    "Todos os resultados estão ligados a conteúdo e atividades; a ligação "
                    "direta à avaliação é coerente com as atividades de ensino-aprendizagem."
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
        RESOURCE_LESSON_PRESENTATIONS: bool(
            resource_data.get("lesson_presentations")
        ),
        RESOURCE_WORKSHEET: bool(resource_data.get("lesson_worksheet", {}).get("sections")),
        RESOURCE_TEST: bool(
            resource_data.get("test", {}).get("questions")
            if state.get("resource_generation_scope") == RESOURCE_TEST
            else resource_data.get("tests")
        ),
        RESOURCE_PRACTICAL: bool(resource_data.get("practical_activity", {}).get("steps")),
        RESOURCE_LESSON_PLAN: bool(resource_data.get("lesson_plan", {}).get("lessons")),
        RESOURCE_ASSESSMENT_GRID: bool(
            resource_data.get("assessment_grid", {}).get("rows")
        ),
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

        assessment_overview_issues = presentation_assessment_overview_issues(
            state,
            presentation_slides,
        )
        checks.append(
            _check(
                "presentation_assessment_overview",
                "Avaliação apresentada nos slides",
                "pass" if not assessment_overview_issues else "error",
                (
                    "A secção de avaliação apresenta todas as tarefas e critérios "
                    "aprovados."
                    if not assessment_overview_issues
                    else "Secção de avaliação incompleta — "
                    + "; ".join(assessment_overview_issues)
                    + "."
                ),
            )
        )

        item_scope = state.get("resource_item_scope", {})
        if isinstance(item_scope, dict) and item_scope.get("kind") == "lesson":
            specificity_issues = lesson_presentation_specificity_issues(
                item_scope,
                presentation_slides,
            )
            specificity_warnings = lesson_presentation_specificity_warnings(
                item_scope,
                presentation_slides,
            )
            peer_presentations = state.get("lesson_presentation_peers", [])
            if isinstance(peer_presentations, list) and peer_presentations:
                specificity_issues.extend(
                    lesson_presentation_repetition_issues(
                        [
                            *[
                                item
                                for item in peer_presentations
                                if isinstance(item, dict)
                            ],
                            {
                                "lesson_number": item_scope.get("lesson_number", 0),
                                "presentation_outline": presentation_slides,
                            },
                        ]
                    )
                )
            general_peer = state.get("general_presentation_peer", [])
            if isinstance(general_peer, list) and general_peer:
                specificity_warnings.extend(
                    lesson_presentation_general_overlap_issues(
                        general_peer,
                        [
                            {
                                "lesson_number": item_scope.get("lesson_number", 0),
                                "presentation_outline": presentation_slides,
                            }
                        ],
                    )
                )
            checks.append(
                _check(
                    "lesson_presentation_specificity",
                    "Especificidade da apresentação da aula",
                    "pass" if not specificity_issues else "error",
                    (
                        "A apresentação desenvolve o tema, a atividade e o fecho "
                        "específicos desta aula."
                        if not specificity_issues
                        else "; ".join(specificity_issues)
                    ),
                )
            )
            checks.append(
                _check(
                    "lesson_presentation_identity",
                    "Identificação e diferenciação da apresentação da aula",
                    "warning" if specificity_warnings else "pass",
                    (
                        "; ".join(specificity_warnings)
                        if specificity_warnings
                        else "O título e o vocabulário distinguem esta apresentação."
                    ),
                )
            )

    if RESOURCE_LESSON_PLAN in requested:
        current_plan = resource_data.get("lesson_plan", {})
        expected_plan = build_lesson_plan(state)
        checks.append(
            _check(
                "lesson_plan_freshness",
                "Atualidade do plano de aulas",
                "pass" if current_plan == expected_plan else "error",
                (
                    "O plano reproduz exatamente o planeamento de aulas aprovado."
                    if current_plan == expected_plan
                    else "O plano deve ser atualizado a partir do planeamento de aulas atual."
                ),
            )
        )
    if RESOURCE_ASSESSMENT_GRID in requested:
        current_grid = resource_data.get("assessment_grid", {})
        expected_grid = build_assessment_grid(state)
        checks.append(
            _check(
                "assessment_grid_freshness",
                "Atualidade da grelha de avaliação",
                "pass" if current_grid == expected_grid else "error",
                (
                    "A grelha reproduz exatamente as tarefas e ligações aprovadas."
                    if current_grid == expected_grid
                    else "A grelha deve ser atualizada a partir das tarefas de avaliação atuais."
                ),
            )
        )

    if RESOURCE_LESSON_PRESENTATIONS in requested:
        lesson_presentations = resource_data.get("lesson_presentations", [])
        expected_lessons = set(
            state.get("resource_scopes", {}).get("lesson_presentations", [])
        )
        received_lessons = {
            int(item.get("lesson_number", 0) or 0)
            for item in lesson_presentations
            if isinstance(item, dict)
        }
        collection_issues: list[str] = []
        collection_warnings: list[str] = []
        if len(received_lessons) != len(lesson_presentations):
            collection_issues.append(
                "cada aula deve ter exatamente uma apresentação"
            )
        if received_lessons != expected_lessons:
            collection_issues.append(
                f"aulas esperadas: {sorted(expected_lessons)}; recebidas: {sorted(received_lessons)}"
            )
        for item in lesson_presentations:
            lesson_number = int(item.get("lesson_number", 0) or 0)
            slides = item.get("presentation_outline", [])
            slide_issues = [
                f"slide {index}: " + "; ".join(presentation_visual_issues(state, slide))
                for index, slide in enumerate(slides, start=1)
                if presentation_visual_issues(state, slide)
            ]
            try:
                current_scope = lesson_scope(state, lesson_number)
                scoped_state = {**state, **current_scope}
            except ValueError as error:
                collection_issues.append(str(error))
                continue
            assessment_issues = presentation_assessment_overview_issues(
                scoped_state,
                slides,
            )
            specificity_issues = lesson_presentation_specificity_issues(
                current_scope,
                slides,
            )
            specificity_warnings = lesson_presentation_specificity_warnings(
                current_scope,
                slides,
            )
            expected_scope = set(current_scope.get("outcome_ids", []))
            declared_scope = set(item.get("outcome_ids", []))
            declared_slide_ids = {
                outcome_id
                for slide in slides
                if isinstance(slide, dict)
                for outcome_id in slide_outcome_ids(slide)
            }
            covered_scope = declared_slide_ids & expected_scope
            unexpected_scope = declared_slide_ids - expected_scope
            if slide_issues:
                collection_issues.append(
                    f"Aula {lesson_number}: " + " | ".join(slide_issues)
                )
            if assessment_issues:
                collection_issues.append(
                    f"Aula {lesson_number}: " + "; ".join(assessment_issues)
                )
            if specificity_issues:
                collection_issues.append(
                    f"Aula {lesson_number}: " + "; ".join(specificity_issues)
                )
            if specificity_warnings:
                collection_warnings.append(
                    f"Aula {lesson_number}: " + "; ".join(specificity_warnings)
                )
            if covered_scope != expected_scope:
                collection_issues.append(
                    f"Aula {lesson_number}: esperados {sorted(expected_scope)}; "
                    f"cobertos {sorted(covered_scope)}"
                )
            if unexpected_scope:
                collection_issues.append(
                    f"Aula {lesson_number}: IDs não permitidos "
                    f"{sorted(unexpected_scope)}"
                )
            if declared_scope != expected_scope:
                collection_issues.append(
                    f"Aula {lesson_number}: âmbito declarado {sorted(declared_scope)}; "
                    f"esperado {sorted(expected_scope)}"
                )
        collection_issues.extend(
            lesson_presentation_repetition_issues(lesson_presentations)
        )
        if RESOURCE_PRESENTATION in requested:
            collection_warnings.extend(
                lesson_presentation_general_overlap_issues(
                    resource_data.get("presentation_outline", []),
                    lesson_presentations,
                )
            )
        checks.append(
            _check(
                "lesson_presentations",
                "Apresentações PowerPoint das aulas",
                "pass" if lesson_presentations and not collection_issues else "error",
                (
                    "Todas as apresentações selecionadas respeitam o âmbito das aulas."
                    if lesson_presentations and not collection_issues
                    else "; ".join(collection_issues) or "Não existem apresentações."
                ),
            )
        )
        checks.append(
            _check(
                "lesson_presentation_overlap",
                "Distinção entre o PPT geral e os PPT das aulas",
                "warning" if collection_warnings else "pass",
                (
                    "; ".join(collection_warnings)
                    if collection_warnings
                    else "As apresentações das aulas estão identificadas e não repetem secções do PPT geral."
                ),
            )
        )
    resource_outcomes: dict[str, set[str]] = {
        RESOURCE_PRESENTATION: {
            outcome_id
            for item in resource_data.get("presentation_outline", [])
            if isinstance(item, dict)
            for outcome_id in slide_outcome_ids(item)
        },
        RESOURCE_WORKSHEET: {
            str(outcome_id)
            for section in resource_data.get("lesson_worksheet", {}).get("sections", [])
            for outcome_id in section.get("outcome_ids", [])
        },
        RESOURCE_TEST: {
            str(item.get("outcome_id", ""))
            for test_entry in resource_data.get("tests", [])
            for item in test_entry.get("test", {}).get("questions", [])
            if item.get("outcome_id")
        },
        RESOURCE_PRACTICAL: {
            str(outcome_id)
            for step in resource_data.get("practical_activity", {}).get("steps", [])
            for outcome_id in step.get("outcome_ids", [])
        },
    }
    for resource_type in requested - {
        RESOURCE_LESSON_PLAN,
        RESOURCE_ASSESSMENT_GRID,
        RESOURCE_LESSON_PRESENTATIONS,
        RESOURCE_TEST,
    }:
        covered = resource_outcomes.get(resource_type, set())
        unexpected = covered - expected_ids
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
                    else (
                        f"Esperados: {sorted(expected_ids)}; "
                        f"cobertos: {sorted(covered & expected_ids)}."
                        + (
                            f" IDs não permitidos: {sorted(unexpected)}."
                            if unexpected
                            else ""
                        )
                    )
                ),
            )
        )

    if RESOURCE_TEST in requested:
        if state.get("resource_generation_scope") == RESOURCE_TEST:
            item_scope = state.get("resource_item_scope", {})
            test_entries = [
                {
                    "assessment_task_id": item_scope.get(
                        "assessment_task_id", ""
                    ),
                    "outcome_ids": list(item_scope.get("outcome_ids", [])),
                    "test": resource_data.get("test", {}),
                }
            ]
        else:
            test_entries = resource_data.get("tests", [])
        test_issues: list[str] = []
        expected_tasks = (
            {
                str(
                    state.get("resource_item_scope", {}).get(
                        "assessment_task_id", ""
                    )
                )
            }
            if state.get("resource_generation_scope") == RESOURCE_TEST
            else set(state.get("resource_scopes", {}).get("tests", []))
        )
        expected_tasks.discard("")
        received_tasks = {
            str(item.get("assessment_task_id", ""))
            for item in test_entries
        }
        if len(received_tasks) != len(test_entries):
            test_issues.append("cada tarefa deve ter exatamente um teste")
        if received_tasks != expected_tasks:
            test_issues.append(
                f"tarefas esperadas: {sorted(expected_tasks)}; recebidas: {sorted(received_tasks)}"
            )
        for entry in test_entries:
            task_id = str(entry.get("assessment_task_id", ""))
            test_data = entry.get("test", {})
            calculated_points = sum(
                item.get("points", 0) for item in test_data.get("questions", [])
            )
            declared_points = test_data.get("total_points", 0)
            try:
                current_scope = assessment_scope(state, task_id)
                expected_test_outcomes = set(current_scope.get("outcome_ids", []))
            except ValueError as error:
                test_issues.append(str(error))
                expected_test_outcomes = set()
            declared_test_outcomes = set(entry.get("outcome_ids", []))
            covered_test_outcomes = {
                str(item.get("outcome_id", ""))
                for item in test_data.get("questions", [])
                if str(item.get("outcome_id", "")).strip()
            }
            if calculated_points != declared_points or declared_points <= 0:
                test_issues.append(
                    f"{task_id}: cotação declarada {declared_points}; soma {calculated_points}"
                )
            if covered_test_outcomes != expected_test_outcomes:
                test_issues.append(
                    f"{task_id}: esperados {sorted(expected_test_outcomes)}; "
                    f"cobertos {sorted(covered_test_outcomes)}"
                )
            if declared_test_outcomes != expected_test_outcomes:
                test_issues.append(
                    f"{task_id}: âmbito declarado {sorted(declared_test_outcomes)}; "
                    f"esperado {sorted(expected_test_outcomes)}"
                )
        checks.append(
            _check(
                "test_points",
                "Testes por tarefa de avaliação",
                "pass" if test_entries and not test_issues else "error",
                (
                    "Todos os testes cobrem a respetiva tarefa e apresentam cotação coerente."
                    if test_entries and not test_issues
                    else "; ".join(test_issues) or "Não existem testes."
                ),
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
