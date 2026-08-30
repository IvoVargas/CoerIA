"""Fluxo CoerIA, implementado como grafo de estados LangGraph."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import (
    AgentGenerationError,
    CritiqueResult,
    GenerationResult,
    LocalizedAssistanceAgent,
    PedagogicalAgent,
    PedagogicalCritic,
    RESOURCE_ARTIFACT_FIELDS,
    RuleBasedPedagogicalAgent,
    _canonicalize_presentation_assessment_overview,
    build_localized_assistance_agent,
    build_pedagogical_team,
    validate_artifact,
)
from .branding import config_value
from .curriculum import (
    ASSESSMENT_PURPOSES,
    LESSON_TYPES,
    LEARNING_CONTEXTS,
    OUTCOME_TYPES,
    TAXONOMY_LEVELS,
    TAXONOMY_VERBS,
    normalize_structured_activity_ids,
    normalize_learning_outcome_ids,
    starts_with_objective_action_verb,
    taxonomy_verb_allowed,
    validate_taxonomy_choice,
)
from .models import (
    CourseInput,
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
    validate_resource_types,
)
from .quality import attach_quality_report
from .providers import configured_ai_provider, validate_ai_provider
from .image_generation import enrich_presentation_with_ai_images
from .manual_editing import (
    apply_proposal_review_changes,
    proposal_review_changes,
)
from .relationships import derive_alignment_rows
from .validation_targets import resolve_validation_target


class PrismState(TypedDict, total=False):
    schema_version: int
    orchestration: dict[str, Any]
    session_id: str
    source_input_text: str
    source_original_text: str
    source_images: list[dict[str, Any]]
    source_attachments: list[dict[str, Any]]
    source_reduction: dict[str, Any]
    learning_outcome_assumptions: list[str]
    generated_images: list[dict[str, Any]]
    ai_image_generation_enabled: bool
    ai_provider: str
    course: dict[str, Any]
    feedback: dict[str, str]
    audit: list[dict[str, str]]
    curriculum_analysis: dict[str, Any]
    solo_taxonomy: list[dict[str, Any]]
    learning_outcomes: list[dict[str, Any]]
    assessment_activities: list[dict[str, Any]]
    pedagogical_design: dict[str, Any]
    teaching_activities: list[dict[str, Any]]
    resources: dict[str, Any]
    final_validation: dict[str, Any]
    current_stage: str
    status: str
    review: dict[str, str]
    resource_types: list[str]
    resource_generation_scope: str
    resource_generation_drafts: dict[str, Any]
    versions: dict[str, list[Any]]
    generation_metadata: dict[str, list[dict[str, Any]]]
    version_dependencies: dict[str, list[dict[str, int]]]
    active_versions: dict[str, int]
    stage_statuses: dict[str, str]
    revision_snapshots: list[dict[str, Any]]
    ai_proposals: list[dict[str, Any]]
    ai_reviews: dict[str, list[dict[str, Any]]]
    restored_from_backup: dict[str, str]


STAGE_LABELS = {
    "curriculum_analysis": "Conteúdos curriculares",
    "learning_outcomes": "Formulação dos resultados de aprendizagem",
    "teaching_activities": "Atividades de ensino-aprendizagem",
    "assessment_activities": "Tarefas e critérios de avaliação",
    "pedagogical_design": "Planeamento das aulas",
    "resources": "Geração de recursos educativos",
    "final_validation": "Validação final da estrutura e do alinhamento",
}

STAGE_ORDER = (
    "learning_outcomes",
    "curriculum_analysis",
    "teaching_activities",
    "assessment_activities",
    "pedagogical_design",
    "resources",
    "final_validation",
)

ProgressCallback = Callable[[str], None]


class ResourceGenerationError(AgentGenerationError):
    """Preserva os recursos válidos quando outro tipo falha."""

    def __init__(self, message: str, drafts: dict[str, Any]) -> None:
        super().__init__(message)
        self.drafts = deepcopy(drafts)


def _report_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(message)


SCHEMA_VERSION = 28

MANUAL_FIRST_MODE = "manual-first"
AUTHORING_STAGES = STAGE_ORDER[:-1]

# Uma etapa pode reabrir qualquer etapa já alcançada. A validação dinâmica
# abaixo exclui artefactos que ainda nunca foram gerados para a sessão.
REVISION_TARGETS = {
    stage: STAGE_ORDER[: index + 1]
    for index, stage in enumerate(STAGE_ORDER)
}


def _feedback(state: PrismState, stage: str) -> str:
    return (state.get("feedback", {}).get(stage, "") or "").strip()


def _audit_update(
    state: PrismState, stage: str, message: str, feedback: str = ""
) -> dict[str, list[dict[str, str]]]:
    entry = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "stage": STAGE_LABELS[stage],
        "event": message,
        "feedback": feedback or "—",
    }
    return {"audit": [*state.get("audit", []), entry]}


def _topics(text: str) -> list[str]:
    fragments = re.split(r"[\n.;:]+", text)
    topics: list[str] = []
    for fragment in fragments:
        clean = re.sub(r"\s+", " ", fragment).strip(" -•\t")
        if len(clean) >= 8 and clean.lower() not in {item.lower() for item in topics}:
            topics.append(clean[:100])
        if len(topics) == 6:
            break
    defaults = [
        "Conceitos fundamentais",
        "Métodos e técnicas",
        "Aplicações em contexto",
        "Análise crítica e integração",
    ]
    for default in defaults:
        if len(topics) >= 4:
            break
        if default.casefold() not in {item.casefold() for item in topics}:
            topics.append(default)
    return topics


def _nominal_content_title(value: str) -> str:
    """Converte um eventual enunciado de desempenho numa designação temática."""

    clean = re.sub(r"\s+", " ", str(value or "")).strip(" .;:-")
    if starts_with_objective_action_verb(clean):
        clean = re.sub(r"^[^\wÀ-ÿ]*[\wÀ-ÿ-]+\s*", "", clean).strip(" .;:-")
    if not clean:
        return "Conteúdo curricular"
    return clean[0].upper() + clean[1:]


def _content_scope_description(title: str) -> str:
    topic = str(title or "conteúdo curricular").strip(" .;:-").lower()
    return (
        "Delimitação conceptual, princípios fundamentais, componentes e aplicações "
        f"relativas a {topic}."
    )


def analyse_curriculum(state: PrismState) -> dict[str, Any]:
    course = state["course"]
    outcomes = state.get("learning_outcomes", [])
    topics = [
        _nominal_content_title(
            str(outcome.get("theme", "")).strip()
            or str(outcome.get("statement", "")).strip()
        )
        for outcome in outcomes
    ] or [_nominal_content_title(topic) for topic in _topics(str(course["source_text"]))]
    feedback = _feedback(state, "curriculum_analysis")
    outcome_ids = [str(outcome.get("id", "")) for outcome in outcomes if outcome.get("id")]
    result = {
        "summary": (
            f"Unidade curricular orientada para {course['audience']}, com "
            f"{course['duration_hours']} horas de trabalho previsto."
        ),
        "themes": topics,
        "contents": [
            {
                "id": f"C{index + 1}",
                "title": topic,
                "description": _content_scope_description(topic),
                "outcome_ids": [outcome_ids[index]] if index < len(outcome_ids) else [],
            }
            for index, topic in enumerate(topics)
        ],
        "feedback_considered": feedback or None,
    }
    reduction_sources = [
        str(item.get("source", "")).strip()
        for item in state.get("source_reduction", {}).get("sources", [])
        if str(item.get("source", "")).strip()
    ]
    if state.get("source_reduction", {}).get("applied") and reduction_sources:
        content_ids = [item["id"] for item in result["contents"]]
        result["source_coverage"] = [
            {
                "source": source,
                "contribution": "Fonte considerada na estruturação curricular.",
                "key_concepts": [topics[index % len(topics)]],
                "content_ids": [content_ids[index % len(content_ids)]],
            }
            for index, source in enumerate(reduction_sources)
        ]
    return {
        "curriculum_analysis": result,
        **_audit_update(state, "curriculum_analysis", "Análise curricular produzida.", feedback),
    }


def formulate_learning_outcomes(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "learning_outcomes")
    taxonomy_type = validate_taxonomy_choice(state["course"].get("taxonomy_type", "SOLO"))
    levels = TAXONOMY_LEVELS[taxonomy_type]
    verbs = TAXONOMY_VERBS[taxonomy_type]
    topics = _topics(str(state["course"]["source_text"]))
    outcomes = [
        {
            "id": f"RA{index + 1}",
            "theme": topic,
            "statement": (
                f"{verbs[levels[index % len(levels)]][0].capitalize()} "
                f"{topic.lower()}."
            ),
            "action_verb": verbs[levels[index % len(levels)]][0],
            "taxonomy_level": levels[index % len(levels)],
            "outcome_type": OUTCOME_TYPES[index % len(OUTCOME_TYPES)],
        }
        for index, topic in enumerate(topics)
    ]
    return {
        "learning_outcomes": outcomes,
        **_audit_update(
            state,
            "learning_outcomes",
            "Resultados de aprendizagem formulados.",
            feedback,
        ),
    }


def propose_assessment_activities(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "assessment_activities")
    taxonomy_type = validate_taxonomy_choice(
        state["course"].get("taxonomy_type", "SOLO")
    )
    assessments = []
    for index, outcome in enumerate(state["learning_outcomes"]):
        outcome_ids = [
            outcome["id"],
            *(
                [state["learning_outcomes"][index + 1]["id"]]
                if index % 2 == 0 and index + 1 < len(state["learning_outcomes"])
                else []
            ),
        ]
        teaching_activity_ids = [
            str(activity.get("id", ""))
            for activity in state.get("teaching_activities", [])
            if str(activity.get("id", "")).strip()
            and set(activity.get("outcome_ids") or [activity.get("outcome_id")])
            & set(outcome_ids)
        ]
        assessments.append({
            "id": f"TA{index + 1}",
            "teaching_activity_ids": teaching_activity_ids,
            "outcome_ids": outcome_ids,
            "work_type": "Trabalho individual" if index % 2 == 0 else "Trabalho de grupo",
            "assessment_purpose": ASSESSMENT_PURPOSES[index % len(ASSESSMENT_PURPOSES)],
            "activity": f"Tarefa aplicada: {outcome['statement']}",
            "evidence": (
                "Produto ou desempenho que demonstra: "
                f"{outcome['statement']}"
            ),
            "criterion": (
                "Domínio demonstrado ao nível "
                f"{outcome['taxonomy_level']} da Taxonomia {taxonomy_type}."
            ),
        })
    return {
        "assessment_activities": assessments,
        **_audit_update(
            state,
            "assessment_activities",
            "Atividades e critérios de avaliação propostos.",
            feedback,
        ),
    }


def create_pedagogical_design(state: PrismState) -> dict[str, Any]:
    course = state["course"]
    outcomes = state.get("learning_outcomes", [])
    contact_minutes = max(
        len(outcomes),
        round(float(course.get("contact_hours", 0) or 0) * 60),
    )
    base_duration, extra_minutes = divmod(
        contact_minutes,
        max(len(outcomes), 1),
    )
    design = {
        "lessons": [
            {
                "duration_minutes": base_duration + (1 if index < extra_minutes else 0),
                "session_type": LESSON_TYPES[1],
                "component_ids": [
                    *[
                        str(item.get("id", ""))
                        for item in state.get("teaching_activities", [])
                        if outcome["id"]
                        in (item.get("outcome_ids") or [item.get("outcome_id")])
                    ],
                    *[
                        str(item.get("id", ""))
                        for item in state.get("assessment_activities", [])
                        if outcome["id"] in item.get("outcome_ids", [])
                    ],
                ],
                "notes": outcome["statement"],
            }
            for index, outcome in enumerate(outcomes)
        ],
    }
    return {
        "pedagogical_design": design,
        **_audit_update(
            state,
            "pedagogical_design",
            "Aulas planeadas.",
            _feedback(state, "pedagogical_design"),
        ),
    }


def propose_teaching_activities(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "teaching_activities")
    activities = [
        {
            "id": f"AE{index + 1}",
            "outcome_id": outcome["id"],
            "outcome_ids": [outcome["id"]],
            "learning_context": LEARNING_CONTEXTS[index % len(LEARNING_CONTEXTS)],
            "activity": f"Exploração orientada e discussão sobre {outcome['statement'].split(' de ', 1)[-1]}",
            "method": "Aprendizagem ativa com feedback formativo.",
            "practice": "Aplicação orientada do resultado em tarefa progressiva.",
            "support": "Acompanhamento do docente com questões orientadoras.",
            "feedback_strategy": "Feedback formativo específico antes da avaliação sumativa.",
        }
        for index, outcome in enumerate(state["learning_outcomes"])
    ]
    return {
        "teaching_activities": activities,
        **_audit_update(
            state,
            "teaching_activities",
            "Atividades de ensino-aprendizagem propostas.",
            feedback,
        ),
    }


def generate_resources(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "resources")
    course = state["course"]
    selected_types = state.get("resource_types", [RESOURCE_PRESENTATION])
    taxonomy_type = validate_taxonomy_choice(course.get("taxonomy_type", "SOLO"))
    def assessment_for(outcome_id: str) -> dict[str, Any]:
        assessment = next(
            (
                item
                for item in state.get("assessment_activities", [])
                if outcome_id in item.get("outcome_ids", [])
            ),
            None,
        )
        if assessment is None:
            raise ValueError(
                f"O resultado {outcome_id} não tem uma tarefa de avaliação diretamente ligada."
            )
        return assessment

    def teaching_for(outcome_id: str) -> dict[str, Any]:
        return next(
            item
            for item in state["teaching_activities"]
            if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
        )
    slides = [
        {
            "title": course["unit_name"],
            "bullets": [
                f"Público: {course['audience']}",
                f"Duração: {course['duration_hours']} horas",
                f"Estrutura alinhada com a Taxonomia {taxonomy_type}.",
            ],
            "outcome_id": "",
            "visual_mode": "diagrama",
            "visual_asset_id": "",
            "visual_prompt": "",
            "visual_kind": "capa",
            "visual_title": "Percurso da unidade curricular",
            "visual_items": [
                f"Taxonomia {taxonomy_type}",
                "Programa da UC",
                "Recursos alinhados",
            ],
            "visual_source": "Diagrama nativo gerado pelo CoerIA a partir da estrutura aprovada.",
            "alt_text": (
                "Percurso entre a taxonomia selecionada, o programa da unidade "
                "curricular e os recursos educativos alinhados."
            ),
        }
    ]
    for index, outcome in enumerate(state["learning_outcomes"]):
        theme = outcome["theme"]
        slides.append(
            {
                "title": f"{outcome['id']} — {theme}",
                "bullets": [
                    outcome["statement"],
                    teaching_for(outcome["id"])["activity"],
                    assessment_for(outcome["id"])["criterion"],
                ],
                "outcome_id": outcome["id"],
                "visual_mode": "diagrama",
                "visual_asset_id": "",
                "visual_prompt": "",
                "visual_kind": ("processo", "conceito", "comparacao")[index % 3],
                "visual_title": f"Como trabalhar {outcome['id']}",
                "visual_items": [
                    theme,
                    teaching_for(outcome["id"])["method"],
                    assessment_for(outcome["id"])["assessment_purpose"],
                ],
                "visual_source": "Diagrama nativo gerado pelo CoerIA a partir dos artefactos aprovados.",
                "alt_text": (
                    f"Diagrama que relaciona o tema {theme}, a atividade de aprendizagem "
                    f"e a avaliação associadas ao resultado {outcome['id']}."
                ),
            }
        )
    slides.append(
        {
            "title": "Síntese e próximos passos",
            "bullets": [
                "Rever os resultados e respetivo alinhamento.",
                "Adaptar exemplos ao contexto da turma.",
                "Registar feedback para uma futura reformulação.",
            ],
            "outcome_id": "",
            "visual_mode": "diagrama",
            "visual_asset_id": "",
            "visual_prompt": "",
            "visual_kind": "sintese",
            "visual_title": "Ciclo de melhoria docente",
            "visual_items": ["Rever", "Adaptar", "Registar feedback"],
            "visual_source": "Diagrama nativo gerado pelo CoerIA.",
            "alt_text": "Ciclo final de revisão, adaptação e registo de feedback.",
        }
    )
    worksheet = {
        "title": f"Ficha de aula — {course['unit_name']}",
        "overview": (
            "Ficha orientada pelos resultados de aprendizagem e pela progressão "
            f"da Taxonomia {taxonomy_type}."
        ),
        "instructions": "Realize as atividades pela ordem apresentada e fundamente as respostas.",
        "sections": [
            {
                "heading": f"{outcome['id']} — {outcome['theme']}",
                "content": outcome["statement"],
                "outcome_ids": [outcome["id"]],
                "activity": teaching_for(outcome["id"])["activity"],
            }
            for index, outcome in enumerate(state["learning_outcomes"])
        ],
    }
    test_questions = [
        {
            "id": f"Q{index + 1}",
            "outcome_id": outcome["id"],
            "prompt": assessment_for(outcome["id"])["activity"],
            "question_type": "Resposta estruturada",
            "points": 10,
            "answer_key": assessment_for(outcome["id"])["criterion"],
        }
        for index, outcome in enumerate(state["learning_outcomes"])
    ]
    test = {
        "title": f"Teste — {course['unit_name']}",
        "instructions": "Responda de forma clara e apresente a fundamentação solicitada.",
        "total_points": sum(item["points"] for item in test_questions),
        "questions": test_questions,
    }
    practical = {
        "title": f"Atividade prática — {course['unit_name']}",
        "context": "Aplicação integrada dos resultados de aprendizagem da unidade.",
        "duration_minutes": max(60, int(course["duration_hours"]) * 15),
        "materials": ["Conteúdos fornecidos pelo docente", "Ferramentas adequadas ao contexto"],
        "steps": [
            {
                "order": index + 1,
                "instruction": teaching_for(outcome["id"])["activity"],
                "outcome_ids": [outcome["id"]],
            }
            for index, outcome in enumerate(state["learning_outcomes"])
        ],
        "deliverables": ["Produto final", "Justificação das decisões tomadas"],
        "criteria": [
            {
                "criterion": "Alinhamento com os resultados",
                "description": "O trabalho demonstra os desempenhos previstos.",
                "weight": 50,
            },
            {
                "criterion": "Qualidade e fundamentação",
                "description": "As decisões são claras, corretas e justificadas.",
                "weight": 50,
            },
        ],
    }
    resources = {
        "selected_types": selected_types,
        "presentation_outline": slides if RESOURCE_PRESENTATION in selected_types else [],
        "lesson_worksheet": worksheet if RESOURCE_WORKSHEET in selected_types else {
            "title": "", "overview": "", "instructions": "", "sections": []
        },
        "test": test if RESOURCE_TEST in selected_types else {
            "title": "", "instructions": "", "total_points": 0, "questions": []
        },
        "practical_activity": practical if RESOURCE_PRACTICAL in selected_types else {
            "title": "", "context": "", "duration_minutes": 0, "materials": [],
            "steps": [], "deliverables": [], "criteria": []
        },
        "feedback_considered": feedback or None,
    }
    resources, _ = _canonicalize_presentation_assessment_overview(
        resources,
        state,
    )
    return {
        "resources": resources,
        **_audit_update(
            state,
            "resources",
            "Recursos educativos e verificação automática de qualidade gerados.",
            feedback,
        ),
    }


def is_manual_first(state: PrismState) -> bool:
    """Indica se a sessão usa autoria manual com IA facultativa."""

    return state.get("orchestration", {}).get("mode") == MANUAL_FIRST_MODE


def blank_artifact(stage: str, state: PrismState) -> Any:
    """Cria apenas a estrutura editável de uma etapa, sem conteúdo pedagógico de IA."""

    if stage == "learning_outcomes":
        return []
    if stage == "curriculum_analysis":
        return {
            "summary": "",
            "themes": [],
            "contents": [],
        }
    if stage == "assessment_activities":
        return []
    if stage == "pedagogical_design":
        return {"lessons": []}
    if stage == "teaching_activities":
        return []
    if stage == "resources":
        return {
            "selected_types": list(state.get("resource_types", [])),
            "presentation_outline": [],
            "lesson_worksheet": {
                "title": "",
                "overview": "",
                "instructions": "",
                "sections": [],
            },
            "test": {
                "title": "",
                "instructions": "",
                "total_points": 0,
                "questions": [],
            },
            "practical_activity": {
                "title": "",
                "context": "",
                "duration_minutes": 0,
                "materials": [],
                "steps": [],
                "deliverables": [],
                "criteria": [],
            },
            "feedback_considered": None,
            "quality": {
                "status": "Não calculada",
                "passed": False,
                "summary": {"passed": 0, "warnings": 0, "errors": 0},
                "checks": [],
            },
        }
    raise ValueError("A etapa selecionada não possui um artefacto editável.")


def ensure_manual_artifacts(state: PrismState) -> PrismState:
    """Completa estruturas ausentes numa sessão manual sem substituir dados existentes."""

    for stage in AUTHORING_STAGES:
        if stage not in state:
            state[stage] = blank_artifact(stage, state)
    state["learning_outcome_assumptions"] = _clean_learning_outcome_assumptions(
        state.get("learning_outcome_assumptions", [])
    )
    state.setdefault("ai_proposals", [])
    state.setdefault("ai_reviews", {})
    return state


def update_initial_context(
    state: PrismState,
    course: CourseInput,
    *,
    ai_provider: str,
    source_input_text: str,
    source_original_text: str,
    source_reduction: dict[str, Any],
    source_images: list[dict[str, Any]],
) -> PrismState:
    """Atualiza a configuração inicial sem eliminar artefactos já produzidos."""

    if state.get("status") == "completed":
        raise ValueError(
            "A sessão concluída está em modo de consulta. Reabra-a explicitamente "
            "antes de alterar os dados iniciais."
        )
    updated = ensure_manual_artifacts(deepcopy(state))
    previous_course = deepcopy(updated.get("course", {}))
    previous_provider = str(updated.get("ai_provider", ""))
    previous_source_input = str(updated.get("source_input_text", ""))
    previous_source_original = str(updated.get("source_original_text", ""))
    previous_source_images = deepcopy(updated.get("source_images", []))

    updated["course"] = course.to_dict()
    updated["ai_provider"] = validate_ai_provider(ai_provider)
    updated["source_input_text"] = source_input_text.strip()
    updated["source_original_text"] = source_original_text.strip()
    updated["source_reduction"] = deepcopy(source_reduction)
    updated["source_images"] = deepcopy(source_images)

    course_changed = previous_course != updated["course"]
    sources_changed = (
        previous_source_input != updated["source_input_text"]
        or previous_source_original != updated["source_original_text"]
        or previous_source_images != updated["source_images"]
    )
    provider_changed = previous_provider != updated["ai_provider"]
    if not any((course_changed, sources_changed, provider_changed)):
        raise ValueError("Não foram detetadas alterações nos dados iniciais.")

    changed_labels: list[str] = []
    if course_changed:
        changed_labels.append("caracterização da unidade curricular")
    if sources_changed:
        changed_labels.append("texto de base ou fontes")
    if provider_changed:
        changed_labels.append("fornecedor de IA")

    if course_changed or sources_changed:
        statuses = dict(updated.get("stage_statuses", {}))
        for stage in AUTHORING_STAGES:
            statuses[stage] = (
                "needs_review" if artifact_has_content(updated.get(stage)) else "empty"
            )
        statuses["final_validation"] = "pending"
        updated["stage_statuses"] = statuses
        updated.pop("final_validation", None)
        updated.get("active_versions", {}).pop("final_validation", None)
        if updated.get("current_stage") not in AUTHORING_STAGES:
            updated["current_stage"] = AUTHORING_STAGES[0]
        updated["status"] = "drafting"
        updated["review"] = {
            "stage": updated["current_stage"],
            "label": STAGE_LABELS[updated["current_stage"]],
            "message": (
                "Os dados iniciais foram alterados. Os artefactos existentes foram "
                "preservados e devem ser revistos."
            ),
        }
        for proposal in updated.get("ai_proposals", []):
            if isinstance(proposal, dict) and proposal.get("status") == "pending":
                proposal["status"] = "superseded"
                proposal["decision"] = "invalidada_por_alteracao_inicial"

    updated.setdefault("audit", []).append(
        {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "stage": "Dados iniciais",
            "event": "Docente alterou os dados iniciais da sessão.",
            "feedback": ", ".join(changed_labels),
        }
    )
    return updated


def artifact_has_content(artifact: Any, *, root: bool = True) -> bool:
    if isinstance(artifact, str):
        return bool(artifact.strip())
    if isinstance(artifact, (int, float)):
        return artifact != 0
    if isinstance(artifact, list):
        return any(artifact_has_content(item, root=False) for item in artifact)
    if isinstance(artifact, dict):
        ignored = {"quality", "selected_types", "feedback_considered"} if root else set()
        return any(
            key not in ignored and artifact_has_content(value, root=False)
            for key, value in artifact.items()
        )
    return artifact not in {None, False}


def _validate_draft_shape(stage: str, artifact: Any) -> None:
    expected = dict if stage in {"curriculum_analysis", "pedagogical_design", "resources"} else list
    if not isinstance(artifact, expected):
        label = "um objeto" if expected is dict else "uma lista de linhas"
        raise ValueError(f"A etapa {STAGE_LABELS[stage]} deve conservar {label}.")


def _clean_learning_outcome_assumptions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
    )


def _version_metadata(
    state: PrismState,
    stage: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    enriched = deepcopy(metadata)
    if stage == "learning_outcomes":
        enriched["stage_context"] = {
            "learning_outcome_assumptions": _clean_learning_outcome_assumptions(
                state.get("learning_outcome_assumptions", [])
            )
        }
    return enriched


def _append_version(
    state: PrismState,
    stage: str,
    artifact: Any,
    metadata: dict[str, Any],
) -> None:
    versions = deepcopy(state.get("versions", {}))
    versions.setdefault(stage, []).append(deepcopy(artifact))
    state["versions"] = versions

    stage_index = STAGE_ORDER.index(stage)
    active_versions = dict(state.get("active_versions", {}))
    dependencies = {
        upstream: int(active_versions[upstream])
        for upstream in STAGE_ORDER[:stage_index]
        if upstream in active_versions
    }
    version_dependencies = deepcopy(state.get("version_dependencies", {}))
    version_dependencies.setdefault(stage, []).append(dependencies)
    state["version_dependencies"] = version_dependencies
    active_versions[stage] = len(versions[stage])
    state["active_versions"] = active_versions

    generation_metadata = deepcopy(state.get("generation_metadata", {}))
    generation_metadata.setdefault(stage, []).append(
        _version_metadata(state, stage, metadata)
    )
    state["generation_metadata"] = generation_metadata


def _snapshot_without_invalidation(
    state: PrismState,
    target_stage: str,
    reason: str,
) -> None:
    snapshots = deepcopy(state.get("revision_snapshots", []))
    snapshots.append(
        {
            "revision_id": f"R{len(snapshots) + 1}",
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "target_stage": target_stage,
            "feedback": reason,
            "previous_status": state.get("status", ""),
            "active_versions": deepcopy(state.get("active_versions", {})),
            "resource_types": list(state.get("resource_types", [])),
            "artifacts": {
                stage: deepcopy(state[stage])
                for stage in STAGE_ORDER
                if stage in state
            },
        }
    )
    state["revision_snapshots"] = snapshots


def _stable_identifier_remap(before: Any, after: Any) -> dict[str, str]:
    """Relaciona IDs preservados e IDs renumerados sem adivinhar linhas removidas."""

    if not isinstance(before, list) or not isinstance(after, list):
        return {}
    before_ids = [
        str(item.get("id", "")).strip()
        for item in before
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]
    after_ids = [
        str(item.get("id", "")).strip()
        for item in after
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]
    after_set = set(after_ids)
    mapping = {identifier: identifier for identifier in before_ids if identifier in after_set}
    unmatched_before = [identifier for identifier in before_ids if identifier not in mapping]
    mapped_after = set(mapping.values())
    unmatched_after = [identifier for identifier in after_ids if identifier not in mapped_after]
    mapping.update(zip(unmatched_before, unmatched_after))
    return mapping


def _remap_outcome_references(value: Any, mapping: dict[str, str]) -> Any:
    """Atualiza apenas chaves de referência a RA em artefactos dependentes."""

    if isinstance(value, list):
        return [_remap_outcome_references(item, mapping) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    remapped: dict[str, Any] = {}
    for key, item in value.items():
        if key == "outcome_id" and isinstance(item, str):
            remapped[key] = mapping.get(item, item)
        elif key == "outcome_ids" and isinstance(item, list):
            remapped[key] = [
                mapping.get(identifier, identifier)
                if isinstance(identifier, str)
                else deepcopy(identifier)
                for identifier in item
            ]
        else:
            remapped[key] = _remap_outcome_references(item, mapping)
    return remapped


def _remap_list_references(
    value: Any,
    field_name: str,
    mapping: dict[str, str],
) -> Any:
    """Atualiza uma lista de referências técnicas num artefacto dependente."""

    if isinstance(value, list):
        return [
            _remap_list_references(item, field_name, mapping)
            for item in value
        ]
    if not isinstance(value, dict):
        return deepcopy(value)
    remapped: dict[str, Any] = {}
    for key, item in value.items():
        if key == field_name and isinstance(item, list):
            remapped[key] = [
                mapping.get(identifier, identifier)
                if isinstance(identifier, str)
                else deepcopy(identifier)
                for identifier in item
            ]
        else:
            remapped[key] = _remap_list_references(
                item,
                field_name,
                mapping,
            )
    return remapped


def save_manual_draft(
    state: PrismState,
    target_stage: str,
    artifact: Any,
    reason: str = "",
    *,
    metadata: dict[str, Any] | None = None,
    stage_context: dict[str, Any] | None = None,
) -> PrismState:
    """Guarda um rascunho incompleto e preserva sempre os artefactos posteriores."""

    if target_stage not in AUTHORING_STAGES:
        raise ValueError("A etapa selecionada não pode ser editada manualmente.")
    updated = ensure_manual_artifacts(deepcopy(state))
    edited_artifact = deepcopy(artifact)
    _validate_draft_shape(target_stage, edited_artifact)
    context_changed = False
    edited_assumptions = _clean_learning_outcome_assumptions(
        updated.get("learning_outcome_assumptions", [])
    )
    if target_stage == "learning_outcomes" and stage_context is not None:
        edited_assumptions = _clean_learning_outcome_assumptions(
            stage_context.get("learning_outcome_assumptions", [])
        )
        context_changed = edited_assumptions != _clean_learning_outcome_assumptions(
            updated.get("learning_outcome_assumptions", [])
        )
    if target_stage == "learning_outcomes":
        edited_artifact = normalize_learning_outcome_ids(
            edited_artifact,
            sequential=False,
        )
        id_mapping = _stable_identifier_remap(
            updated.get("learning_outcomes"),
            edited_artifact,
        )
        if any(before != after for before, after in id_mapping.items()):
            for downstream in AUTHORING_STAGES[1:]:
                if downstream in updated:
                    updated[downstream] = _remap_outcome_references(
                        updated[downstream],
                        id_mapping,
                    )
    elif target_stage in {"teaching_activities", "assessment_activities"}:
        prefix = "AE" if target_stage == "teaching_activities" else "TA"
        edited_artifact = normalize_structured_activity_ids(
            edited_artifact,
            prefix=prefix,
            sequential=False,
        )
        id_mapping = _stable_identifier_remap(
            updated.get(target_stage),
            edited_artifact,
        )
        if target_stage == "teaching_activities" and any(
            before != after for before, after in id_mapping.items()
        ):
            updated["assessment_activities"] = _remap_list_references(
                updated.get("assessment_activities", []),
                "teaching_activity_ids",
                id_mapping,
            )
            updated["pedagogical_design"] = _remap_list_references(
                updated.get("pedagogical_design", {}),
                "component_ids",
                id_mapping,
            )
        elif target_stage == "assessment_activities" and any(
            before != after for before, after in id_mapping.items()
        ):
            updated["pedagogical_design"] = _remap_list_references(
                updated.get("pedagogical_design", {}),
                "component_ids",
                id_mapping,
            )
    if edited_artifact == updated.get(target_stage) and not context_changed:
        raise ValueError("Não foram detetadas alterações para guardar.")
    if target_stage == "resources":
        selected_types = validate_resource_types(updated.get("resource_types", []))
        blank_resources = blank_artifact("resources", updated)
        resource_fields = {
            RESOURCE_PRESENTATION: "presentation_outline",
            RESOURCE_WORKSHEET: "lesson_worksheet",
            RESOURCE_TEST: "test",
            RESOURCE_PRACTICAL: "practical_activity",
        }
        edited_artifact["selected_types"] = list(selected_types)
        for resource_type, field in resource_fields.items():
            if resource_type not in selected_types:
                edited_artifact[field] = deepcopy(blank_resources[field])
        edited_artifact = attach_quality_report(updated, edited_artifact)

    clean_reason = reason.strip() or "Conteúdo alterado diretamente pelo docente."
    _snapshot_without_invalidation(updated, target_stage, clean_reason)
    if target_stage == "learning_outcomes":
        updated["learning_outcome_assumptions"] = edited_assumptions
    updated[target_stage] = edited_artifact
    updated.setdefault("feedback", {})[target_stage] = clean_reason
    _append_version(
        updated,
        target_stage,
        edited_artifact,
        metadata
        or {
            "provider": "Docente",
            "model": "Edição manual",
            "duration_ms": 0,
            "total_tokens": 0,
            "validation_attempts": 0,
            "manual_edit": True,
        },
    )

    target_index = STAGE_ORDER.index(target_stage)
    statuses = dict(updated.get("stage_statuses", {}))
    statuses[target_stage] = "draft"
    for stage in AUTHORING_STAGES[target_index + 1 :]:
        statuses[stage] = (
            "needs_review" if artifact_has_content(updated.get(stage)) else "empty"
        )
    statuses["final_validation"] = "pending"
    updated["stage_statuses"] = statuses
    updated.pop("final_validation", None)
    updated.get("active_versions", {}).pop("final_validation", None)
    updated["current_stage"] = target_stage
    updated["status"] = "drafting"
    updated["review"] = {
        "stage": target_stage,
        "label": STAGE_LABELS[target_stage],
        "message": "Rascunho guardado. Pode continuar sem executar a IA.",
    }
    _record_decision(
        updated,
        target_stage,
        f"Docente guardou um rascunho em {STAGE_LABELS[target_stage]}.",
        clean_reason,
    )
    return updated


def _parse_history_selection(selected_version: str) -> tuple[str, int]:
    try:
        stage, index_text = str(selected_version or "").rsplit("::", maxsplit=1)
        index = int(index_text)
    except (ValueError, TypeError) as error:
        raise ValueError("Selecione uma versão válida do histórico.") from error
    if stage not in AUTHORING_STAGES:
        raise ValueError(
            "A verificação final é recalculada e não pode ser restaurada do histórico."
        )
    return stage, index


def version_restore_impact(
    state: PrismState,
    selected_version: str,
) -> dict[str, Any]:
    """Descreve o impacto de restaurar uma versão sem modificar a sessão."""

    if not is_manual_first(state):
        raise ValueError("O restauro aplica-se ao fluxo de autoria manual.")
    stage, index = _parse_history_selection(selected_version)
    versions = state.get("versions", {}).get(stage, [])
    if index < 0 or index >= len(versions):
        raise ValueError("A versão selecionada já não está disponível.")
    active_version = int(
        state.get("active_versions", {}).get(stage) or len(versions) or 0
    )
    target_index = STAGE_ORDER.index(stage)
    affected_stages = [
        downstream
        for downstream in AUTHORING_STAGES[target_index + 1 :]
        if artifact_has_content(state.get(downstream))
    ]
    return {
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "version_index": index,
        "version_number": index + 1,
        "active_version": active_version,
        "is_active": active_version == index + 1,
        "was_completed": state.get("status") == "completed",
        "affected_stages": affected_stages,
        "affected_labels": [STAGE_LABELS[item] for item in affected_stages],
    }


def restore_stage_version(
    state: PrismState,
    selected_version: str,
) -> PrismState:
    """Volta a tornar ativa uma versão histórica, sem criar uma nova versão."""

    impact = version_restore_impact(state, selected_version)
    if impact["is_active"]:
        raise ValueError("A versão selecionada já é a versão ativa desta etapa.")
    stage = str(impact["stage"])
    artifact = deepcopy(
        state["versions"][stage][int(impact["version_index"])]
    )
    restored = ensure_manual_artifacts(deepcopy(state))
    if stage == "learning_outcomes":
        metadata_versions = restored.get("generation_metadata", {}).get(stage, [])
        version_index = int(impact["version_index"])
        version_metadata = (
            metadata_versions[version_index]
            if 0 <= version_index < len(metadata_versions)
            and isinstance(metadata_versions[version_index], dict)
            else {}
        )
        stage_context = version_metadata.get("stage_context", {})
        if (
            isinstance(stage_context, dict)
            and "learning_outcome_assumptions" in stage_context
        ):
            restored["learning_outcome_assumptions"] = (
                _clean_learning_outcome_assumptions(
                    stage_context.get("learning_outcome_assumptions", [])
                )
            )
    previous_resource_types = list(restored.get("resource_types", []))
    if stage == "resources":
        selected_types = validate_resource_types(
            list(artifact.get("selected_types", previous_resource_types))
        )
        restored["resource_types"] = selected_types
        artifact["selected_types"] = list(selected_types)
        artifact = attach_quality_report(restored, artifact)
    restored[stage] = artifact
    restored.setdefault("active_versions", {})[stage] = int(
        impact["version_number"]
    )
    target_index = STAGE_ORDER.index(stage)
    statuses = dict(restored.get("stage_statuses", {}))
    statuses[stage] = "draft"
    for downstream in AUTHORING_STAGES[target_index + 1 :]:
        statuses[downstream] = (
            "needs_review"
            if artifact_has_content(restored.get(downstream))
            else "empty"
        )
    statuses["final_validation"] = "pending"
    restored["stage_statuses"] = statuses
    restored.pop("final_validation", None)
    restored.get("active_versions", {}).pop("final_validation", None)
    restored["current_stage"] = stage
    restored["status"] = "drafting"
    restored["review"] = {
        "stage": stage,
        "label": STAGE_LABELS[stage],
        "message": f"A versão {impact['version_number']} voltou a ser a versão ativa.",
    }
    _record_decision(
        restored,
        stage,
        (
            f"Docente tornou novamente ativa a versão {impact['version_number']} de "
            f"{STAGE_LABELS[stage]}."
        ),
    )
    return restored


def navigate_to_stage(state: PrismState, target_stage: str) -> PrismState:
    """Muda de etapa sem gerar, validar ou apagar conteúdo."""

    if target_stage not in STAGE_ORDER:
        raise ValueError("A etapa selecionada não está disponível.")
    if state.get("status") == "completed" and target_stage != state.get("current_stage"):
        raise ValueError(
            "A sessão concluída está em modo de consulta. Inicie uma revisão explícita "
            "para voltar à autoria."
        )
    updated = ensure_manual_artifacts(deepcopy(state))
    updated["current_stage"] = target_stage
    if target_stage == "final_validation":
        resources = updated.get("resources")
        if isinstance(resources, dict):
            updated["resources"] = attach_quality_report(updated, resources)
        previous_validation = deepcopy(updated.get("final_validation"))
        current_validation = build_final_validation(updated)
        updated["final_validation"] = current_validation
        if (
            previous_validation != current_validation
            or target_stage not in updated.get("active_versions", {})
        ):
            _append_version(
                updated,
                target_stage,
                current_validation,
                {
                    "provider": "CoerIA",
                    "model": "Verificação determinística",
                    "duration_ms": 0,
                    "total_tokens": 0,
                    "validation_attempts": 1,
                },
            )
        updated["stage_statuses"][target_stage] = "checked"
        updated["status"] = "awaiting_review"
    else:
        updated["status"] = "drafting"
    updated["review"] = {
        "stage": target_stage,
        "label": STAGE_LABELS[target_stage],
        "message": (
            "Verificação global atualizada."
            if target_stage == "final_validation"
            else "Etapa aberta para autoria manual."
        ),
    }
    return updated


def reopen_completed_manual_session(
    state: PrismState,
    target_stage: str,
    reason: str,
) -> PrismState:
    """Reabre explicitamente uma sessão concluída sem alterar os artefactos."""

    if not is_manual_first(state) or state.get("status") != "completed":
        raise ValueError("A sessão não está concluída no modo de autoria manual.")
    if target_stage not in AUTHORING_STAGES:
        raise ValueError("Escolha uma etapa de autoria para reabrir a sessão.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("Indique o motivo da reabertura.")
    updated = ensure_manual_artifacts(deepcopy(state))
    _snapshot_without_invalidation(updated, target_stage, clean_reason)
    updated["current_stage"] = target_stage
    updated["status"] = "drafting"
    updated.setdefault("stage_statuses", {})["final_validation"] = "pending"
    updated.pop("final_validation", None)
    updated.get("active_versions", {}).pop("final_validation", None)
    updated["review"] = {
        "stage": target_stage,
        "label": STAGE_LABELS[target_stage],
        "message": "Sessão reaberta explicitamente para edição manual.",
    }
    _record_decision(
        updated,
        target_stage,
        f"Docente reabriu explicitamente {STAGE_LABELS[target_stage]}.",
        clean_reason,
    )
    return updated


def update_manual_resource_settings(
    state: PrismState,
    resource_types: list[str],
) -> PrismState:
    """Atualiza escolhas de recursos sem gerar conteúdo nem avançar a sessão."""

    if not is_manual_first(state):
        raise ValueError("Esta operação aplica-se apenas ao fluxo de autoria manual.")
    updated = ensure_manual_artifacts(deepcopy(state))
    if updated.get("current_stage") != "resources":
        raise ValueError(
            "A seleção de recursos pertence à etapa Geração de recursos educativos."
        )
    selected = validate_resource_types(resource_types)
    updated["resource_types"] = selected

    resources = deepcopy(updated["resources"])
    resources["selected_types"] = list(selected)
    updated["resources"] = attach_quality_report(updated, resources)
    statuses = dict(updated.get("stage_statuses", {}))
    statuses["resources"] = (
        "needs_review" if artifact_has_content(resources) else "empty"
    )
    statuses["final_validation"] = "pending"
    updated["stage_statuses"] = statuses
    updated.pop("final_validation", None)
    updated.get("active_versions", {}).pop("final_validation", None)
    _record_decision(
        updated,
        "resources",
        "Docente atualizou a seleção de recursos sem executar a IA.",
        ", ".join(selected),
    )
    return updated


def _value_at_scope(value: Any, path: list[str | int]) -> Any:
    current = value
    for part in path:
        current = current[part]
    return current


def _replace_at_scope(value: Any, path: list[str | int], replacement: Any) -> Any:
    if not path:
        return deepcopy(replacement)
    result = deepcopy(value)
    parent = result
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = deepcopy(replacement)
    return result


def request_ai_assistance(
    state: PrismState,
    target_stage: str,
    scope_path: list[str | int],
    scope_label: str,
    instruction: str,
    agent: PedagogicalAgent | LocalizedAssistanceAgent | None = None,
) -> PrismState:
    """Produz uma proposta localizada; nunca altera o artefacto ativo."""

    if target_stage not in AUTHORING_STAGES:
        raise ValueError("A assistência de IA só está disponível nas etapas de autoria.")
    clean_instruction = instruction.strip()
    if not clean_instruction:
        raise ValueError("Indique o que pretende que a IA proponha.")
    updated = ensure_manual_artifacts(deepcopy(state))
    current_artifact = deepcopy(updated[target_stage])
    try:
        before = deepcopy(_value_at_scope(current_artifact, scope_path))
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("O âmbito selecionado já não existe nesta versão.") from error

    working = deepcopy(updated)
    working["current_stage"] = target_stage
    working.setdefault("feedback", {})[target_stage] = (
        "Assistência localizada pedida pelo docente. Altera apenas "
        f"{scope_label}. Pedido: {clean_instruction}. Preserva o restante conteúdo."
    )
    if target_stage == "resources" and scope_path:
        resource_by_field = {
            "presentation_outline": RESOURCE_PRESENTATION,
            "lesson_worksheet": RESOURCE_WORKSHEET,
            "test": RESOURCE_TEST,
            "practical_activity": RESOURCE_PRACTICAL,
        }
        scoped_resource = resource_by_field.get(str(scope_path[0]))
        if scoped_resource and scoped_resource not in updated.get("resource_types", []):
            raise ValueError("O âmbito pertence a um recurso que não está selecionado.")
    proposed_images: list[dict[str, Any]] = []
    if scope_path:
        localized_agent = agent or build_localized_assistance_agent(
            updated.get("ai_provider", configured_ai_provider())
        )
        propose = getattr(localized_agent, "propose", None)
        if not callable(propose):
            raise AgentGenerationError(
                "A assistência de teste para um âmbito localizado deve implementar propose()."
            )
        result = propose(
            target_stage,
            working,
            list(scope_path),
            scope_label,
            clean_instruction,
            deepcopy(before),
        )
        after = deepcopy(result.artifact)
    else:
        working["_ai_assistance_request"] = {
            "mode": "complete_stage_proposal",
            "instruction": clean_instruction,
            "current_artifact": deepcopy(current_artifact),
        }
        active_agent = agent or build_pedagogical_team(
            updated.get("ai_provider", configured_ai_provider())
        ).generator
        generate = getattr(active_agent, "generate", None)
        if not callable(generate):
            raise AgentGenerationError(
                "A assistência para toda a etapa deve implementar generate()."
            )
        execution_agent: PedagogicalAgent = active_agent
        if target_stage == "resources":
            execution_agent = _SeparateResourceAgent(active_agent, None)
        result = execution_agent.generate(target_stage, working)
        after = deepcopy(result.artifact)
        if target_stage == "resources" and isinstance(after, dict):
            proposed_images = after.pop("_generated_images", [])
    if target_stage == "learning_outcomes" and not scope_path:
        after = normalize_learning_outcome_ids(after, sequential=True)
    if before == after:
        raise AgentGenerationError("A IA não propôs qualquer alteração nesse âmbito.")

    proposals = deepcopy(updated.get("ai_proposals", []))
    used_proposal_numbers = [
        int(match.group(1))
        for item in proposals
        if isinstance(item, dict)
        and (match := re.fullmatch(r"P(\d+)", str(item.get("id", ""))))
    ]
    proposal = {
        "id": f"P{max(used_proposal_numbers, default=0) + 1}",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "stage": target_stage,
        "scope_path": list(scope_path),
        "scope_label": scope_label,
        "instruction": clean_instruction,
        "before": before,
        "after": after,
        "status": "pending",
        "metadata": deepcopy(result.metadata),
        "generated_images": proposed_images,
    }
    proposals.append(proposal)
    updated["ai_proposals"] = proposals
    _record_decision(
        updated,
        target_stage,
        "IA produziu uma proposta localizada; nenhuma alteração foi aplicada.",
        f"Âmbito: {scope_label}. Pedido: {clean_instruction}",
    )
    return updated


def decide_ai_proposal(
    state: PrismState,
    proposal_id: str,
    accept: bool,
    selections: list[dict[str, Any]] | None = None,
    *,
    edited_after: Any = None,
) -> PrismState:
    """Aceita ou rejeita explicitamente uma proposta previamente guardada."""

    working = deepcopy(state)
    proposals = deepcopy(working.get("ai_proposals", []))
    matching_proposals = [
        item for item in proposals if item.get("id") == proposal_id
    ]
    if not matching_proposals:
        raise ValueError("A proposta de IA selecionada já não está disponível.")
    # Sessões migradas podem ter IDs repetidos: ao remover uma antiga etapa, a
    # numeração ficava com uma lacuna e len(proposals) reutilizava um ID. A UI
    # apresenta a proposta pendente mais recente, portanto decide a mesma aqui.
    proposal = next(
        (
            item
            for item in reversed(matching_proposals)
            if item.get("status") == "pending"
        ),
        None,
    )
    if proposal is None:
        raise ValueError("Esta proposta de IA já foi decidida.")
    proposal["status"] = "accepted" if accept else "rejected"
    proposal["decided_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    working["ai_proposals"] = proposals
    stage = str(proposal["stage"])
    if not accept:
        _record_decision(working, stage, "Docente rejeitou a proposta localizada da IA.")
        return working

    scope_path = list(proposal.get("scope_path", []))
    try:
        current_scope_value = _value_at_scope(working[stage], scope_path)
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(
            "O âmbito da proposta deixou de existir. Rejeite-a e peça uma nova proposta."
        ) from error
    if current_scope_value != proposal.get("before"):
        raise ValueError(
            "O rascunho foi alterado depois desta proposta. Para evitar substituir "
            "trabalho mais recente, rejeite-a e peça uma nova proposta."
        )

    if edited_after is not None:
        if selections is not None:
            raise ValueError(
                "A revisão editada não pode ser combinada com decisões por célula."
            )
        if stage != "resources" or scope_path:
            raise ValueError(
                "A revisão editada completa aplica-se apenas à etapa "
                "Geração de recursos educativos."
            )
        if not isinstance(edited_after, dict):
            raise ValueError("A proposta editada deve conservar a estrutura dos recursos.")
        artifact = deepcopy(edited_after)
        proposal["reviewed_after"] = deepcopy(edited_after)
        proposal["review_mode"] = "edited_complete_resource"
    elif selections is None:
        artifact = _replace_at_scope(
            working[stage],
            scope_path,
            proposal.get("after"),
        )
    else:
        changes = proposal_review_changes(
            stage,
            working[stage],
            scope_path,
            proposal.get("after"),
        )
        artifact = apply_proposal_review_changes(
            working[stage],
            changes,
            selections,
        )
        accepted_keys = {
            str(item.get("key", ""))
            for item in selections
            if isinstance(item, dict) and item.get("accept") is True
        }
        accepted_keys &= {str(change["key"]) for change in changes}
        proposal["review_decisions"] = deepcopy(selections)
        proposal["status"] = (
            "accepted"
            if len(accepted_keys) == len(changes)
            else "partially_accepted"
        )
    if stage == "resources" and proposal.get("generated_images"):
        current_images = [
            deepcopy(item)
            for item in working.get("generated_images", [])
            if isinstance(item, dict)
        ]
        known_ids = {str(item.get("id", "")) for item in current_images}
        current_images.extend(
            deepcopy(item)
            for item in proposal.get("generated_images", [])
            if isinstance(item, dict) and str(item.get("id", "")) not in known_ids
        )
        working["generated_images"] = current_images
    accepted = save_manual_draft(
        working,
        stage,
        artifact,
        f"Proposta {proposal_id} da IA aceite pelo docente.",
        metadata={
            **deepcopy(proposal.get("metadata", {})),
            "assistance_proposal_id": proposal_id,
            "human_approved": True,
        },
    )
    # save_manual_draft faz uma cópia; replica a decisão que acabou de ser tomada.
    accepted["ai_proposals"] = proposals
    return accepted


def verify_stage_with_ai(
    state: PrismState,
    target_stage: str,
    critic: PedagogicalCritic | None = None,
) -> PrismState:
    """Regista uma crítica facultativa e não bloqueante, sem modificar conteúdo."""

    if target_stage not in AUTHORING_STAGES:
        raise ValueError("A verificação por IA só se aplica às etapas de autoria.")
    updated = ensure_manual_artifacts(deepcopy(state))
    active_critic = critic or build_pedagogical_team(
        updated.get("ai_provider", configured_ai_provider())
    ).critic
    result: CritiqueResult = active_critic.review(
        target_stage,
        updated,
        updated[target_stage],
    )
    deterministic_criteria = {
        "unique_outcomes",
        "taxonomy_outcomes",
        "assessment_coverage",
        "assessment_purposes",
        "assessment_teaching_alignment",
        "teaching_coverage",
        "formative_activity_structure",
        "constructive_alignment",
        "resource_selection",
        "presentation_visuals",
        "test_points",
        "practical_weights",
    }
    ignored_findings = [
        finding
        for finding in result.findings
        if str(finding.get("criterion", "")).strip().casefold()
        in deterministic_criteria
        or str(finding.get("criterion", "")).strip().casefold().startswith(
            ("resource_", "coverage_")
        )
    ]
    findings = [
        finding for finding in result.findings if finding not in ignored_findings
    ]
    findings = [
        {
            **deepcopy(finding),
            "target": resolve_validation_target(
                target_stage,
                updated[target_stage],
                finding,
            ),
        }
        for finding in findings
    ]
    metadata = deepcopy(result.metadata)
    if ignored_findings:
        metadata["ignored_deterministic_findings"] = deepcopy(ignored_findings)
    review = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "context_signature": ai_review_context_signature(updated, target_stage),
        "passed": not any(
            finding.get("severity") == "blocking" for finding in findings
        ),
        "findings": deepcopy(findings),
        "revision_instructions": result.revision_instructions if findings else "",
        "metadata": metadata,
        "non_blocking": True,
    }
    reviews = deepcopy(updated.get("ai_reviews", {}))
    reviews.setdefault(target_stage, []).append(review)
    updated["ai_reviews"] = reviews
    _record_decision(
        updated,
        target_stage,
        "Verificação facultativa por IA concluída; o resultado não bloqueia a navegação.",
    )
    return updated


def ai_review_context_signature(state: PrismState, target_stage: str) -> str:
    """Identifica o conteúdo e as dependências usados numa verificação facultativa."""

    if target_stage not in AUTHORING_STAGES:
        return ""
    target_index = AUTHORING_STAGES.index(target_stage)
    artifacts: dict[str, Any] = {}
    for stage in AUTHORING_STAGES[: target_index + 1]:
        artifact = deepcopy(state.get(stage))
        if stage == "resources" and isinstance(artifact, dict):
            artifact.pop("quality", None)
        artifacts[stage] = artifact
    relevant = {
        "course": state.get("course"),
        "resource_types": state.get("resource_types", []),
        "artifacts": artifacts,
    }
    serialized = json.dumps(
        relevant,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def ai_review_is_current(
    state: PrismState,
    target_stage: str,
    review: dict[str, Any],
) -> bool:
    """Distingue um parecer atual de um parecer histórico ou legado."""

    signature = str(review.get("context_signature", "")).strip()
    return bool(signature) and signature == ai_review_context_signature(
        state, target_stage
    )


def build_final_validation(state: PrismState) -> dict[str, Any]:
    """Prepara o ecrã final sem delegar a decisão a um modelo."""

    structural_checks: list[dict[str, Any]] = []
    resource_quality_checks: list[dict[str, Any]] = []
    for stage in AUTHORING_STAGES:
        artifact = state.get(stage, blank_artifact(stage, state))
        try:
            if stage == "resources":
                quality = attach_quality_report(state, artifact).get("quality", {})
                resource_quality_checks = deepcopy(quality.get("checks", []))
                if not quality.get("passed"):
                    raise ValueError(
                        f"{quality.get('summary', {}).get('errors', 0)} erro(s) de qualidade."
                    )
            validate_artifact(stage, artifact, state)
            passed = True
            detail = "Estrutura completa e relações válidas."
        except (AgentGenerationError, IndexError, KeyError, TypeError, ValueError) as error:
            passed = False
            detail = str(error)
        structural_checks.append(
            {
                "id": f"stage_{stage}",
                "label": STAGE_LABELS[stage],
                "passed": passed,
                "detail": detail,
                "target_stage": stage,
                "target_key": "__stage__",
            }
        )

    alignment_rows = derive_alignment_rows(state)
    alignment_ok = bool(alignment_rows) and all(
        row.get("status") == "Coerente" for row in alignment_rows
    )
    first_alignment_problem = next(
        (
            str(row.get("outcome_id", "")).strip()
            for row in alignment_rows
            if row.get("status") != "Coerente"
        ),
        "",
    )
    selected_taxonomy = validate_taxonomy_choice(
        state.get("course", {}).get("taxonomy_type", "SOLO")
    )
    taxonomy_ok = bool(state.get("learning_outcomes")) and all(
        taxonomy_verb_allowed(
            selected_taxonomy,
            str(item.get("taxonomy_level", "")),
            str(item.get("action_verb", "")),
        )
        for item in state["learning_outcomes"]
    )
    first_taxonomy_problem = next(
        (
            str(item.get("id", "")).strip()
            for item in state.get("learning_outcomes", [])
            if not taxonomy_verb_allowed(
                selected_taxonomy,
                str(item.get("taxonomy_level", "")),
                str(item.get("action_verb", "")),
            )
        ),
        "",
    )
    checks = [
        *structural_checks,
        {
            "id": "alignment",
            "label": "Estrutura e alinhamento pedagógico",
            "passed": alignment_ok,
            "detail": (
                "Cada resultado deve estar ligado a conteúdo, atividade de "
                "ensino-aprendizagem e tarefa de avaliação; a tarefa deve indicar "
                "diretamente o resultado e uma atividade que o desenvolva."
            ),
            "target_stage": "assessment_activities",
            "target_key": first_alignment_problem or "__stage__",
        },
        {
            "id": "taxonomy",
            "label": f"Uso exclusivo da Taxonomia {selected_taxonomy}",
            "passed": taxonomy_ok,
            "detail": "Cada verbo deve corresponder ao nível taxonómico escolhido.",
            "target_stage": "learning_outcomes",
            "target_key": first_taxonomy_problem or "__stage__",
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks)
        and all(item.get("status") != "error" for item in resource_quality_checks),
        "checks": checks,
        "resource_quality_checks": resource_quality_checks,
        "message": (
            "Verificação global determinística. As observações de IA, quando "
            "pedidas, são facultativas e não substituem estes controlos."
        ),
    }


def _route_current_stage(state: PrismState) -> str:
    return state["current_stage"]


DETERMINISTIC_GENERATORS = {
    "curriculum_analysis": lambda state: analyse_curriculum(state)["curriculum_analysis"],
    "learning_outcomes": lambda state: formulate_learning_outcomes(state)["learning_outcomes"],
    "assessment_activities": lambda state: propose_assessment_activities(state)[
        "assessment_activities"
    ],
    "pedagogical_design": lambda state: create_pedagogical_design(state)["pedagogical_design"],
    "teaching_activities": lambda state: propose_teaching_activities(state)[
        "teaching_activities"
    ],
    "resources": lambda state: generate_resources(state)["resources"],
}


GENERATION_EVENTS = {
    "curriculum_analysis": "Conteúdos curriculares estruturados.",
    "learning_outcomes": "Resultados de aprendizagem formulados.",
    "teaching_activities": "Atividades de ensino-aprendizagem propostas.",
    "assessment_activities": "Tarefas e critérios de avaliação propostos.",
    "pedagogical_design": "Aulas planeadas.",
    "resources": "Recursos educativos e verificação automática de qualidade gerados.",
}


def create_test_agent() -> RuleBasedPedagogicalAgent:
    """Cria o agente determinístico usado apenas pelos testes automatizados."""

    return RuleBasedPedagogicalAgent(DETERMINISTIC_GENERATORS)


def _resource_generation_scope(
    state: PrismState,
    resource_type: str,
) -> PrismState:
    scoped = deepcopy(state)
    scoped["resource_types"] = [resource_type]
    scoped["resource_generation_scope"] = resource_type
    return scoped


def _resource_draft_fingerprint(
    state: PrismState,
    selected_types: list[str],
) -> str:
    relevant_state = {
        "ai_provider": state.get("ai_provider"),
        "course": state.get("course"),
        "resource_types": selected_types,
        **{
            stage: state.get(stage)
            for stage in STAGE_ORDER[: STAGE_ORDER.index("resources")]
        },
    }
    serialized = json.dumps(
        relevant_state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _resource_draft_payload(
    fingerprint: str,
    selected_types: list[str],
    entries: dict[str, Any],
) -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "selected_types": list(selected_types),
        "entries": deepcopy(entries),
    }


def _matching_resource_drafts(
    state: PrismState,
    fingerprint: str,
    selected_types: list[str],
) -> dict[str, Any]:
    drafts = state.get("resource_generation_drafts", {})
    if not isinstance(drafts, dict):
        return {}
    if (
        drafts.get("fingerprint") != fingerprint
        or drafts.get("selected_types") != selected_types
        or not isinstance(drafts.get("entries"), dict)
    ):
        return {}
    return deepcopy(drafts["entries"])


def _aggregate_resource_metadata(
    records: list[tuple[str, list[GenerationResult], int]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for resource_type, generations, quality_revisions in records:
        attempts = [deepcopy(generation.metadata) for generation in generations]

        def attempt_total(field: str) -> int:
            return sum(int(item.get(field, 0) or 0) for item in attempts)

        row: dict[str, Any] = {
            "resource_type": resource_type,
            "quality_revisions": quality_revisions,
            "provider": ", ".join(
                dict.fromkeys(
                    str(item.get("provider", "agente")) for item in attempts
                )
            ),
            "model": ", ".join(
                dict.fromkeys(
                    str(item.get("model", "não registado")) for item in attempts
                )
            ),
            "duration_ms": attempt_total("duration_ms"),
            "input_tokens": attempt_total("input_tokens"),
            "output_tokens": attempt_total("output_tokens"),
            "total_tokens": attempt_total("total_tokens"),
            "validation_attempts": attempt_total("validation_attempts"),
            "attempts": attempts,
        }
        agentic_attempts = [
            item.get("agentic", {})
            for item in attempts
            if item.get("agentic", {}).get("enabled")
        ]
        if agentic_attempts:
            review_values = [
                details.get("critic_passed") for details in agentic_attempts
            ]
            row["agentic"] = {
                "enabled": True,
                "critic_passed": (
                    False
                    if False in review_values
                    else True
                    if len(review_values) == len(attempts)
                    and all(value is True for value in review_values)
                    else None
                ),
                "findings": [
                    deepcopy(finding)
                    for details in agentic_attempts
                    for finding in details.get("findings", [])
                ],
                "revision_instructions": "; ".join(
                    details["revision_instructions"]
                    for details in agentic_attempts
                    if details.get("revision_instructions")
                ),
                "automatic_revisions": sum(
                    int(details.get("automatic_revisions", 0) or 0)
                    for details in agentic_attempts
                ),
                "runs": [
                    deepcopy(run)
                    for details in agentic_attempts
                    for run in details.get("runs", [])
                ],
            }
        rows.append(row)

    def total(field: str) -> int:
        return sum(int(row.get(field, 0) or 0) for row in rows)

    providers = list(dict.fromkeys(str(row.get("provider", "agente")) for row in rows))
    models = list(
        dict.fromkeys(str(row.get("model", "não registado")) for row in rows)
    )
    metadata: dict[str, Any] = {
        "provider": ", ".join(providers),
        "model": ", ".join(models),
        "duration_ms": total("duration_ms"),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "total_tokens": total("total_tokens"),
        "validation_attempts": total("validation_attempts"),
        "resource_generations": rows,
    }
    agentic_rows = [
        (row["resource_type"], row.get("agentic", {}))
        for row in rows
        if row.get("agentic", {}).get("enabled")
    ]
    if agentic_rows:
        review_values = [details.get("critic_passed") for _, details in agentic_rows]
        critic_passed = (
            False
            if False in review_values
            else True
            if len(review_values) == len(rows)
            and all(value is True for value in review_values)
            else None
        )
        metadata["agentic"] = {
            "enabled": True,
            "critic_passed": critic_passed,
            "findings": [
                {"resource_type": resource_type, **deepcopy(finding)}
                for resource_type, details in agentic_rows
                for finding in details.get("findings", [])
            ],
            "revision_instructions": "; ".join(
                f"{resource_type}: {details['revision_instructions']}"
                for resource_type, details in agentic_rows
                if details.get("revision_instructions")
            ),
            "automatic_revisions": sum(
                int(details.get("automatic_revisions", 0) or 0)
                for _, details in agentic_rows
            ),
            "runs": [
                {"resource_type": resource_type, **deepcopy(run)}
                for resource_type, details in agentic_rows
                for run in details.get("runs", [])
            ],
        }
    return metadata


class _SeparateResourceAgent:
    """Gera e valida cada tipo de recurso sem repetir os restantes."""

    def __init__(
        self,
        agent: PedagogicalAgent,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.agent = agent
        self.progress_callback = progress_callback

    def generate(self, stage: str, state: dict[str, Any]) -> GenerationResult:
        if stage != "resources":
            return self.agent.generate(stage, state)

        selected_types = validate_resource_types(state.get("resource_types"))
        total_resources = len(selected_types)
        max_quality_revisions = max(
            0,
            int(config_value("RESOURCE_QUALITY_MAX_REVISIONS", "1")),
        )
        draft_fingerprint = _resource_draft_fingerprint(state, selected_types)
        draft_entries = _matching_resource_drafts(
            state,
            draft_fingerprint,
            selected_types,
        )
        records: list[tuple[str, list[GenerationResult], int]] = []
        generated_artifacts: list[tuple[str, dict[str, Any]]] = []

        for index, resource_type in enumerate(selected_types, start=1):
            working_state = _resource_generation_scope(state, resource_type)
            cached_entry = draft_entries.get(resource_type, {})
            cached_metadata = cached_entry.get("generation_metadata", [])
            cached_artifact = deepcopy(cached_entry.get("artifact", {}))
            if (
                isinstance(cached_artifact, dict)
                and isinstance(cached_metadata, list)
                and cached_metadata
            ):
                cached_quality = attach_quality_report(
                    working_state,
                    cached_artifact,
                )
                if cached_quality.get("quality", {}).get("passed"):
                    cached_generations = [
                        GenerationResult(
                            artifact=deepcopy(cached_artifact),
                            metadata=deepcopy(metadata),
                        )
                        for metadata in cached_metadata
                    ]
                    records.append(
                        (
                            resource_type,
                            cached_generations,
                            int(cached_entry.get("quality_revisions", 0) or 0),
                        )
                    )
                    generated_artifacts.append(
                        (resource_type, cached_artifact)
                    )
                    _report_progress(
                        self.progress_callback,
                        (
                            f"Recurso {index} de {total_resources} reutilizado: "
                            f"{resource_type}."
                        ),
                    )
                    continue
            draft_entries.pop(resource_type, None)

            quality_revision = 0
            generations: list[GenerationResult] = []
            while True:
                action = "A gerar" if quality_revision == 0 else "A corrigir"
                _report_progress(
                    self.progress_callback,
                    f"{action} recurso {index} de {total_resources}: {resource_type}…",
                )
                try:
                    generation = self.agent.generate("resources", working_state)
                except AgentGenerationError as error:
                    drafts = _resource_draft_payload(
                        draft_fingerprint,
                        selected_types,
                        draft_entries,
                    )
                    completed = len(draft_entries)
                    if completed == 1:
                        resume_message = (
                            " 1 recurso já concluído foi guardado; a próxima "
                            "tentativa será retomada no recurso em falta."
                        )
                    elif completed > 1:
                        resume_message = (
                            f" {completed} recursos já concluídos foram guardados; "
                            "a próxima tentativa será retomada no recurso em falta."
                        )
                    else:
                        resume_message = ""
                    raise ResourceGenerationError(
                        f"{error}{resume_message}",
                        drafts,
                    ) from error
                generations.append(generation)
                artifact = deepcopy(generation.artifact)
                checked_artifact = attach_quality_report(working_state, artifact)
                if (
                    checked_artifact.get("quality", {}).get("passed")
                    or quality_revision >= max_quality_revisions
                ):
                    break

                quality_revision += 1
                failed_checks = [
                    check.get("detail", "")
                    for check in checked_artifact.get("quality", {}).get("checks", [])
                    if check.get("status") == "error"
                ]
                working_state = deepcopy(working_state)
                working_state.setdefault("feedback", {})["resources"] = (
                    f"Reformulação automática de {resource_type} após validação "
                    "de qualidade: "
                    + "; ".join(failed_checks)
                )

            records.append((resource_type, generations, quality_revision))
            generated_artifacts.append((resource_type, artifact))
            draft_entries[resource_type] = {
                "artifact": deepcopy(artifact),
                "generation_metadata": [
                    deepcopy(item.metadata) for item in generations
                ],
                "quality_revisions": quality_revision,
            }
            conclusion = (
                "concluído"
                if checked_artifact.get("quality", {}).get("passed")
                else "concluído com erros de qualidade"
            )
            _report_progress(
                self.progress_callback,
                f"Recurso {index} de {total_resources} {conclusion}: {resource_type}.",
            )

        combined = deepcopy(generated_artifacts[0][1])
        combined.pop("quality", None)
        combined["selected_types"] = list(selected_types)
        for resource_type, artifact in generated_artifacts:
            field = RESOURCE_ARTIFACT_FIELDS[resource_type]
            combined[field] = deepcopy(artifact[field])

        generated_images: list[dict[str, Any]] = []
        image_records: list[dict[str, Any]] = []
        if RESOURCE_PRESENTATION in selected_types:
            combined, generated_images, image_records = enrich_presentation_with_ai_images(
                state,
                combined,
                progress_callback=self.progress_callback,
            )
        combined["_generated_images"] = generated_images
        metadata = _aggregate_resource_metadata(records)
        if image_records:
            metadata["image_generations"] = image_records

        return GenerationResult(
            artifact=combined,
            metadata=metadata,
        )


def _stage_node(stage: str, agent: PedagogicalAgent):
    def execute(state: PrismState) -> dict[str, Any]:
        generation: GenerationResult = agent.generate(stage, state)
        artifact = deepcopy(generation.artifact)
        state_updates: dict[str, Any] = {}
        if stage == "resources" and isinstance(artifact, dict):
            state_updates["generated_images"] = artifact.pop("_generated_images", [])
        metadata = deepcopy(state.get("generation_metadata", {}))
        metadata.setdefault(stage, []).append(
            _version_metadata(state, stage, generation.metadata)
        )
        audit_update = _audit_update(
            state,
            stage,
            GENERATION_EVENTS[stage],
            _feedback(state, stage),
        )
        agentic = generation.metadata.get("agentic", {})
        if agentic.get("enabled"):
            audit_update["audit"].append(
                {
                    "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "stage": STAGE_LABELS[stage],
                    "event": (
                        "Crítico pedagógico aprovou a proposta."
                        if agentic.get("critic_passed") is True
                        else "Crítico pedagógico registou observações para decisão humana."
                    ),
                    "feedback": agentic.get("revision_instructions") or "—",
                }
            )
        for resource in generation.metadata.get("resource_generations", []):
            revisions = int(resource.get("quality_revisions", 0) or 0)
            if revisions:
                audit_update["audit"].append(
                    {
                        "timestamp": datetime.now(UTC).strftime(
                            "%Y-%m-%d %H:%M:%S UTC"
                        ),
                        "stage": STAGE_LABELS[stage],
                        "event": (
                            f"{resource['resource_type']} reformulado "
                            "automaticamente após falha na validação de qualidade."
                        ),
                        "feedback": f"{revisions} tentativa(s) adicional(is).",
                    }
                )
        return {
            stage: artifact,
            "generation_metadata": metadata,
            **state_updates,
            **audit_update,
        }

    return execute


def build_stage_executor(agent: PedagogicalAgent):
    """Compila o grafo que executa a etapa ativa com o agente selecionado.

    O grafo termina imediatamente após a proposta, preservando o ponto de
    decisão humana definido no diagrama de fluxo.
    """

    graph = StateGraph(PrismState)
    node_by_stage = {
        "curriculum_analysis": "analyse_curriculum",
        "learning_outcomes": "formulate_learning_outcomes",
        "assessment_activities": "propose_assessment_activities",
        "pedagogical_design": "create_pedagogical_design",
        "teaching_activities": "propose_teaching_activities",
        "resources": "generate_resources",
    }
    for stage, node_name in node_by_stage.items():
        graph.add_node(node_name, _stage_node(stage, agent))
    graph.add_conditional_edges(START, _route_current_stage, node_by_stage)
    for node_name in node_by_stage.values():
        graph.add_edge(node_name, END)
    return graph.compile()


def _record_decision(
    state: PrismState, stage: str, decision: str, feedback: str = ""
) -> None:
    state.setdefault("audit", []).append(
        {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "stage": STAGE_LABELS[stage],
            "event": decision,
            "feedback": feedback or "—",
        }
    )


def revision_targets_for_state(state: PrismState) -> tuple[str, ...]:
    """Devolve as etapas de autoria já alcançadas que podem ser reabertas."""

    if is_manual_first(state):
        return tuple(AUTHORING_STAGES)
    current_stage = state.get("current_stage", STAGE_ORDER[0])
    if current_stage not in STAGE_ORDER:
        return ()
    reached_index = (
        len(STAGE_ORDER) - 1
        if state.get("status") == "completed"
        else STAGE_ORDER.index(current_stage)
    )
    versions = state.get("versions", {})
    return tuple(
        stage
        for stage in STAGE_ORDER[: reached_index + 1]
        if stage != "final_validation"
        and (stage in state or bool(versions.get(stage)))
    )


def revision_impact(state: PrismState, target_stage: str) -> dict[str, Any]:
    """Calcula o impacto antes de qualquer mutação ou chamada ao fornecedor."""

    targets = revision_targets_for_state(state)
    if target_stage not in targets:
        raise ValueError("A etapa selecionada ainda não pode ser reaberta.")
    target_index = STAGE_ORDER.index(target_stage)
    generated_downstream = [
        stage
        for stage in STAGE_ORDER[target_index + 1 :]
        if stage in state and artifact_has_content(state.get(stage))
    ]
    return {
        "target_stage": target_stage,
        "target_label": STAGE_LABELS[target_stage],
        "next_version": len(state.get("versions", {}).get(target_stage, [])) + 1,
        "affected_stages": generated_downstream,
        "affected_labels": [STAGE_LABELS[stage] for stage in generated_downstream],
        "was_completed": state.get("status") == "completed",
    }


def _archive_and_invalidate_revision(
    state: PrismState,
    target_stage: str,
    feedback: str,
) -> None:
    """Preserva o estado coerente anterior e invalida a cadeia dependente."""

    target_index = STAGE_ORDER.index(target_stage)
    artifacts = {
        stage: deepcopy(state[stage])
        for stage in STAGE_ORDER
        if stage in state
    }
    snapshots = deepcopy(state.get("revision_snapshots", []))
    snapshots.append(
        {
            "revision_id": f"R{len(snapshots) + 1}",
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "target_stage": target_stage,
            "feedback": feedback,
            "previous_status": state.get("status", ""),
            "active_versions": deepcopy(state.get("active_versions", {})),
            "resource_types": list(state.get("resource_types", [])),
            "artifacts": artifacts,
        }
    )
    state["revision_snapshots"] = snapshots
    state.pop("resource_generation_drafts", None)

    stage_statuses = dict(state.get("stage_statuses", {}))
    active_versions = dict(state.get("active_versions", {}))
    for stage in STAGE_ORDER[target_index:]:
        existed = stage in state
        state.pop(stage, None)
        active_versions.pop(stage, None)
        if stage == target_stage:
            stage_statuses[stage] = "generating"
        elif existed:
            stage_statuses[stage] = "stale"
        else:
            stage_statuses[stage] = "pending"
    state["stage_statuses"] = stage_statuses
    state["active_versions"] = active_versions


def reopen_stage(
    state: PrismState,
    target_stage: str,
    feedback: str,
    agent: PedagogicalAgent | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PrismState:
    """Cria uma nova versão de uma etapa e preserva a versão coerente anterior."""

    if is_manual_first(state):
        raise ValueError(
            "Nesta sessão, use a assistência de IA e aprove ou rejeite a proposta "
            "antes de alterar o rascunho."
        )
    if state.get("status") not in {"awaiting_review", "completed"}:
        raise ValueError("A sessão não está disponível para reabertura.")
    clean_feedback = feedback.strip()
    if not clean_feedback:
        raise ValueError("Indique a alteração que pretende efetuar.")
    revision_impact(state, target_stage)

    updated = deepcopy(state)
    origin_stage = updated.get("current_stage", target_stage)
    _record_decision(
        updated,
        origin_stage,
        f"Docente reabriu {STAGE_LABELS[target_stage]} para nova versão.",
        clean_feedback,
    )
    feedback_by_stage = dict(updated.get("feedback", {}))
    feedback_by_stage[target_stage] = clean_feedback
    updated["feedback"] = feedback_by_stage
    _archive_and_invalidate_revision(updated, target_stage, clean_feedback)
    updated["current_stage"] = target_stage
    updated["status"] = "generating"
    updated["review"] = {
        "stage": target_stage,
        "label": STAGE_LABELS[target_stage],
        "message": "A produzir uma nova versão após confirmação do impacto.",
    }
    return run_current_stage(
        updated,
        agent=agent,
        progress_callback=progress_callback,
    )


def apply_manual_edit(
    state: PrismState,
    target_stage: str,
    artifact: Any,
    reason: str = "",
    *,
    stage_context: dict[str, Any] | None = None,
) -> PrismState:
    """Guarda uma edição humana como nova versão, sem chamar um fornecedor de IA."""

    if is_manual_first(state):
        return save_manual_draft(
            state,
            target_stage,
            artifact,
            reason,
            stage_context=stage_context,
        )
    if state.get("status") not in {"awaiting_review", "completed"}:
        raise ValueError("A sessão não está disponível para edição manual.")
    revision_impact(state, target_stage)
    edited_artifact = deepcopy(artifact)
    edited_assumptions = _clean_learning_outcome_assumptions(
        state.get("learning_outcome_assumptions", [])
    )
    context_changed = False
    if target_stage == "learning_outcomes" and stage_context is not None:
        edited_assumptions = _clean_learning_outcome_assumptions(
            stage_context.get("learning_outcome_assumptions", [])
        )
        context_changed = edited_assumptions != _clean_learning_outcome_assumptions(
            state.get("learning_outcome_assumptions", [])
        )
    if edited_artifact == state.get(target_stage) and not context_changed:
        raise ValueError("Não foram detetadas alterações para guardar.")

    updated = deepcopy(state)
    if target_stage == "resources":
        validate_artifact(target_stage, edited_artifact, updated)
        edited_artifact = attach_quality_report(updated, edited_artifact)
    else:
        validate_artifact(target_stage, edited_artifact, updated)

    clean_reason = reason.strip() or "Conteúdo alterado diretamente pelo docente."
    origin_stage = updated.get("current_stage", target_stage)
    _archive_and_invalidate_revision(updated, target_stage, clean_reason)
    _record_decision(
        updated,
        origin_stage,
        f"Docente editou manualmente {STAGE_LABELS[target_stage]}.",
        clean_reason,
    )
    updated[target_stage] = edited_artifact
    if target_stage == "learning_outcomes":
        updated["learning_outcome_assumptions"] = edited_assumptions
    updated.setdefault("feedback", {})[target_stage] = clean_reason

    versions = deepcopy(updated.get("versions", {}))
    versions.setdefault(target_stage, []).append(deepcopy(edited_artifact))
    updated["versions"] = versions

    stage_index = STAGE_ORDER.index(target_stage)
    active_versions = dict(updated.get("active_versions", {}))
    dependencies = {
        upstream_stage: int(active_versions[upstream_stage])
        for upstream_stage in STAGE_ORDER[:stage_index]
        if upstream_stage in active_versions
    }
    version_dependencies = deepcopy(updated.get("version_dependencies", {}))
    version_dependencies.setdefault(target_stage, []).append(dependencies)
    updated["version_dependencies"] = version_dependencies
    active_versions[target_stage] = len(versions[target_stage])
    updated["active_versions"] = active_versions

    generation_metadata = deepcopy(updated.get("generation_metadata", {}))
    generation_metadata.setdefault(target_stage, []).append(
        _version_metadata(updated, target_stage, {
            "provider": "Docente",
            "model": "Edição manual",
            "duration_ms": 0,
            "total_tokens": 0,
            "validation_attempts": 1,
            "manual_edit": True,
        })
    )
    updated["generation_metadata"] = generation_metadata
    stage_statuses = dict(updated.get("stage_statuses", {}))
    stage_statuses[target_stage] = "awaiting_review"
    updated["stage_statuses"] = stage_statuses
    updated["current_stage"] = target_stage
    updated["status"] = "awaiting_review"
    updated["review"] = {
        "stage": target_stage,
        "label": STAGE_LABELS[target_stage],
        "message": "Edição manual guardada. A aguardar aprovação do docente.",
    }
    return updated


def run_current_stage(
    state: PrismState,
    agent: PedagogicalAgent | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PrismState:
    """Executa o agente da etapa ativa e pára para validação do docente."""

    stage = state["current_stage"]
    if stage == "final_validation":
        _report_progress(
            progress_callback,
            "A executar as verificações finais de estrutura e alinhamento…",
        )
        generated = deepcopy(state)
        resources = generated.get("resources")
        if isinstance(resources, dict):
            generated["resources"] = attach_quality_report(generated, resources)
        generated[stage] = build_final_validation(generated)
        generated.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": STAGE_LABELS[stage],
                "event": "Verificação final preparada para decisão do docente.",
                "feedback": "—",
            }
        )
    else:
        _report_progress(
            progress_callback,
            f"A gerar e validar «{STAGE_LABELS[stage]}»…",
        )
        active_agent = agent or build_pedagogical_team(
            state.get("ai_provider", configured_ai_provider())
        )
        execution_agent: PedagogicalAgent = active_agent
        if stage == "resources":
            execution_agent = _SeparateResourceAgent(
                active_agent,
                progress_callback,
            )
        generated = build_stage_executor(execution_agent).invoke(state)

        if stage == "resources":
            _report_progress(
                progress_callback,
                "A verificar o conjunto final dos recursos…",
            )
            generated[stage] = attach_quality_report(generated, generated[stage])
            generated.pop("resource_generation_drafts", None)
    _report_progress(
        progress_callback,
        "A preparar a proposta para revisão do docente…",
    )
    versions = deepcopy(generated.get("versions", {}))
    versions.setdefault(stage, []).append(deepcopy(generated[stage]))
    generated["versions"] = versions
    stage_index = STAGE_ORDER.index(stage)
    active_versions = dict(generated.get("active_versions", {}))
    dependencies = {
        upstream_stage: int(active_versions[upstream_stage])
        for upstream_stage in STAGE_ORDER[:stage_index]
        if upstream_stage in active_versions
    }
    version_dependencies = deepcopy(generated.get("version_dependencies", {}))
    version_dependencies.setdefault(stage, []).append(dependencies)
    generated["version_dependencies"] = version_dependencies
    active_versions[stage] = len(versions[stage])
    generated["active_versions"] = active_versions
    stage_statuses = dict(generated.get("stage_statuses", {}))
    stage_statuses[stage] = "awaiting_review"
    generated["stage_statuses"] = stage_statuses
    generated["status"] = "awaiting_review"
    generated["review"] = {
        "stage": stage,
        "label": STAGE_LABELS[stage],
        "message": "A aguardar validação, aprovação ou pedido de reformulação do docente.",
    }
    return generated


def create_session(
    course: CourseInput,
    resource_types: list[str] | None = None,
    agent: PedagogicalAgent | None = None,
    ai_provider: str | None = None,
    ai_image_generation_enabled: bool = False,
    source_reduction: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    manual_first: bool | None = None,
) -> PrismState:
    """Inicia uma sessão no primeiro ponto de validação humana."""

    selected_resource_types = validate_resource_types(resource_types)
    use_manual_first = agent is None if manual_first is None else bool(manual_first)
    state: PrismState = {
        "schema_version": SCHEMA_VERSION,
        "orchestration": {
            "mode": MANUAL_FIRST_MODE if use_manual_first else "bounded-generator-critic",
            "human_approval_required": not use_manual_first,
            "llm_optional": use_manual_first,
            "proposal_approval_required": use_manual_first,
            "global_deterministic_validation_required": True,
        },
        "course": course.to_dict(),
        "feedback": {},
        "audit": [],
        "versions": {},
        "generation_metadata": {},
        "version_dependencies": {},
        "active_versions": {},
        "stage_statuses": {stage: "pending" for stage in STAGE_ORDER},
        "revision_snapshots": [],
        "ai_proposals": [],
        "ai_reviews": {},
        "resource_types": selected_resource_types,
        "generated_images": [],
        "source_reduction": deepcopy(source_reduction or {}),
        "learning_outcome_assumptions": [],
        "ai_image_generation_enabled": bool(ai_image_generation_enabled),
        "ai_provider": validate_ai_provider(
            ai_provider or configured_ai_provider()
        ),
        "current_stage": STAGE_ORDER[0],
        "status": "drafting" if use_manual_first else "generating",
    }
    if use_manual_first:
        ensure_manual_artifacts(state)
        state["stage_statuses"] = {
            stage: "draft" if stage == STAGE_ORDER[0] else "empty"
            for stage in AUTHORING_STAGES
        }
        state["stage_statuses"]["final_validation"] = "pending"
        state["review"] = {
            "stage": STAGE_ORDER[0],
            "label": STAGE_LABELS[STAGE_ORDER[0]],
            "message": "Preencha manualmente ou peça assistência localizada à IA.",
        }
        state["audit"] = [
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": STAGE_LABELS[STAGE_ORDER[0]],
                "event": "Sessão manual criada sem executar um fornecedor de IA.",
                "feedback": "—",
            }
        ]
        return state
    return run_current_stage(
        state,
        agent=agent,
        progress_callback=progress_callback,
    )


def _mark_selected_images_approved(state: PrismState) -> None:
    """Regista as imagens documentais ou geradas aceites pelo docente."""

    selected_ids = {
        str(slide.get("visual_asset_id", "")).strip()
        for slide in state.get("resources", {}).get("presentation_outline", [])
        if isinstance(slide, dict)
        and slide.get("visual_mode") in {"documento", "ia"}
        and str(slide.get("visual_asset_id", "")).strip()
    }
    for collection in ("source_images", "generated_images"):
        for asset in state.get(collection, []):
            if isinstance(asset, dict):
                asset["approved"] = str(asset.get("id", "")) in selected_ids


def review_current_stage(
    state: PrismState,
    decision: str,
    feedback: str = "",
    revision_stage: str | None = None,
    agent: PedagogicalAgent | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PrismState:
    """Aplica a decisão do docente e executa a próxima etapa apropriada."""

    # Não alteramos o estado persistido até a nova proposta ser produzida com êxito.
    state = deepcopy(state)
    if is_manual_first(state):
        if decision != "approve":
            raise ValueError(
                "A reformulação automática foi substituída por assistência "
                "localizada com aprovação explícita."
            )
        current_stage = state.get("current_stage", STAGE_ORDER[0])
        if current_stage == "final_validation":
            refreshed = navigate_to_stage(state, "final_validation")
            if not refreshed["final_validation"].get("passed"):
                raise ValueError(
                    "A verificação global encontrou problemas bloqueantes. "
                    "Pode abrir qualquer etapa, corrigi-la e voltar a verificar."
                )
            _mark_selected_images_approved(refreshed)
            refreshed["status"] = "completed"
            refreshed["stage_statuses"]["final_validation"] = "approved"
            refreshed["review"] = {
                "stage": "completed",
                "label": "Concluído",
                "message": "Verificação global concluída; pacote pronto para exportação.",
            }
            _record_decision(
                refreshed,
                "final_validation",
                "Docente concluiu a verificação global determinística.",
            )
            return refreshed
        current_index = STAGE_ORDER.index(current_stage)
        state.setdefault("stage_statuses", {})[current_stage] = (
            "draft" if artifact_has_content(state.get(current_stage)) else "empty"
        )
        return navigate_to_stage(state, STAGE_ORDER[current_index + 1])
    if state.get("status") == "completed" and decision == "approve":
        # Uma segunda submissão do botão final não deve criar uma exceção nem
        # duplicar a decisão já registada.
        return state
    if state.get("status") not in {"awaiting_review", "completed"}:
        raise ValueError("A sessão não está num ponto de validação humana.")

    current_stage = state["current_stage"]
    clean_feedback = feedback.strip()

    if decision == "approve":
        if current_stage == "resources" and not state["resources"].get("quality", {}).get("passed"):
            raise ValueError(
                "A validação automática detetou erros. Solicite a reformulação dos recursos."
            )
        if (
            current_stage == "final_validation"
            and not state["final_validation"].get("passed")
        ):
            raise ValueError(
                "A estrutura final contém verificações bloqueantes. "
                "Selecione a componente que deve ser revista."
            )
        if current_stage == "resources":
            _mark_selected_images_approved(state)
        _record_decision(state, current_stage, "Docente aprovou a proposta.")
        stage_statuses = dict(state.get("stage_statuses", {}))
        stage_statuses[current_stage] = "approved"
        state["stage_statuses"] = stage_statuses
        current_index = STAGE_ORDER.index(current_stage)
        if current_index == len(STAGE_ORDER) - 1:
            state["status"] = "completed"
            state["review"] = {
                "stage": "completed",
                "label": "Concluído",
                "message": (
                    "Estrutura, alinhamento e recursos aprovados e prontos "
                    "para exportação."
                ),
            }
            return state

        state["current_stage"] = STAGE_ORDER[current_index + 1]
        state["status"] = "generating"
        return run_current_stage(
            state,
            agent=agent,
            progress_callback=progress_callback,
        )

    if decision != "revise":
        raise ValueError("A decisão deve ser 'approve' ou 'revise'.")
    if not clean_feedback:
        raise ValueError("Indique o feedback que fundamenta o pedido de reformulação.")

    target = revision_stage or current_stage
    return reopen_stage(
        state,
        target,
        clean_feedback,
        agent=agent,
        progress_callback=progress_callback,
    )
