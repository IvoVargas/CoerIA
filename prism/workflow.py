"""Fluxo CoerIA, implementado como grafo de estados LangGraph."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import (
    GenerationResult,
    PedagogicalAgent,
    RuleBasedPedagogicalAgent,
    build_pedagogical_team,
)
from .branding import config_value
from .curriculum import (
    ASSESSMENT_PURPOSES,
    CONTENT_IMPORTANCE,
    LEARNING_CONTEXTS,
    OUTCOME_TYPES,
    TAXONOMY_LEVELS,
    TAXONOMY_VERBS,
    taxonomy_level_for_verb,
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


class PrismState(TypedDict, total=False):
    schema_version: int
    orchestration: dict[str, Any]
    session_id: str
    source_input_text: str
    ai_provider: str
    course: dict[str, Any]
    feedback: dict[str, str]
    audit: list[dict[str, str]]
    curriculum_analysis: dict[str, Any]
    solo_taxonomy: list[dict[str, Any]]
    learning_outcomes: list[dict[str, Any]]
    outcome_taxonomy: list[dict[str, Any]]
    assessment_activities: list[dict[str, Any]]
    pedagogical_design: dict[str, Any]
    teaching_activities: list[dict[str, Any]]
    alignment_matrix: list[dict[str, Any]]
    resources: dict[str, Any]
    final_validation: dict[str, Any]
    current_stage: str
    status: str
    review: dict[str, str]
    resource_types: list[str]
    versions: dict[str, list[Any]]
    generation_metadata: dict[str, list[dict[str, Any]]]
    version_dependencies: dict[str, list[dict[str, int]]]
    active_versions: dict[str, int]
    stage_statuses: dict[str, str]
    revision_snapshots: list[dict[str, Any]]


STAGE_LABELS = {
    "curriculum_analysis": "Conteúdos e objetivos curriculares",
    "learning_outcomes": "Formulação dos resultados de aprendizagem",
    "outcome_taxonomy": "Classificação taxonómica dos resultados",
    "assessment_activities": "Avaliação formativa e sumativa",
    "pedagogical_design": "Design pedagógico",
    "teaching_activities": "Atividades formativas de aprendizagem",
    "alignment_matrix": "Matriz de alinhamento",
    "resources": "Recursos educativos",
    "final_validation": "Validação final da estrutura e do alinhamento",
}

STAGE_ORDER = (
    "curriculum_analysis",
    "learning_outcomes",
    "outcome_taxonomy",
    "assessment_activities",
    "pedagogical_design",
    "teaching_activities",
    "alignment_matrix",
    "resources",
    "final_validation",
)

SCHEMA_VERSION = 6

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


def _general_objectives(course: dict[str, Any], topics: list[str]) -> list[dict[str, str]]:
    source = str(course.get("general_aims", "") or "")
    fragments = [
        re.sub(r"\s+", " ", item).strip(" -•\t")
        for item in re.split(r"[\n.;]+", source)
        if len(re.sub(r"\s+", " ", item).strip(" -•\t")) >= 8
    ]
    if not fragments:
        fragments = [
            f"Desenvolver conhecimentos fundamentais sobre {topics[0].lower()}.",
            "Aplicar os conteúdos da unidade curricular em contextos relevantes.",
            "Promover análise crítica, autonomia e integração dos conhecimentos.",
        ]
    return [
        {"id": f"OG{index + 1}", "statement": statement}
        for index, statement in enumerate(fragments[:6])
    ]


def analyse_curriculum(state: PrismState) -> dict[str, Any]:
    course = state["course"]
    topics = _topics(str(course["source_text"]))
    feedback = _feedback(state, "curriculum_analysis")
    result = {
        "summary": (
            f"Unidade curricular orientada para {course['audience']}, com "
            f"{course['duration_hours']} horas de trabalho previsto."
        ),
        "themes": topics,
        "objectives": _general_objectives(course, topics),
        "contents": [
            {"id": f"C{index + 1}", "title": topic, "description": topic}
            for index, topic in enumerate(topics)
        ],
        "assumptions": [
            "Os conteúdos fornecidos pelo docente constituem a fonte primária.",
            "A progressão parte de conceitos fundamentais para aplicação e reflexão.",
        ],
        "feedback_considered": feedback or None,
    }
    return {
        "curriculum_analysis": result,
        **_audit_update(state, "curriculum_analysis", "Análise curricular produzida.", feedback),
    }


def formulate_learning_outcomes(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "learning_outcomes")
    taxonomy_type = validate_taxonomy_choice(state["course"].get("taxonomy_type", "SOLO"))
    levels = TAXONOMY_LEVELS[taxonomy_type]
    verbs = TAXONOMY_VERBS[taxonomy_type]
    contents = state["curriculum_analysis"]["contents"]
    objectives = state["curriculum_analysis"]["objectives"]
    objective_ids_by_outcome = [
        [objectives[index % len(objectives)]["id"]]
        for index in range(len(contents))
    ]
    for objective_index, objective in enumerate(objectives):
        target = objective_index % len(contents)
        if objective["id"] not in objective_ids_by_outcome[target]:
            objective_ids_by_outcome[target].append(objective["id"])
    outcomes = [
        {
            "id": f"RA{index + 1}",
            "theme": content["title"],
            "statement": (
                f"{verbs[levels[index % len(levels)]][0].capitalize()} "
                f"{content['title'].lower()}."
            ),
            "action_verb": verbs[levels[index % len(levels)]][0],
            "outcome_type": OUTCOME_TYPES[index % len(OUTCOME_TYPES)],
            "content_links": [
                {
                    "content_id": content["id"],
                    "importance": CONTENT_IMPORTANCE[0],
                },
                *(
                    [{
                        "content_id": contents[index - 1]["id"],
                        "importance": CONTENT_IMPORTANCE[1],
                    }]
                    if index > 0
                    else []
                ),
            ],
            "objective_ids": objective_ids_by_outcome[index],
        }
        for index, content in enumerate(contents)
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


def classify_learning_outcomes(state: PrismState) -> dict[str, Any]:
    taxonomy_type = validate_taxonomy_choice(state["course"].get("taxonomy_type", "SOLO"))
    feedback = _feedback(state, "outcome_taxonomy")
    classifications: list[dict[str, Any]] = []
    for outcome in state["learning_outcomes"]:
        level = (
            taxonomy_level_for_verb(taxonomy_type, outcome["action_verb"])
            or TAXONOMY_LEVELS[taxonomy_type][0]
        )
        classifications.append(
            {
                "outcome_id": outcome["id"],
                "taxonomy": taxonomy_type,
                "level": level,
                "action_verb": outcome["action_verb"],
            }
        )
    return {
        "outcome_taxonomy": classifications,
        **_audit_update(
            state,
            "outcome_taxonomy",
            f"Resultados classificados exclusivamente pela Taxonomia {taxonomy_type}.",
            feedback,
        ),
    }


def propose_assessment_activities(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "assessment_activities")
    classification_by_outcome = {
        item["outcome_id"]: item for item in state["outcome_taxonomy"]
    }
    assessments = [
        {
            "id": f"AV{index + 1}",
            "outcome_id": outcome["id"],
            "outcome_ids": [
                outcome["id"],
                *(
                    [state["learning_outcomes"][index + 1]["id"]]
                    if index % 2 == 0 and index + 1 < len(state["learning_outcomes"])
                    else []
                ),
            ],
            "work_type": "Trabalho individual" if index % 2 == 0 else "Trabalho de grupo",
            "assessment_purpose": ASSESSMENT_PURPOSES[index % len(ASSESSMENT_PURPOSES)],
            "activity": f"Tarefa aplicada: {outcome['statement']}",
            "evidence": "Resposta fundamentada com critérios explícitos.",
            "criterion": (
                "Domínio demonstrado ao nível "
                f"{classification_by_outcome[outcome['id']]['level']} da Taxonomia "
                f"{classification_by_outcome[outcome['id']]['taxonomy']}."
            ),
        }
        for index, outcome in enumerate(state["learning_outcomes"])
    ]
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
    feedback = _feedback(state, "pedagogical_design")
    course = state["course"]
    design = {
        "strategy": "Progressão guiada por resultados, prática e reflexão.",
        "sequence": [
            {
                "outcome_id": outcome["id"],
                "focus": outcome["statement"],
                "assessment": next(
                    item["activity"]
                    for item in state["assessment_activities"]
                    if outcome["id"] in item.get("outcome_ids", [item.get("outcome_id")])
                ),
            }
            for outcome in state["learning_outcomes"]
        ],
        "audience": course["audience"],
        "estimated_hours": course["duration_hours"],
        "feedback_considered": feedback or None,
    }
    return {
        "pedagogical_design": design,
        **_audit_update(
            state,
            "pedagogical_design",
            "Estrutura pedagógica criada.",
            feedback,
        ),
    }


def propose_teaching_activities(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "teaching_activities")
    activities = [
        {
            "id": f"EA{index + 1}",
            "outcome_id": outcome["id"],
            "outcome_ids": [outcome["id"]],
            "assessment_ids": [
                item["id"]
                for item in state["assessment_activities"]
                if outcome["id"] in item.get("outcome_ids", [item.get("outcome_id")])
            ],
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
            "Atividades formativas de aprendizagem propostas.",
            feedback,
        ),
    }


def validate_alignment(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "alignment_matrix")
    assessments_by_outcome = {
        outcome["id"]: [
            item["id"] for item in state["assessment_activities"]
            if outcome["id"] in item.get("outcome_ids", [item.get("outcome_id")])
        ]
        for outcome in state["learning_outcomes"]
    }
    teaching_by_outcome = {
        outcome["id"]: [
            item["id"] for item in state["teaching_activities"]
            if outcome["id"] in item.get("outcome_ids", [item.get("outcome_id")])
        ]
        for outcome in state["learning_outcomes"]
    }
    classification_by_outcome = {
        item["outcome_id"]: item for item in state["outcome_taxonomy"]
    }
    assessment_purposes_by_outcome = {
        outcome["id"]: sorted(
            {
                item["assessment_purpose"]
                for item in state["assessment_activities"]
                if outcome["id"] in item.get("outcome_ids", [item.get("outcome_id")])
            }
        )
        for outcome in state["learning_outcomes"]
    }
    matrix = [
        {
            "outcome_id": outcome["id"],
            "result": outcome["statement"],
            "objective_ids": list(outcome.get("objective_ids", [])),
            "content_ids": [link["content_id"] for link in outcome.get("content_links", [])],
            "taxonomy": classification_by_outcome[outcome["id"]]["taxonomy"],
            "taxonomy_level": classification_by_outcome[outcome["id"]]["level"],
            "assessment_ids": assessments_by_outcome[outcome["id"]],
            "assessment_purposes": assessment_purposes_by_outcome[outcome["id"]],
            "teaching_activity_ids": teaching_by_outcome[outcome["id"]],
            "resource_types": list(state.get("resource_types", [])),
            "assessment": "Sim" if assessments_by_outcome[outcome["id"]] else "Não",
            "teaching_activity": "Sim" if teaching_by_outcome[outcome["id"]] else "Não",
            "status": (
                "Coerente"
                if assessments_by_outcome[outcome["id"]] and teaching_by_outcome[outcome["id"]]
                else "Requer revisão"
            ),
            "rationale": (
                "Existem uma avaliação e uma atividade formativa de aprendizagem "
                "associadas ao resultado."
                if assessments_by_outcome[outcome["id"]] and teaching_by_outcome[outcome["id"]]
                else "Falta pelo menos uma evidência necessária ao alinhamento."
            ),
        }
        for outcome in state["learning_outcomes"]
    ]
    return {
        "alignment_matrix": matrix,
        **_audit_update(
            state,
            "alignment_matrix",
            "Matriz de alinhamento validada.",
            feedback,
        ),
    }


def generate_resources(state: PrismState) -> dict[str, Any]:
    feedback = _feedback(state, "resources")
    course = state["course"]
    selected_types = state.get("resource_types", [RESOURCE_PRESENTATION])
    taxonomy_type = validate_taxonomy_choice(course.get("taxonomy_type", "SOLO"))
    assessment_for = lambda outcome_id: next(
        item for item in state["assessment_activities"]
        if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
    )
    teaching_for = lambda outcome_id: next(
        item for item in state["teaching_activities"]
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
    return {
        "resources": resources,
        **_audit_update(
            state,
            "resources",
            "Recursos educativos e verificação automática de qualidade gerados.",
            feedback,
        ),
    }


def build_final_validation(state: PrismState) -> dict[str, Any]:
    """Prepara o ecrã final sem delegar a decisão a um modelo."""

    alignment_ok = bool(state.get("alignment_matrix")) and all(
        row.get("status") == "Coerente" for row in state["alignment_matrix"]
    )
    resource_quality_ok = bool(
        state.get("resources", {}).get("quality", {}).get("passed")
    )
    selected_taxonomy = validate_taxonomy_choice(
        state.get("course", {}).get("taxonomy_type", "SOLO")
    )
    taxonomy_ok = bool(state.get("outcome_taxonomy")) and all(
        item.get("taxonomy") == selected_taxonomy
        for item in state["outcome_taxonomy"]
    )
    checks = [
        {
            "id": "alignment",
            "label": "Estrutura e alinhamento pedagógico",
            "passed": alignment_ok,
        },
        {
            "id": "resources",
            "label": "Qualidade automática dos recursos",
            "passed": resource_quality_ok,
        },
        {
            "id": "taxonomy",
            "label": f"Uso exclusivo da Taxonomia {selected_taxonomy}",
            "passed": taxonomy_ok,
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "message": (
            "Confirme se a integração dos recursos mantém a estrutura e o "
            "alinhamento coerentes."
        ),
    }


def _route_current_stage(state: PrismState) -> str:
    return state["current_stage"]


DETERMINISTIC_GENERATORS = {
    "curriculum_analysis": lambda state: analyse_curriculum(state)["curriculum_analysis"],
    "learning_outcomes": lambda state: formulate_learning_outcomes(state)["learning_outcomes"],
    "outcome_taxonomy": lambda state: classify_learning_outcomes(state)[
        "outcome_taxonomy"
    ],
    "assessment_activities": lambda state: propose_assessment_activities(state)[
        "assessment_activities"
    ],
    "pedagogical_design": lambda state: create_pedagogical_design(state)["pedagogical_design"],
    "teaching_activities": lambda state: propose_teaching_activities(state)[
        "teaching_activities"
    ],
    "alignment_matrix": lambda state: validate_alignment(state)["alignment_matrix"],
    "resources": lambda state: generate_resources(state)["resources"],
}


GENERATION_EVENTS = {
    "curriculum_analysis": "Conteúdos e objetivos curriculares estruturados.",
    "learning_outcomes": "Resultados de aprendizagem formulados.",
    "outcome_taxonomy": "Resultados classificados pela taxonomia escolhida.",
    "assessment_activities": "Avaliações formativas ou sumativas propostas.",
    "pedagogical_design": "Estrutura pedagógica criada.",
    "teaching_activities": "Atividades formativas de aprendizagem propostas.",
    "alignment_matrix": "Matriz de alinhamento validada.",
    "resources": "Recursos educativos e verificação automática de qualidade gerados.",
}


def create_test_agent() -> RuleBasedPedagogicalAgent:
    """Cria o agente determinístico usado apenas pelos testes automatizados."""

    return RuleBasedPedagogicalAgent(DETERMINISTIC_GENERATORS)


def _stage_node(stage: str, agent: PedagogicalAgent):
    def execute(state: PrismState) -> dict[str, Any]:
        generation: GenerationResult = agent.generate(stage, state)
        metadata = deepcopy(state.get("generation_metadata", {}))
        metadata.setdefault(stage, []).append(generation.metadata)
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
        return {
            stage: generation.artifact,
            "generation_metadata": metadata,
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
        "outcome_taxonomy": "classify_learning_outcomes",
        "assessment_activities": "propose_assessment_activities",
        "pedagogical_design": "create_pedagogical_design",
        "teaching_activities": "propose_teaching_activities",
        "alignment_matrix": "validate_alignment",
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
        if stage in state
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
) -> PrismState:
    """Cria uma nova versão de uma etapa e preserva a versão coerente anterior."""

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
    return run_current_stage(updated, agent=agent)


def run_current_stage(
    state: PrismState, agent: PedagogicalAgent | None = None
) -> PrismState:
    """Executa o agente da etapa ativa e pára para validação do docente."""

    stage = state["current_stage"]
    if stage == "final_validation":
        generated = deepcopy(state)
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
        active_agent = agent or build_pedagogical_team(
            state.get("ai_provider", configured_ai_provider())
        )
        generated = build_stage_executor(active_agent).invoke(state)

        if stage == "resources":
            generated[stage] = attach_quality_report(generated, generated[stage])
            max_quality_revisions = max(
                0, int(config_value("RESOURCE_QUALITY_MAX_REVISIONS", "1"))
            )
            quality_revision = 0
            while (
                not generated[stage].get("quality", {}).get("passed")
                and quality_revision < max_quality_revisions
            ):
                quality_revision += 1
                working_state = deepcopy(generated)
                failed_checks = [
                    check.get("detail", "")
                    for check in generated[stage].get("quality", {}).get("checks", [])
                    if check.get("status") == "error"
                ]
                working_state.setdefault("feedback", {})["resources"] = (
                    "Reformulação automática após validação de qualidade: "
                    + "; ".join(failed_checks)
                )
                generated = build_stage_executor(active_agent).invoke(working_state)
                generated[stage] = attach_quality_report(generated, generated[stage])
                generated.setdefault("audit", []).append(
                    {
                        "timestamp": datetime.now(UTC).strftime(
                            "%Y-%m-%d %H:%M:%S UTC"
                        ),
                        "stage": STAGE_LABELS[stage],
                        "event": (
                            "Recursos reformulados automaticamente após falha "
                            "na validação de qualidade."
                        ),
                        "feedback": f"Tentativa automática {quality_revision}.",
                    }
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
) -> PrismState:
    """Inicia uma sessão no primeiro ponto de validação humana."""

    selected_resource_types = validate_resource_types(resource_types)
    state: PrismState = {
        "schema_version": SCHEMA_VERSION,
        "orchestration": {
            "mode": "bounded-generator-critic",
            "human_approval_required": True,
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
        "resource_types": selected_resource_types,
        "ai_provider": validate_ai_provider(
            ai_provider or configured_ai_provider()
        ),
        "current_stage": STAGE_ORDER[0],
        "status": "generating",
    }
    return run_current_stage(state, agent=agent)


def review_current_stage(
    state: PrismState,
    decision: str,
    feedback: str = "",
    revision_stage: str | None = None,
    agent: PedagogicalAgent | None = None,
) -> PrismState:
    """Aplica a decisão do docente e executa a próxima etapa apropriada."""

    # Não alteramos o estado persistido até a nova proposta ser produzida com êxito.
    state = deepcopy(state)
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
        return run_current_stage(state, agent=agent)

    if decision != "revise":
        raise ValueError("A decisão deve ser 'approve' ou 'revise'.")
    if not clean_feedback:
        raise ValueError("Indique o feedback que fundamenta o pedido de reformulação.")

    target = revision_stage or current_stage
    return reopen_stage(state, target, clean_feedback, agent=agent)
