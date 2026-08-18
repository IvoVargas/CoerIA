"""Agentes especializados para as etapas pedagógicas do CoerIA.

Em execução normal, cada agente pede uma proposta estruturada ao fornecedor de IA
selecionado para a sessão.
O agente baseado em regras existe exclusivamente para testes automatizados, onde
não se deve depender de uma chave de API ou de uma resposta não determinística.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from time import perf_counter
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .branding import config_value
from .curriculum import (
    ASSESSMENT_PURPOSES,
    BLOOM_LEVELS,
    CONTENT_IMPORTANCE,
    has_single_action_verb,
    LEARNING_CONTEXTS,
    MAX_OUTCOMES,
    MIN_OUTCOMES,
    OUTCOME_TYPES,
    SOLO_LEVELS,
    TAXONOMY_CHOICES,
    TAXONOMY_VERBS,
    taxonomy_catalogue_for_prompt,
    taxonomy_level_for_verb,
    taxonomy_verb_allowed,
    validate_taxonomy_choice,
)
from .models import (
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
)
from .providers import (
    AI_PROVIDER_IAEDU,
    AI_PROVIDER_OPENAI,
    IAeduResponsesAdapter,
    validate_ai_provider,
)


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_RESOURCE_MODEL = DEFAULT_MODEL


def supports_reasoning_effort(model: str) -> bool:
    """Indica se o modelo aceita o parâmetro ``reasoning.effort``."""

    normalized = model.strip().lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


# Alias interno mantido para compatibilidade com testes/código anterior.
_supports_reasoning_effort = supports_reasoning_effort


class AgentGenerationError(RuntimeError):
    """Erro compreensível ao produzir uma proposta pedagógica."""


@dataclass(frozen=True)
class GenerationResult:
    artifact: Any
    metadata: dict[str, Any]


class PedagogicalAgent(Protocol):
    def generate(self, stage: str, state: dict[str, Any]) -> GenerationResult:
        """Produz o artefacto de uma única etapa do fluxo."""


@dataclass(frozen=True)
class CritiqueResult:
    passed: bool
    findings: list[dict[str, str]]
    revision_instructions: str
    metadata: dict[str, Any]


class PedagogicalCritic(Protocol):
    def review(
        self, stage: str, state: dict[str, Any], artifact: Any
    ) -> CritiqueResult:
        """Revê uma proposta sem substituir a decisão do docente."""


STAGE_ROLES = {
    "curriculum_analysis": "especialista em análise curricular",
    "learning_outcomes": "especialista em resultados de aprendizagem",
    "outcome_taxonomy": "especialista na classificação taxonómica de resultados",
    "assessment_activities": "especialista em avaliação formativa e sumativa",
    "pedagogical_design": "agente de Design Pedagógico",
    "teaching_activities": "especialista em atividades formativas de aprendizagem",
    "alignment_matrix": "especialista em alinhamento construtivo",
    "resources": "especialista em recursos educativos",
}


STAGE_REQUIREMENTS = {
    "curriculum_analysis": (
        "Objeto com summary, themes, contents, objectives e assumptions. contents contém "
        "4 a 10 objetos {id, title, description}, com IDs C1, C2, ...; objectives contém "
        "objetos {id, statement}, com IDs OG1, OG2, ... estáveis."
    ),
    "learning_outcomes": (
        "Lista de 4 a 10 objetos {id, theme, statement, action_verb, outcome_type, "
        "content_links, objective_ids}. Cada resultado contém exatamente um verbo de ação "
        "observável, começa por esse verbo e liga-se a conteúdos e objetivos existentes."
    ),
    "outcome_taxonomy": (
        "Lista de objetos {outcome_id, taxonomy, level, action_verb}. taxonomy deve ser "
        "exatamente a taxonomia escolhida para a sessão (SOLO ou Bloom), nunca ambas; "
        "level e action_verb devem pertencer ao respetivo catálogo controlado."
    ),
    "assessment_activities": (
        "Lista de objetos {id, outcome_id, outcome_ids, work_type, assessment_purpose, "
        "activity, evidence, criterion}. assessment_purpose é exclusivamente Formativa "
        "ou Sumativa. É válido o conjunto conter apenas avaliações sumativas."
    ),
    "pedagogical_design": (
        "Objeto com strategy e sequence. sequence é uma lista de objetos "
        "{outcome_id, focus, assessment}; deve aplicar backward design."
    ),
    "teaching_activities": (
        "Lista de objetos {id, outcome_id, outcome_ids, assessment_ids, learning_context, "
        "activity, method, practice, support, feedback_strategy}; o conjunto deve cobrir "
        "todos os resultados e explicitar prática, acompanhamento e feedback."
    ),
    "alignment_matrix": (
        "Lista de objetos {outcome_id, result, objective_ids, content_ids, taxonomy, "
        "taxonomy_level, assessment_ids, assessment_purposes, teaching_activity_ids, "
        "resource_types, assessment, teaching_activity, status, rationale}. "
        "assessment e teaching_activity devem ser Sim ou Não; status deve indicar "
        "Coerente ou Requer revisão."
    ),
    "resources": (
        "Objeto com selected_types, presentation_outline, lesson_worksheet, test e "
        "practical_activity. Preenche apenas os recursos pedidos e mantém vazios os "
        "restantes. Cada elemento deve indicar os resultados de aprendizagem associados. "
        "Cada slide da apresentação inclui visual_mode, visual_asset_id, visual_prompt, visual_kind, "
        "visual_title, visual_items, visual_source e alt_text. visual_mode é diagrama, "
        "documento ou ia. visual_asset_id fica vazio em diagrama, contém um ID válido "
        "do catálogo source_image_catalogue em documento e é preenchido pela aplicação "
        "após gerar uma imagem quando visual_mode é ia. visual_prompt contém a instrução "
        "específica para a imagem IA e fica vazio nos restantes modos. visual_items contém entre "
        "2 e 4 textos não vazios; visual_title, visual_source e alt_text também nunca "
        "podem estar vazios. Os "
        "elementos visuais devem apoiar o conteúdo e não servir apenas de decoração. "
        "Cada recurso pedido deve cobrir exatamente todos os IDs dos resultados de "
        "aprendizagem, sem usar IDs desconhecidos. No teste, a soma dos pontos das "
        "questões deve ser igual a total_points. Na atividade prática, a união dos "
        "outcome_ids de todas as etapas deve cobrir exatamente todos os resultados e "
        "os pesos positivos dos critérios devem totalizar exatamente 100."
    ),
}


RESOURCE_ARTIFACT_FIELDS = {
    RESOURCE_PRESENTATION: "presentation_outline",
    RESOURCE_WORKSHEET: "lesson_worksheet",
    RESOURCE_TEST: "test",
    RESOURCE_PRACTICAL: "practical_activity",
}

RESOURCE_REQUIREMENTS = {
    RESOURCE_PRESENTATION: (
        "Lista de slides com title, bullets, outcome_id, visual_mode, visual_asset_id, "
        "visual_prompt, visual_kind, visual_title, visual_items, visual_source e alt_text. Cobre todos os "
        "resultados de aprendizagem e inclui slides de capa e síntese."
    ),
    RESOURCE_WORKSHEET: (
        "Objeto da ficha com title, overview, instructions e sections. Cada "
        "secção contém heading, content, outcome_ids e activity e o conjunto "
        "cobre todos os resultados de aprendizagem."
    ),
    RESOURCE_TEST: (
        "Objeto do teste com title, instructions, total_points e questions. "
        "Cada questão contém id, outcome_id, prompt, question_type, points e "
        "answer_key; o conjunto cobre todos os resultados e total_points é a "
        "soma exata dos pontos."
    ),
    RESOURCE_PRACTICAL: (
        "Objeto da atividade com title, context, duration_minutes, materials, "
        "steps, deliverables e criteria. As etapas cobrem todos os resultados "
        "e os pesos positivos dos critérios totalizam exatamente 100."
    ),
}


def _scoped_resource_type(state: dict[str, Any] | None) -> str | None:
    if not state or not state.get("resource_generation_scope"):
        return None
    resource_type = str(state["resource_generation_scope"])
    if resource_type not in RESOURCE_ARTIFACT_FIELDS:
        raise AgentGenerationError("O tipo de recurso isolado não é suportado.")
    if list(state.get("resource_types", [])) != [resource_type]:
        raise AgentGenerationError(
            "O âmbito interno da geração não corresponde ao recurso atual."
        )
    return resource_type


def _schema_for(
    stage: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Devolve um esquema JSON com um objeto obrigatório na raiz.

    A Responses API requer um objeto na raiz de um ``json_schema``. Algumas
    etapas do CoerIA produzem naturalmente listas; por isso todas as respostas
    são encapsuladas em ``{\"artifact\": ...}`` e desembrulhadas antes de entrar
    no estado partilhado.
    """

    string = {"type": "string"}
    target_levels = list((*SOLO_LEVELS, *BLOOM_LEVELS))
    content_link = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "content_id": string,
            "importance": {"type": "string", "enum": list(CONTENT_IMPORTANCE)},
        },
        "required": ["content_id", "importance"],
    }
    artifact_schemas: dict[str, dict[str, Any]] = {
        "curriculum_analysis": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": string,
                "themes": {"type": "array", "items": string},
                "objectives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"id": string, "statement": string},
                        "required": ["id", "statement"],
                    },
                },
                "contents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"id": string, "title": string, "description": string},
                        "required": ["id", "title", "description"],
                    },
                },
                "assumptions": {"type": "array", "items": string},
            },
            "required": [
                "summary", "themes", "objectives", "contents", "assumptions"
            ],
        },
        "outcome_taxonomy": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "outcome_id": string,
                    "taxonomy": {
                        "type": "string",
                        "enum": list(TAXONOMY_CHOICES),
                    },
                    "level": {"type": "string", "enum": target_levels},
                    "action_verb": string,
                },
                "required": ["outcome_id", "taxonomy", "level", "action_verb"],
            },
        },
        "learning_outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": string,
                    "theme": string,
                    "statement": string,
                    "action_verb": string,
                    "outcome_type": {"type": "string", "enum": list(OUTCOME_TYPES)},
                    "content_links": {"type": "array", "items": content_link},
                    "objective_ids": {"type": "array", "items": string},
                },
                "required": [
                    "id", "theme", "statement", "action_verb",
                    "outcome_type", "content_links", "objective_ids"
                ],
            },
        },
        "assessment_activities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": string,
                    "outcome_id": string,
                    "outcome_ids": {"type": "array", "items": string},
                    "work_type": string,
                    "assessment_purpose": {
                        "type": "string",
                        "enum": list(ASSESSMENT_PURPOSES),
                    },
                    "activity": string,
                    "evidence": string,
                    "criterion": string,
                },
                "required": [
                    "id", "outcome_id", "outcome_ids", "work_type",
                    "assessment_purpose",
                    "activity", "evidence", "criterion"
                ],
            },
        },
        "pedagogical_design": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "strategy": string,
                "sequence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "outcome_id": string,
                            "focus": string,
                            "assessment": string,
                        },
                        "required": ["outcome_id", "focus", "assessment"],
                    },
                },
            },
            "required": ["strategy", "sequence"],
        },
        "teaching_activities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": string,
                    "outcome_id": string,
                    "outcome_ids": {"type": "array", "items": string},
                    "assessment_ids": {"type": "array", "items": string},
                    "learning_context": {"type": "string", "enum": list(LEARNING_CONTEXTS)},
                    "activity": string,
                    "method": string,
                    "practice": string,
                    "support": string,
                    "feedback_strategy": string,
                },
                "required": [
                    "id", "outcome_id", "outcome_ids", "assessment_ids",
                    "learning_context", "activity", "method", "practice",
                    "support", "feedback_strategy"
                ],
            },
        },
        "alignment_matrix": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "outcome_id": string,
                    "result": string,
                    "objective_ids": {"type": "array", "items": string},
                    "content_ids": {"type": "array", "items": string},
                    "taxonomy": {
                        "type": "string",
                        "enum": list(TAXONOMY_CHOICES),
                    },
                    "taxonomy_level": {"type": "string", "enum": target_levels},
                    "assessment_ids": {"type": "array", "items": string},
                    "assessment_purposes": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(ASSESSMENT_PURPOSES),
                        },
                    },
                    "teaching_activity_ids": {"type": "array", "items": string},
                    "resource_types": {"type": "array", "items": string},
                    "assessment": {"type": "string", "enum": ["Sim", "Não"]},
                    "teaching_activity": {"type": "string", "enum": ["Sim", "Não"]},
                    "status": {
                        "type": "string",
                        "enum": ["Coerente", "Requer revisão"],
                    },
                    "rationale": string,
                },
                "required": [
                    "outcome_id",
                    "result",
                    "objective_ids",
                    "content_ids",
                    "taxonomy",
                    "taxonomy_level",
                    "assessment_ids",
                    "assessment_purposes",
                    "teaching_activity_ids",
                    "resource_types",
                    "assessment",
                    "teaching_activity",
                    "status",
                    "rationale",
                ],
            },
        },
        "resources": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected_types": {"type": "array", "items": string},
                "presentation_outline": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": string,
                            "bullets": {"type": "array", "items": string},
                            "outcome_id": string,
                            "visual_mode": {
                                "type": "string",
                                "enum": ["diagrama", "documento", "ia"],
                            },
                            "visual_asset_id": string,
                            "visual_prompt": string,
                            "visual_kind": {
                                "type": "string",
                                "enum": ["capa", "conceito", "processo", "comparacao", "sintese"],
                            },
                            "visual_title": string,
                            "visual_items": {"type": "array", "items": string},
                            "visual_source": string,
                            "alt_text": string,
                        },
                        "required": [
                            "title", "bullets", "outcome_id", "visual_mode",
                            "visual_asset_id", "visual_prompt", "visual_kind", "visual_title",
                            "visual_items", "visual_source", "alt_text"
                        ],
                    },
                },
                "lesson_worksheet": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": string,
                        "overview": string,
                        "instructions": string,
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "heading": string,
                                    "content": string,
                                    "outcome_ids": {"type": "array", "items": string},
                                    "activity": string,
                                },
                                "required": ["heading", "content", "outcome_ids", "activity"],
                            },
                        },
                    },
                    "required": ["title", "overview", "instructions", "sections"],
                },
                "test": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": string,
                        "instructions": string,
                        "total_points": {"type": "integer"},
                        "questions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": string,
                                    "outcome_id": string,
                                    "prompt": string,
                                    "question_type": string,
                                    "points": {"type": "integer", "minimum": 1},
                                    "answer_key": string,
                                },
                                "required": ["id", "outcome_id", "prompt", "question_type", "points", "answer_key"],
                            },
                        },
                    },
                    "required": ["title", "instructions", "total_points", "questions"],
                },
                "practical_activity": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": string,
                        "context": string,
                        "duration_minutes": {"type": "integer"},
                        "materials": {"type": "array", "items": string},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "order": {"type": "integer"},
                                    "instruction": string,
                                    "outcome_ids": {"type": "array", "items": string},
                                },
                                "required": ["order", "instruction", "outcome_ids"],
                            },
                        },
                        "deliverables": {"type": "array", "items": string},
                        "criteria": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "criterion": string,
                                    "description": string,
                                    "weight": {"type": "integer"},
                                },
                                "required": ["criterion", "description", "weight"],
                            },
                        },
                    },
                    "required": ["title", "context", "duration_minutes", "materials", "steps", "deliverables", "criteria"],
                },
            },
            "required": [
                "selected_types",
                "presentation_outline",
                "lesson_worksheet",
                "test",
                "practical_activity",
            ],
        },
    }
    artifact_schema = artifact_schemas[stage]
    if stage == "learning_outcomes" and state:
        artifact_schema = deepcopy(artifact_schema)
        selected_taxonomy = validate_taxonomy_choice(
            state.get("course", {}).get("taxonomy_type", "SOLO")
        )
        allowed_verbs = [
            verb
            for verbs in TAXONOMY_VERBS[selected_taxonomy].values()
            for verb in verbs
        ]
        content_ids = [
            str(item.get("id", ""))
            for item in state.get("curriculum_analysis", {}).get("contents", [])
            if str(item.get("id", "")).strip()
        ]
        objective_ids = [
            str(item.get("id", ""))
            for item in state.get("curriculum_analysis", {}).get("objectives", [])
            if str(item.get("id", "")).strip()
        ]
        item_schema = artifact_schema["items"]["properties"]
        item_schema["action_verb"] = {
            "type": "string",
            "enum": allowed_verbs,
        }
        if content_ids:
            item_schema["content_links"]["items"]["properties"]["content_id"] = {
                "type": "string",
                "enum": content_ids,
            }
        if objective_ids:
            item_schema["objective_ids"]["items"] = {
                "type": "string",
                "enum": objective_ids,
            }
    scoped_resource_type = (
        _scoped_resource_type(state) if stage == "resources" else None
    )
    if scoped_resource_type:
        resource_field = RESOURCE_ARTIFACT_FIELDS[scoped_resource_type]
        artifact_schema = deepcopy(
            artifact_schemas["resources"]["properties"][resource_field]
        )
        if scoped_resource_type == RESOURCE_TEST and state:
            outcome_ids = [
                str(item["id"])
                for item in state.get("learning_outcomes", [])
                if item.get("id")
            ]
            artifact_schema["properties"]["questions"]["items"]["properties"][
                "outcome_id"
            ] = {"type": "string", "enum": outcome_ids}
        elif scoped_resource_type == RESOURCE_PRACTICAL and state:
            outcome_ids = [
                str(item["id"])
                for item in state.get("learning_outcomes", [])
                if item.get("id")
            ]
            artifact_schema["properties"]["steps"]["items"]["properties"][
                "outcome_ids"
            ]["items"] = {"type": "string", "enum": outcome_ids}
            artifact_schema["properties"]["duration_minutes"]["minimum"] = 1
            artifact_schema["properties"]["steps"]["items"]["properties"][
                "order"
            ]["minimum"] = 1
            artifact_schema["properties"]["criteria"]["items"]["properties"][
                "weight"
            ].update({"minimum": 1, "maximum": 100})

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"artifact": artifact_schema},
        "required": ["artifact"],
    }


def _upstream_context(state: dict[str, Any], stage: str) -> dict[str, Any]:
    """Inclui apenas os dados pedagógicos relevantes na chamada ao modelo."""

    stage_order = (
        "curriculum_analysis",
        "learning_outcomes",
        "outcome_taxonomy",
        "assessment_activities",
        "pedagogical_design",
        "teaching_activities",
        "alignment_matrix",
        "resources",
    )
    stage_index = stage_order.index(stage)
    context = {
        "course": state["course"],
        "feedback_from_teacher": state.get("feedback", {}).get(stage, ""),
        "requested_resource_types": state.get("resource_types", []),
    }
    for artifact_stage in stage_order[:stage_index]:
        if artifact_stage in state:
            context[artifact_stage] = state[artifact_stage]
    if stage == "learning_outcomes":
        curriculum = state.get("curriculum_analysis", {})
        context["learning_outcome_coverage_rules"] = {
            "required_content_ids": [
                item["id"] for item in curriculum.get("contents", [])
            ],
            "required_objective_ids": [
                item["id"] for item in curriculum.get("objectives", [])
            ],
            "rule": (
                "A união de content_links.content_id deve ser exatamente a lista de "
                "required_content_ids e a união de objective_ids deve ser exatamente a "
                "lista de required_objective_ids. Não omitir nem inventar IDs."
            ),
        }
    if stage == "outcome_taxonomy":
        selected_taxonomy = validate_taxonomy_choice(
            state["course"].get("taxonomy_type", "SOLO")
        )
        context["required_taxonomy_mapping"] = [
            {
                "outcome_id": outcome["id"],
                "taxonomy": selected_taxonomy,
                "level": taxonomy_level_for_verb(
                    selected_taxonomy, outcome["action_verb"]
                ),
                "action_verb": outcome["action_verb"],
            }
            for outcome in state.get("learning_outcomes", [])
        ]
    if stage == "assessment_activities":
        context["assessment_link_rules"] = {
            "allowed_outcome_ids": [
                outcome["id"] for outcome in state.get("learning_outcomes", [])
            ],
            "rule": (
                "Cada outcome_ids deve conter pelo menos um ID permitido e "
                "outcome_id deve ser exatamente o primeiro elemento de outcome_ids."
            ),
            "allowed_purposes": list(ASSESSMENT_PURPOSES),
            "mixed_purpose_forbidden": True,
        }
    if stage == "alignment_matrix":
        context["required_alignment_mapping"] = list(
            _expected_alignment_rows(state).values()
        )
    if stage == "resources" and "Apresentação PowerPoint" in state.get(
        "resource_types", []
    ):
        source_images = []
        selected_source_ids = {
            str(item).strip()
            for item in state.get("selected_source_image_ids", [])
            if str(item).strip()
        }
        for asset in state.get("source_images", []):
            if not isinstance(asset, dict) or not str(asset.get("id", "")).strip():
                continue
            if str(asset.get("id", "")).strip() not in selected_source_ids:
                continue
            source_images.append(
                {
                    "id": str(asset.get("id", "")),
                    "source_file": str(asset.get("source_file", "")),
                    "source_location": str(asset.get("source_location", "")),
                    "filename": str(asset.get("filename", "")),
                    "media_type": str(asset.get("media_type", "")),
                    "candidate_kind": str(asset.get("candidate_kind", "embedded")),
                    "width_px": int(asset.get("width_px", 0) or 0),
                    "height_px": int(asset.get("height_px", 0) or 0),
                }
            )
        context["source_image_catalogue"] = source_images
        context["ai_image_generation"] = {
            "enabled": bool(state.get("ai_image_generation_enabled")),
            "rule": (
                "Usar apenas quando a imagem acrescenta valor pedagógico real; "
                "a aplicação limita e valida a geração antes da exportação."
            ),
        }
    return context


def _canonicalize_outcome_taxonomy(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Aplica a correspondência canónica entre verbo, nível e taxonomia.

    A cobertura dos resultados continua a ser validada separadamente. Esta
    proteção corrige apenas campos que são totalmente determinados pelo verbo
    já aprovado pelo docente na etapa anterior.
    """

    if not isinstance(artifact, list):
        return artifact, []
    selected_taxonomy = validate_taxonomy_choice(
        state["course"].get("taxonomy_type", "SOLO")
    )
    outcomes = {item["id"]: item for item in state.get("learning_outcomes", [])}
    normalized: list[Any] = []
    corrections: list[dict[str, Any]] = []
    for item in artifact:
        if not isinstance(item, dict) or item.get("outcome_id") not in outcomes:
            normalized.append(item)
            continue
        outcome = outcomes[item["outcome_id"]]
        canonical = {
            "taxonomy": selected_taxonomy,
            "level": taxonomy_level_for_verb(
                selected_taxonomy, outcome["action_verb"]
            ),
            "action_verb": outcome["action_verb"],
        }
        changes = {
            field: {"received": item.get(field), "used": value}
            for field, value in canonical.items()
            if item.get(field) != value
        }
        normalized.append({**item, **canonical})
        if changes:
            corrections.append(
                {"outcome_id": item["outcome_id"], "changes": changes}
            )
    return normalized, corrections


def _canonicalize_assessment_activities(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Normaliza ligações redundantes sem inventar cobertura curricular."""

    if not isinstance(artifact, list):
        return artifact, []
    allowed = {item["id"] for item in state.get("learning_outcomes", [])}
    normalized: list[Any] = []
    corrections: list[dict[str, Any]] = []
    for item in artifact:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        primary = str(item.get("outcome_id", ""))
        raw_links = item.get("outcome_ids") or ([primary] if primary else [])
        links = list(
            dict.fromkeys(str(identifier) for identifier in raw_links if identifier in allowed)
        )
        if primary in allowed:
            links = [primary, *(identifier for identifier in links if identifier != primary)]
        canonical_primary = links[0] if links else primary
        purpose = str(item.get("assessment_purpose", ""))
        canonical_purpose = next(
            (
                allowed_purpose
                for allowed_purpose in ASSESSMENT_PURPOSES
                if purpose.casefold() == allowed_purpose.casefold()
            ),
            purpose,
        )
        canonical = {
            "outcome_id": canonical_primary,
            "outcome_ids": links,
            "assessment_purpose": canonical_purpose,
        }
        changes = {
            field: {"received": item.get(field), "used": value}
            for field, value in canonical.items()
            if item.get(field) != value
        }
        normalized.append({**item, **canonical})
        if changes:
            corrections.append(
                {"assessment_id": item.get("id", ""), "changes": changes}
            )
    return normalized, corrections


def _expected_alignment_rows(
    state: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    outcomes = {
        item["id"]: item for item in state.get("learning_outcomes", [])
    }
    taxonomy = {
        item["outcome_id"]: item for item in state.get("outcome_taxonomy", [])
    }
    rows: dict[str, dict[str, Any]] = {}
    for outcome_id, outcome in outcomes.items():
        assessment_items = [
            item
            for item in state.get("assessment_activities", [])
            if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
        ]
        teaching_items = [
            item
            for item in state.get("teaching_activities", [])
            if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
        ]
        assessment_ids = sorted(item["id"] for item in assessment_items)
        teaching_ids = sorted(item["id"] for item in teaching_items)
        has_assessment = bool(assessment_ids)
        has_teaching = bool(teaching_ids)
        classification = taxonomy.get(outcome_id, {})
        rows[outcome_id] = {
            "outcome_id": outcome_id,
            "result": outcome["statement"],
            "objective_ids": list(outcome.get("objective_ids", [])),
            "content_ids": [
                link["content_id"] for link in outcome.get("content_links", [])
            ],
            "taxonomy": classification.get("taxonomy", ""),
            "taxonomy_level": classification.get("level", ""),
            "assessment_ids": assessment_ids,
            "assessment_purposes": sorted(
                {item["assessment_purpose"] for item in assessment_items}
            ),
            "teaching_activity_ids": teaching_ids,
            "resource_types": list(state.get("resource_types", [])),
            "assessment": "Sim" if has_assessment else "Não",
            "teaching_activity": "Sim" if has_teaching else "Não",
            "status": "Coerente" if has_assessment and has_teaching else "Requer revisão",
        }
    return rows


def _canonicalize_alignment_matrix(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Substitui campos derivados por ligações calculadas dos artefactos aprovados."""

    if not isinstance(artifact, list):
        return artifact, []
    expected = _expected_alignment_rows(state)
    normalized: list[Any] = []
    corrections: list[dict[str, Any]] = []
    for item in artifact:
        if not isinstance(item, dict) or item.get("outcome_id") not in expected:
            normalized.append(item)
            continue
        canonical = expected[item["outcome_id"]]
        rationale = str(item.get("rationale", "")).strip() or (
            "Estado calculado a partir das avaliações e atividades formativas "
            "associadas ao resultado."
        )
        corrected = {**item, **canonical, "rationale": rationale}
        changes = {
            field: {"received": item.get(field), "used": value}
            for field, value in canonical.items()
            if item.get(field) != value
        }
        normalized.append(corrected)
        if changes:
            corrections.append(
                {"outcome_id": item["outcome_id"], "changes": changes}
            )
    return normalized, corrections


def _expand_scoped_resource_payload(
    payload: Any,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Acrescenta deterministicamente a seleção e os recursos não pedidos."""

    resource_type = _scoped_resource_type(state)
    if resource_type is None:
        return payload

    resource_field = RESOURCE_ARTIFACT_FIELDS[resource_type]
    resource_payload = (
        payload[resource_field]
        if isinstance(payload, dict) and resource_field in payload
        else payload
    )
    artifact = {
        "selected_types": [resource_type],
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
    }
    artifact[resource_field] = resource_payload
    return artifact


def _canonicalize_resource_test(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Deriva IDs técnicos e cotação total das questões devolvidas."""

    if (
        not isinstance(artifact, dict)
        or RESOURCE_TEST not in state.get("resource_types", [])
    ):
        return artifact, []
    test = artifact.get("test")
    if not isinstance(test, dict) or not isinstance(test.get("questions"), list):
        return artifact, []

    normalized_questions: list[Any] = []
    corrections: list[dict[str, Any]] = []
    total_points = 0
    for index, question in enumerate(test["questions"], start=1):
        if not isinstance(question, dict):
            normalized_questions.append(question)
            continue
        normalized = deepcopy(question)
        canonical_id = f"Q{index}"
        if normalized.get("id") != canonical_id:
            corrections.append(
                {
                    "question": index,
                    "changes": {
                        "id": {
                            "received": normalized.get("id"),
                            "used": canonical_id,
                        }
                    },
                }
            )
            normalized["id"] = canonical_id
        points = normalized.get("points")
        if isinstance(points, int):
            total_points += points
        normalized_questions.append(normalized)

    normalized_artifact = deepcopy(artifact)
    normalized_artifact["test"]["questions"] = normalized_questions
    received_total = normalized_artifact["test"].get("total_points")
    if received_total != total_points:
        corrections.append(
            {
                "resource": RESOURCE_TEST,
                "changes": {
                    "total_points": {
                        "received": received_total,
                        "used": total_points,
                    }
                },
            }
        )
        normalized_artifact["test"]["total_points"] = total_points
    return normalized_artifact, corrections


def _positive_percentages(weights: list[int]) -> list[int] | None:
    """Distribui 100 pontos por critérios, preservando as proporções recebidas."""

    if not weights or len(weights) > 100:
        return None
    positive = [max(weight, 1) for weight in weights]
    distributable = 100 - len(positive)
    total = sum(positive)
    quotients: list[int] = []
    remainders: list[tuple[int, int]] = []
    for index, weight in enumerate(positive):
        quotient, remainder = divmod(weight * distributable, total)
        quotients.append(quotient)
        remainders.append((remainder, index))
    missing = distributable - sum(quotients)
    recipients = {
        index
        for _remainder, index in sorted(
            remainders,
            key=lambda item: (-item[0], item[1]),
        )[:missing]
    }
    return [
        1 + quotient + (1 if index in recipients else 0)
        for index, quotient in enumerate(quotients)
    ]


def _canonicalize_resource_practical(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Repara ligações técnicas e ponderações da atividade prática."""

    if (
        not isinstance(artifact, dict)
        or RESOURCE_PRACTICAL not in state.get("resource_types", [])
    ):
        return artifact, []
    practical = artifact.get("practical_activity")
    if not isinstance(practical, dict):
        return artifact, []

    outcomes = [
        item
        for item in state.get("learning_outcomes", [])
        if isinstance(item, dict) and item.get("id")
    ]
    expected_ids = [str(item["id"]) for item in outcomes]
    expected = set(expected_ids)
    statements = {
        str(item["id"]): str(item.get("statement", "")).strip()
        for item in outcomes
    }
    steps = practical.get("steps")
    criteria = practical.get("criteria")
    if not isinstance(steps, list) or not isinstance(criteria, list):
        return artifact, []

    normalized_artifact = deepcopy(artifact)
    normalized_practical = normalized_artifact["practical_activity"]
    normalized_steps: list[Any] = []
    corrections: list[dict[str, Any]] = []
    covered: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            normalized_steps.append(step)
            continue
        normalized = deepcopy(step)
        received_ids = step.get("outcome_ids", [])
        received_ids = received_ids if isinstance(received_ids, list) else []
        valid_ids: list[str] = []
        for outcome_id in received_ids:
            identifier = str(outcome_id)
            if identifier in expected and identifier not in valid_ids:
                valid_ids.append(identifier)
        changes: dict[str, Any] = {}
        if received_ids != valid_ids:
            changes["outcome_ids"] = {
                "received": received_ids,
                "used": valid_ids,
            }
            normalized["outcome_ids"] = valid_ids
        if normalized.get("order") != index:
            changes["order"] = {
                "received": normalized.get("order"),
                "used": index,
            }
            normalized["order"] = index
        if changes:
            corrections.append({"step": index, "changes": changes})
        covered.update(valid_ids)
        normalized_steps.append(normalized)

    for outcome_id in expected_ids:
        if outcome_id in covered:
            continue
        statement = statements.get(outcome_id) or "demonstrar o resultado previsto"
        added_step = {
            "order": len(normalized_steps) + 1,
            "instruction": (
                f"Aplicar e demonstrar o resultado {outcome_id}: {statement}. "
                "Integrar a evidência no entregável final."
            ),
            "outcome_ids": [outcome_id],
        }
        normalized_steps.append(added_step)
        covered.add(outcome_id)
        corrections.append(
            {
                "resource": RESOURCE_PRACTICAL,
                "added_step_for_outcome": outcome_id,
            }
        )
    normalized_practical["steps"] = normalized_steps

    normalized_criteria = [
        deepcopy(item) for item in criteria if isinstance(item, dict)
    ]
    if not normalized_criteria:
        normalized_criteria = [
            {
                "criterion": "Demonstração dos resultados de aprendizagem",
                "description": (
                    "Qualidade e completude das evidências apresentadas para "
                    + ", ".join(expected_ids)
                    + "."
                ),
                "weight": 100,
            }
        ]
        corrections.append(
            {
                "resource": RESOURCE_PRACTICAL,
                "changes": {"criteria": {"received": criteria, "used": "1 critério"}},
            }
        )
    else:
        received_weights = [
            item.get("weight") if isinstance(item.get("weight"), int) else 0
            for item in normalized_criteria
        ]
        normalized_weights = _positive_percentages(received_weights)
        if normalized_weights is not None and received_weights != normalized_weights:
            for item, weight in zip(normalized_criteria, normalized_weights):
                item["weight"] = weight
            corrections.append(
                {
                    "resource": RESOURCE_PRACTICAL,
                    "changes": {
                        "criteria_weights": {
                            "received": received_weights,
                            "used": normalized_weights,
                        }
                    },
                }
            )
    normalized_practical["criteria"] = normalized_criteria
    return normalized_artifact, corrections


def _canonicalize_resource_visuals(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Completa e valida deterministicamente a especificação visual dos slides.

    Os diagramas nativos continuam sempre disponíveis como fallback editável. Uma
    imagem documental só é selecionada quando o fornecedor devolve um ID que existe
    realmente no catálogo extraído da sessão. A capa e o slide final permanecem com
    diagrama nativo para preservar a composição institucional da apresentação.
    """

    if not isinstance(artifact, dict):
        return artifact, []
    requested = set(state.get("resource_types", []))
    slides = artifact.get("presentation_outline")
    if "Apresentação PowerPoint" not in requested or not isinstance(slides, list):
        return artifact, []

    allowed_kinds = {"capa", "conceito", "processo", "comparacao", "sintese"}
    kind_aliases = {"comparação": "comparacao", "síntese": "sintese"}
    mode_aliases = {
        "diagram": "diagrama",
        "diagrama": "diagrama",
        "document": "documento",
        "documento": "documento",
        "imagem": "documento",
        "image": "documento",
        "ia": "ia",
        "ai": "ia",
        "gerada": "ia",
        "imagem gerada": "ia",
        "imagem_ia": "ia",
    }
    outcomes = {
        str(item.get("id", "")): item
        for item in state.get("learning_outcomes", [])
        if item.get("id")
    }
    selected_source_ids = {
        str(item).strip()
        for item in state.get("selected_source_image_ids", [])
        if str(item).strip()
    }
    source_assets = {
        str(item.get("id", "")): item
        for item in state.get("source_images", [])
        if isinstance(item, dict)
        and str(item.get("id", "")).strip()
        and str(item.get("id", "")).strip() in selected_source_ids
    }

    def clean_text(value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    def compact_item(value: Any) -> str:
        text = clean_text(value)
        return text if len(text) <= 80 else text[:79].rstrip() + "…"

    def linked_value(items: list[dict[str, Any]], outcome_id: str, key: str) -> str:
        for item in items:
            if outcome_id in item.get("outcome_ids", [item.get("outcome_id")]):
                return compact_item(item.get(key))
        return ""

    normalized_slides: list[Any] = []
    corrections: list[dict[str, Any]] = []
    slide_count = len(slides)
    for offset, slide in enumerate(slides):
        if not isinstance(slide, dict):
            normalized_slides.append(slide)
            continue

        outcome_id = str(slide.get("outcome_id", ""))
        raw_kind = clean_text(slide.get("visual_kind")).casefold()
        canonical_kind = kind_aliases.get(raw_kind, raw_kind)
        if canonical_kind not in allowed_kinds:
            if offset == 0:
                canonical_kind = "capa"
            elif offset == slide_count - 1 and not outcome_id:
                canonical_kind = "sintese"
            else:
                canonical_kind = ("processo", "conceito", "comparacao")[
                    max(offset - 1, 0) % 3
                ]

        visual_title = clean_text(slide.get("visual_title")) or clean_text(
            slide.get("title")
        )
        if not visual_title:
            visual_title = f"Representação visual do slide {offset + 1}"

        raw_items = slide.get("visual_items", [])
        if not isinstance(raw_items, list):
            raw_items = [raw_items]
        clean_raw_items = [clean_text(item) for item in raw_items]
        if (
            2 <= len(clean_raw_items) <= 4
            and all(clean_raw_items)
            and len({item.casefold() for item in clean_raw_items})
            == len(clean_raw_items)
        ):
            visual_items = clean_raw_items
        else:
            candidates: list[Any] = list(raw_items)
            outcome = outcomes.get(outcome_id, {})
            if outcome:
                candidates.extend(
                    [
                        outcome.get("theme"),
                        linked_value(
                            state.get("teaching_activities", []), outcome_id, "method"
                        ),
                        linked_value(
                            state.get("assessment_activities", []),
                            outcome_id,
                            "assessment_purpose",
                        ),
                    ]
                )
            bullets = slide.get("bullets", [])
            if isinstance(bullets, list):
                candidates.extend(bullets)
            candidates.extend(
                [
                    "Conteúdo principal",
                    "Aplicação pedagógica",
                    "Evidência de aprendizagem",
                ]
            )

            visual_items = []
            seen_items: set[str] = set()
            for candidate in candidates:
                item = compact_item(candidate)
                key = item.casefold()
                if not item or key in seen_items:
                    continue
                visual_items.append(item)
                seen_items.add(key)
                if len(visual_items) == 4:
                    break

        raw_mode = mode_aliases.get(
            clean_text(slide.get("visual_mode")).casefold(),
            clean_text(slide.get("visual_mode")).casefold(),
        )
        raw_asset_id = clean_text(slide.get("visual_asset_id"))
        is_boundary_slide = offset == 0 or offset == slide_count - 1
        visual_prompt = clean_text(slide.get("visual_prompt"))
        ai_enabled = bool(state.get("ai_image_generation_enabled"))
        if (
            not is_boundary_slide
            and raw_mode == "documento"
            and raw_asset_id in source_assets
        ):
            visual_mode = "documento"
            visual_asset_id = raw_asset_id
            visual_prompt = ""
            asset = source_assets[visual_asset_id]
            source_file = clean_text(asset.get("source_file")) or "documento fornecido"
            source_location = clean_text(asset.get("source_location"))
            visual_source = f"Imagem extraída de {source_file}"
            if source_location:
                visual_source += f", {source_location}"
            visual_source += "."
        elif (
            not is_boundary_slide
            and raw_mode == "ia"
            and ai_enabled
            and visual_prompt
        ):
            visual_mode = "ia"
            visual_asset_id = ""
            visual_source = "Imagem proposta para geração por IA, sujeita a validação do docente."
        else:
            visual_mode = "diagrama"
            visual_asset_id = ""
            visual_prompt = ""
            visual_source = clean_text(slide.get("visual_source")) or (
                "Diagrama nativo gerado pelo CoerIA a partir dos artefactos aprovados."
            )

        alt_text = clean_text(slide.get("alt_text"))
        if not alt_text:
            if visual_mode == "documento":
                alt_text = f"Imagem documental associada a {visual_title}."
            elif visual_mode == "ia":
                alt_text = f"Imagem gerada por IA associada a {visual_title}."
            else:
                alt_text = (
                    f"Diagrama «{visual_title}» com os elementos "
                    + ", ".join(visual_items)
                    + "."
                )
        canonical = {
            "visual_mode": visual_mode,
            "visual_asset_id": visual_asset_id,
            "visual_prompt": visual_prompt,
            "visual_kind": canonical_kind,
            "visual_title": visual_title,
            "visual_items": visual_items,
            "visual_source": visual_source,
            "alt_text": alt_text,
        }
        changes = {
            field: {"received": slide.get(field), "used": value}
            for field, value in canonical.items()
            if slide.get(field) != value
        }
        normalized_slides.append({**slide, **canonical})
        if changes:
            corrections.append({"slide": offset + 1, "changes": changes})

    return {**artifact, "presentation_outline": normalized_slides}, corrections

def _require_exact_coverage(
    artifact: list[dict[str, Any]], expected: set[str], key: str, message: str
) -> None:
    received_list = [str(item.get(key, "")) for item in artifact]
    received = set(received_list)
    if received != expected or len(received_list) != len(received):
        raise AgentGenerationError(message)


def _flattened_ids(artifact: list[dict[str, Any]], plural_key: str, legacy_key: str) -> list[str]:
    return [
        str(identifier)
        for item in artifact
        for identifier in (item.get(plural_key) or [item.get(legacy_key, "")])
        if identifier
    ]


def _validate_artifact(stage: str, artifact: Any, state: dict[str, Any]) -> None:
    if stage == "curriculum_analysis":
        contents = artifact.get("contents", []) if isinstance(artifact, dict) else []
        objectives = artifact.get("objectives", []) if isinstance(artifact, dict) else []
        content_ids = [item.get("id") for item in contents]
        objective_ids = [item.get("id") for item in objectives]
        if (
            not MIN_OUTCOMES <= len(contents) <= MAX_OUTCOMES
            or len(content_ids) != len(set(content_ids))
            or any(not item.get("title") for item in contents)
            or not objectives
            or len(objective_ids) != len(set(objective_ids))
            or any(not item.get("statement") for item in objectives)
            or any(
                not re.fullmatch(r"OG[1-9]\d*", str(identifier or ""))
                for identifier in objective_ids
            )
        ):
            raise AgentGenerationError(
                "A análise curricular deve conter conteúdos e objetivos com IDs únicos."
            )
        return

    if stage in {
        "learning_outcomes",
        "outcome_taxonomy",
        "assessment_activities",
        "teaching_activities",
        "alignment_matrix",
    }:
        if not isinstance(artifact, list) or not artifact:
            raise AgentGenerationError("O agente devolveu uma lista vazia para esta etapa.")

    if stage == "outcome_taxonomy":
        expected_outcome_ids = {item["id"] for item in state["learning_outcomes"]}
        _require_exact_coverage(
            artifact,
            expected_outcome_ids,
            "outcome_id",
            "A classificação taxonómica não cobre exatamente os resultados.",
        )
        selected_taxonomy = validate_taxonomy_choice(
            state["course"].get("taxonomy_type", "SOLO")
        )
        outcome_by_id = {item["id"]: item for item in state["learning_outcomes"]}
        invalid_details = []
        for item in artifact:
            outcome = outcome_by_id[item["outcome_id"]]
            expected_verb = outcome["action_verb"]
            expected_level = taxonomy_level_for_verb(
                selected_taxonomy, expected_verb
            )
            if (
                item["taxonomy"] != selected_taxonomy
                or item["level"] != expected_level
                or item["action_verb"] != expected_verb
                or not taxonomy_verb_allowed(
                    selected_taxonomy, item["level"], item["action_verb"]
                )
            ):
                invalid_details.append(
                    f"{item['outcome_id']} deve usar {selected_taxonomy} / "
                    f"{expected_level} / {expected_verb}"
                )
        if invalid_details:
            raise AgentGenerationError(
                "A classificação usa outra taxonomia ou verbos incompatíveis: "
                + "; ".join(invalid_details)
            )

    if stage == "learning_outcomes":
        if not MIN_OUTCOMES <= len(artifact) <= MAX_OUTCOMES:
            raise AgentGenerationError("Devem existir entre 4 e 10 resultados de aprendizagem.")
        outcome_ids = [item["id"] for item in artifact]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise AgentGenerationError("Os resultados de aprendizagem contêm IDs duplicados.")

        expected_contents = {
            item["id"] for item in state["curriculum_analysis"]["contents"]
        }
        linked_contents = {
            link["content_id"] for item in artifact for link in item.get("content_links", [])
        }
        if linked_contents != expected_contents:
            missing = sorted(expected_contents - linked_contents)
            unknown = sorted(linked_contents - expected_contents)
            details = []
            if missing:
                details.append("em falta: " + ", ".join(missing))
            if unknown:
                details.append("IDs desconhecidos: " + ", ".join(unknown))
            raise AgentGenerationError(
                "Os resultados devem cobrir todos e apenas os conteúdos curriculares"
                + (" (" + "; ".join(details) + ")" if details else "")
                + "."
            )
        expected_objectives = {
            item["id"] for item in state["curriculum_analysis"]["objectives"]
        }
        linked_objectives = {
            identifier
            for item in artifact
            for identifier in item.get("objective_ids", [])
        }
        if linked_objectives != expected_objectives:
            missing = sorted(expected_objectives - linked_objectives)
            unknown = sorted(linked_objectives - expected_objectives)
            details = []
            if missing:
                details.append("em falta: " + ", ".join(missing))
            if unknown:
                details.append("IDs desconhecidos: " + ", ".join(unknown))
            raise AgentGenerationError(
                "Os resultados devem cobrir todos e apenas os objetivos gerais"
                + (" (" + "; ".join(details) + ")" if details else "")
                + "."
            )
        taxonomy_type = validate_taxonomy_choice(
            state["course"].get("taxonomy_type", "SOLO")
        )
        invalid = [
            item["id"] for item in artifact
            if not has_single_action_verb(
                item["statement"], item["action_verb"], taxonomy_type
            )
        ]
        if invalid:
            invalid_by_id = {item["id"]: item for item in artifact if item["id"] in invalid}
            details = "; ".join(
                f"{identifier}: verbo='{invalid_by_id[identifier].get('action_verb', '')}', "
                f"enunciado='{invalid_by_id[identifier].get('statement', '')}'"
                for identifier in invalid
            )
            raise AgentGenerationError(
                "Cada resultado deve começar pelo action_verb declarado e conter "
                "exatamente um verbo de ação controlado, sem coordenações do tipo "
                "'e/ou + infinitivo'. Corrigir: " + details
            )

    if stage in {"assessment_activities", "teaching_activities"}:
        expected = {item["id"] for item in state["learning_outcomes"]}
        covered = set(_flattened_ids(artifact, "outcome_ids", "outcome_id"))
        identifiers = [item["id"] for item in artifact]
        if covered != expected or len(identifiers) != len(set(identifiers)):
            raise AgentGenerationError(
                "A proposta deve ter IDs únicos e cobrir todos e apenas os resultados definidos."
            )

    if stage == "assessment_activities":
        invalid_assessments = []
        for item in artifact:
            problems = []
            if not item.get("outcome_ids"):
                problems.append("outcome_ids vazio")
            elif item.get("outcome_id") != item["outcome_ids"][0]:
                problems.append("outcome_id não é o primeiro elemento de outcome_ids")
            if item.get("assessment_purpose") not in ASSESSMENT_PURPOSES:
                problems.append("finalidade diferente de Formativa ou Sumativa")
            if problems:
                invalid_assessments.append(
                    f"{item.get('id', '?')}: " + ", ".join(problems)
                )
        if invalid_assessments:
            raise AgentGenerationError(
                "Cada avaliação deve ser Formativa ou Sumativa e manter ligações "
                "válidas. " + "; ".join(invalid_assessments)
            )

    if stage == "teaching_activities":
        expected_assessments = {item["id"] for item in state["assessment_activities"]}
        covered_assessments = {
            identifier for item in artifact for identifier in item.get("assessment_ids", [])
        }
        if covered_assessments != expected_assessments:
            raise AgentGenerationError(
                "As atividades de ensino devem cobrir todas e apenas as avaliações definidas."
            )
        if any(
            not item.get("practice")
            or not item.get("support")
            or not item.get("feedback_strategy")
            for item in artifact
        ):
            raise AgentGenerationError(
                "Cada atividade formativa deve explicitar prática, acompanhamento e feedback."
            )

    if stage == "alignment_matrix":
        expected = {item["id"] for item in state["learning_outcomes"]}
        _require_exact_coverage(
            artifact, expected, "outcome_id",
            "A matriz não cobre exatamente os resultados de aprendizagem definidos."
        )

        inconsistent = [
            item["outcome_id"]
            for item in artifact
            if (
                item["assessment"] == "Sim" and item["teaching_activity"] == "Sim"
            )
            != (item["status"] == "Coerente")
        ]
        if inconsistent:
            raise AgentGenerationError(
                "A matriz contém estados incompatíveis com as evidências de alinhamento: "
                + ", ".join(inconsistent)
            )
        outcome_by_id = {item["id"]: item for item in state["learning_outcomes"]}
        taxonomy_by_outcome = {
            item["outcome_id"]: item for item in state["outcome_taxonomy"]
        }
        assessment_by_outcome = {
            outcome_id: sorted(
                item["id"] for item in state["assessment_activities"]
                if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
            )
            for outcome_id in expected
        }
        teaching_by_outcome = {
            outcome_id: sorted(
                item["id"] for item in state["teaching_activities"]
                if outcome_id in item.get("outcome_ids", [item.get("outcome_id")])
            )
            for outcome_id in expected
        }
        divergent = [
            row["outcome_id"] for row in artifact
            if sorted(row["objective_ids"])
            != sorted(outcome_by_id[row["outcome_id"]].get("objective_ids", []))
            or sorted(row["content_ids"]) != sorted(
                link["content_id"] for link in outcome_by_id[row["outcome_id"]]["content_links"]
            )
            or row["taxonomy"]
            != taxonomy_by_outcome[row["outcome_id"]]["taxonomy"]
            or row["taxonomy_level"]
            != taxonomy_by_outcome[row["outcome_id"]]["level"]
            or sorted(row["assessment_ids"]) != assessment_by_outcome[row["outcome_id"]]
            or sorted(row["assessment_purposes"])
            != sorted(
                {
                    item["assessment_purpose"]
                    for item in state["assessment_activities"]
                    if row["outcome_id"]
                    in item.get("outcome_ids", [item.get("outcome_id")])
                }
            )
            or sorted(row["teaching_activity_ids"]) != teaching_by_outcome[row["outcome_id"]]
            or sorted(row["resource_types"]) != sorted(state.get("resource_types", []))
        ]
        if divergent:
            raise AgentGenerationError(
                "A matriz diverge das ligações reais em: " + ", ".join(divergent)
            )

    if stage == "pedagogical_design":
        expected = {item["id"] for item in state["learning_outcomes"]}
        _require_exact_coverage(
            artifact.get("sequence", []),
            expected,
            "outcome_id",
            "O design pedagógico não contempla todos os resultados de aprendizagem.",
        )

    if stage == "resources":
        selected = set(artifact["selected_types"])
        requested = set(state.get("resource_types", []))
        if selected != requested or len(artifact["selected_types"]) != len(selected):
            raise AgentGenerationError("Os recursos devolvidos não respeitam a seleção do docente.")

        resource_content = {
            "Apresentação PowerPoint": artifact["presentation_outline"],
            "Ficha de aula": artifact["lesson_worksheet"]["sections"],
            "Teste": artifact["test"]["questions"],
            "Atividade prática": artifact["practical_activity"]["steps"],
        }
        for resource_type, content in resource_content.items():
            if (resource_type in requested) != bool(content):
                raise AgentGenerationError(
                    f"O conteúdo de {resource_type} não corresponde à seleção do docente."
                )

        if "Apresentação PowerPoint" in requested:
            allowed_visual_kinds = {
                "capa",
                "conceito",
                "processo",
                "comparacao",
                "sintese",
            }
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
            generated_asset_ids = set(generated_assets)
            pending_ai_allowed = bool(
                state.get("resource_generation_scope")
                and state.get("ai_image_generation_enabled")
            )
            invalid_slides = []
            for index, slide in enumerate(artifact["presentation_outline"], start=1):
                visual_items = slide.get("visual_items", [])
                valid_items = (
                    2 <= len(visual_items) <= 4
                    and all(str(item).strip() for item in visual_items)
                )
                visual_mode = str(slide.get("visual_mode", ""))
                visual_asset_id = str(slide.get("visual_asset_id", "")).strip()
                visual_prompt = str(slide.get("visual_prompt", "")).strip()
                valid_mode = visual_mode in {"diagrama", "documento", "ia"}
                valid_asset = (
                    visual_mode == "diagrama" and not visual_asset_id
                ) or (
                    visual_mode == "documento"
                    and visual_asset_id in source_asset_ids
                ) or (
                    visual_mode == "ia"
                    and bool(state.get("ai_image_generation_enabled"))
                    and (
                        (
                            visual_asset_id in generated_asset_ids
                            and bool(str(generated_assets[visual_asset_id].get("prompt", "")).strip())
                        )
                        or (
                            pending_ai_allowed
                            and not visual_asset_id
                            and bool(visual_prompt)
                        )
                    )
                )
                if (
                    slide.get("visual_kind") not in allowed_visual_kinds
                    or not str(slide.get("visual_title", "")).strip()
                    or not valid_items
                    or not str(slide.get("visual_source", "")).strip()
                    or not str(slide.get("alt_text", "")).strip()
                    or not valid_mode
                    or not valid_asset
                ):
                    invalid_slides.append(str(index))
            if invalid_slides:
                raise AgentGenerationError(
                    "A especificação visual está incompleta nos slides: "
                    + ", ".join(invalid_slides)
                    + "."
                )

        expected = {item["id"] for item in state["learning_outcomes"]}
        if "Teste" in requested:
            question_ids = [item["id"] for item in artifact["test"]["questions"]]
            if len(question_ids) != len(set(question_ids)):
                raise AgentGenerationError("O teste contém identificadores de questão duplicados.")
            covered = {item["outcome_id"] for item in artifact["test"]["questions"]}
            if covered != expected:
                missing = sorted(expected - covered)
                unexpected = sorted(covered - expected)
                details = []
                if missing:
                    details.append("IDs em falta: " + ", ".join(missing))
                if unexpected:
                    details.append(
                        "IDs não permitidos: " + ", ".join(unexpected)
                    )
                raise AgentGenerationError(
                    "O teste não cobre exatamente todos os resultados de "
                    "aprendizagem. " + "; ".join(details) + "."
                )
            points = sum(item["points"] for item in artifact["test"]["questions"])
            if (
                points != artifact["test"]["total_points"]
                or points <= 0
                or any(item["points"] <= 0 for item in artifact["test"]["questions"])
            ):
                raise AgentGenerationError(
                    "O teste deve apresentar pontos positivos e uma cotação total coerente."
                )

        if "Atividade prática" in requested:
            covered = {
                outcome_id
                for step in artifact["practical_activity"]["steps"]
                for outcome_id in step["outcome_ids"]
            }
            weight = sum(item["weight"] for item in artifact["practical_activity"]["criteria"])
            steps = artifact["practical_activity"]["steps"]
            problems = []
            if covered != expected:
                missing = sorted(expected - covered)
                unexpected = sorted(covered - expected)
                if missing:
                    problems.append("IDs em falta: " + ", ".join(missing))
                if unexpected:
                    problems.append("IDs não permitidos: " + ", ".join(unexpected))
            if weight != 100:
                problems.append(f"a soma dos critérios é {weight}%")
            if artifact["practical_activity"]["duration_minutes"] <= 0:
                problems.append("a duração deve ser positiva")
            if any(item["order"] <= 0 for item in steps):
                problems.append("a ordem das etapas deve ser positiva")
            if any(
                item["weight"] <= 0
                for item in artifact["practical_activity"]["criteria"]
            ):
                problems.append("todos os critérios devem ter peso positivo")
            if problems:
                raise AgentGenerationError(
                    "A atividade prática contém incoerências: "
                    + "; ".join(problems)
                    + "."
                )


def validate_artifact(stage: str, artifact: Any, state: dict[str, Any]) -> None:
    """Valida um artefacto produzido por IA ou editado manualmente."""

    try:
        _validate_artifact(stage, artifact, state)
    except AgentGenerationError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise AgentGenerationError(
            "A edição manual contém campos incompletos ou valores inválidos."
        ) from error


class OpenAIPedagogicalAgent:
    """Chama a Responses API para produzir propostas pedagógicas estruturadas."""

    def __init__(
        self,
        model: str | None = None,
        *,
        resource_model: str | None = None,
        client_factory: Callable[[], Any] | None = None,
        provider_name: str = "OpenAI Responses API",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model or config_value("OPENAI_MODEL", DEFAULT_MODEL)
        self.resource_model = (
            resource_model
            or (model if model is not None else None)
            or config_value("OPENAI_RESOURCE_MODEL", DEFAULT_RESOURCE_MODEL)
        )
        self.timeout_seconds = float(config_value("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(config_value("OPENAI_MAX_RETRIES", "2"))
        self.max_output_tokens = int(config_value("OPENAI_MAX_OUTPUT_TOKENS", "12000"))
        self.reasoning_effort = config_value("OPENAI_REASONING_EFFORT", "minimal")
        self.validation_retries = max(
            0, int(config_value("OPENAI_VALIDATION_RETRIES", "2"))
        )
        self.client_factory = client_factory
        self.provider_name = provider_name
        self.api_key_env = api_key_env

    def generate(self, stage: str, state: dict[str, Any]) -> GenerationResult:
        if not os.getenv(self.api_key_env):
            raise AgentGenerationError(
                f"{self.api_key_env} não está disponível nesta sessão. Reinicie o terminal "
                "depois de a configurar ou defina-a antes de executar a aplicação."
            )

        OpenAI = None
        if self.client_factory is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise AgentGenerationError(
                    "A biblioteca OpenAI não está instalada. Execute "
                    "'python -m pip install -r requirements.txt'."
                ) from error

        selected_taxonomy = validate_taxonomy_choice(
            state.get("course", {}).get("taxonomy_type", "SOLO")
        )
        scoped_resource_type = (
            _scoped_resource_type(state) if stage == "resources" else None
        )
        artifact_requirement = (
            RESOURCE_REQUIREMENTS[scoped_resource_type]
            if scoped_resource_type
            else STAGE_REQUIREMENTS[stage]
        )
        instructions = (
            f"És o {STAGE_ROLES[stage]} numa aplicação de autoria pedagógica assistida. "
            "Responde em português europeu. Trabalha exclusivamente a partir dos dados "
            "fornecidos pelo docente e dos artefactos anteriores; não inventes fontes, "
            "regulamentos ou contextos institucionais. A sessão usa exclusivamente a "
            f"Taxonomia {selected_taxonomy}; nunca combines SOLO e Bloom. "
            "Quando houver feedback, aplica-o de modo explícito. "
            "A tua proposta será validada por um docente antes de o fluxo avançar. "
            f"Formato obrigatório do campo artifact: {artifact_requirement} "
            "Devolve o resultado no objeto raiz {\"artifact\": ...}."
        )
        if stage in {"outcome_taxonomy", "learning_outcomes"}:
            instructions += (
                f" Usa exclusivamente este catálogo controlado de verbos {selected_taxonomy}: "
                + json.dumps(
                    taxonomy_catalogue_for_prompt(selected_taxonomy),
                    ensure_ascii=False,
                )
                + "."
            )
        if stage == "learning_outcomes":
            curriculum = state.get("curriculum_analysis", {})
            required_contents = [item["id"] for item in curriculum.get("contents", [])]
            required_objectives = [item["id"] for item in curriculum.get("objectives", [])]
            instructions += (
                " Em cada resultado, statement começa exatamente pelo action_verb declarado. "
                "Depois desse verbo usa complementos nominais sempre que possível: não uses "
                "outro verbo do catálogo em nenhum ponto da frase e evita coordenações "
                "'e + infinitivo' ou 'ou + infinitivo'. Antes de responder, faz uma verificação "
                "de cobertura: a união de todos os content_links.content_id tem de ser exatamente "
                f"{required_contents} e a união de todos os objective_ids tem de ser exatamente "
                f"{required_objectives}. Não omitas nem inventes identificadores."
            )
        if stage == "outcome_taxonomy":
            instructions += (
                " A correspondência entre outcome_id, taxonomy, level e action_verb "
                "já está calculada em required_taxonomy_mapping. Copia-a exatamente; "
                "não escolhas um nível diferente com base numa interpretação semântica."
            )
        if stage == "assessment_activities":
            instructions += (
                " Em cada avaliação, assessment_purpose tem exatamente um valor: "
                "Formativa ou Sumativa, nunca Mista. outcome_ids nunca pode estar vazio "
                "e outcome_id tem de ser uma cópia exata do primeiro elemento de "
                "outcome_ids. Usa apenas os IDs indicados em assessment_link_rules."
            )
        if stage == "alignment_matrix":
            instructions += (
                " Todos os campos factuais da matriz estão calculados em "
                "required_alignment_mapping. Copia-os exatamente e acrescenta apenas "
                "uma rationale pedagógica clara para cada linha. O status é Coerente "
                "somente quando assessment e teaching_activity são ambos Sim."
            )
        if stage == "resources":
            outcome_ids = [item["id"] for item in state.get("learning_outcomes", [])]
            instructions += (
                " Os únicos identificadores de resultados de aprendizagem permitidos são: "
                f"{', '.join(outcome_ids)}. Confirma aritmeticamente as somas antes de responder."
            )
            if scoped_resource_type in {None, RESOURCE_PRESENTATION}:
                instructions += (
                    " Para cada slide, visual_mode pode ser diagrama, documento ou ia. "
                    "Capa e síntese final devem usar diagrama. "
                )
                if state.get("source_images"):
                    instructions += (
                        "Usa documento apenas quando um item de source_image_catalogue tiver "
                        "proveniência suficientemente clara para justificar a sua relevância "
                        "pedagógica; nesse caso copia exatamente o respetivo id para "
                        "visual_asset_id e deixa visual_prompt vazio. Não inventes IDs nem "
                        "deduzas o conteúdo de uma imagem quando o nome, ficheiro ou página/slide "
                        "não o permitem. "
                    )
                else:
                    instructions += (
                        "Não existem imagens documentais disponíveis; nunca uses documento e "
                        "não inventes visual_asset_id. "
                    )
                if state.get("ai_image_generation_enabled"):
                    instructions += (
                        "A geração de imagens por IA foi autorizada. Podes usar ia apenas em "
                        "slides de conteúdo onde uma ilustração acrescente valor pedagógico real; "
                        "nesse caso deixa visual_asset_id vazio e escreve em visual_prompt uma "
                        "instrução visual específica, sem pedir texto decorativo dentro da imagem. "
                    )
                else:
                    instructions += (
                        "A geração de imagens por IA não foi autorizada; nunca uses ia e deixa "
                        "visual_prompt vazio. "
                    )
                instructions += (
                    "Quando houver dúvida usa diagrama. Os campos visual_kind, visual_title e "
                    "visual_items continuam obrigatórios como fallback editável."
                )
            if scoped_resource_type:
                instructions += (
                    f" Gera exclusivamente {scoped_resource_type}. O campo artifact "
                    "contém diretamente o conteúdo desse recurso. Não devolvas "
                    "selected_types nem campos dos outros recursos; esses campos são "
                    "controlados deterministicamente pela aplicação."
                )

        started_at = perf_counter()
        try:
            client = (
                self.client_factory()
                if self.client_factory is not None
                else OpenAI(
                    timeout=self.timeout_seconds,
                    max_retries=self.max_retries,
                )
            )
        except Exception as error:
            raise AgentGenerationError(
                f"Não foi possível gerar {STAGE_ROLES[stage]}. {error}"
            ) from error

        base_context = _upstream_context(state, stage)
        repair_feedback: dict[str, Any] | None = None
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        attempts = self.validation_retries + 1
        guardrail_corrections: list[dict[str, Any]] = []
        request_model = self.resource_model if stage == "resources" else self.model

        for attempt in range(1, attempts + 1):
            request_context = dict(base_context)
            if repair_feedback:
                request_context["automatic_validation_feedback"] = repair_feedback

            try:
                request_options = {
                    "model": request_model,
                    "instructions": instructions,
                    "input": json.dumps(request_context, ensure_ascii=False),
                    "max_output_tokens": self.max_output_tokens,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": (
                                f"coeria_{stage}_"
                                f"{RESOURCE_ARTIFACT_FIELDS[scoped_resource_type]}"
                                if scoped_resource_type
                                else f"coeria_{stage}"
                            ),
                            "strict": True,
                            "schema": _schema_for(stage, state),
                        }
                    },
                }
                if supports_reasoning_effort(request_model):
                    request_options["reasoning"] = {
                        "effort": self.reasoning_effort
                    }
                response = client.responses.create(**request_options)
            except Exception as error:
                raise AgentGenerationError(
                    f"Não foi possível gerar {STAGE_ROLES[stage]}. {error}"
                ) from error

            usage = getattr(response, "usage", None)
            if usage:
                total_input_tokens += getattr(usage, "input_tokens", 0) or 0
                total_output_tokens += getattr(usage, "output_tokens", 0) or 0
                total_tokens += getattr(usage, "total_tokens", 0) or 0

            artifact: Any = None
            raw_artifact: Any = None
            try:
                payload = json.loads(response.output_text)
                raw_artifact = payload["artifact"]
                artifact = (
                    _expand_scoped_resource_payload(raw_artifact, state)
                    if stage == "resources"
                    else raw_artifact
                )
                if stage == "outcome_taxonomy":
                    artifact, guardrail_corrections = (
                        _canonicalize_outcome_taxonomy(artifact, state)
                    )
                elif stage == "assessment_activities":
                    artifact, guardrail_corrections = (
                        _canonicalize_assessment_activities(artifact, state)
                    )
                elif stage == "alignment_matrix":
                    artifact, guardrail_corrections = (
                        _canonicalize_alignment_matrix(artifact, state)
                    )
                elif stage == "resources":
                    artifact, test_corrections = _canonicalize_resource_test(
                        artifact,
                        state,
                    )
                    artifact, practical_corrections = (
                        _canonicalize_resource_practical(artifact, state)
                    )
                    artifact, visual_corrections = (
                        _canonicalize_resource_visuals(artifact, state)
                    )
                    guardrail_corrections = [
                        *test_corrections,
                        *practical_corrections,
                        *visual_corrections,
                    ]
                _validate_artifact(stage, artifact, state)
            except (AgentGenerationError, json.JSONDecodeError, KeyError, TypeError) as error:
                validation_message = (
                    str(error)
                    if isinstance(error, AgentGenerationError)
                    else "A resposta estruturada está incompleta ou contém tipos inválidos."
                )
                if attempt == attempts:
                    raise AgentGenerationError(
                        f"{validation_message} A geração foi repetida automaticamente "
                        f"{attempts} vezes sem produzir uma proposta válida."
                    ) from error
                repair_feedback = {
                    "instruction": (
                        "Corrige o problema indicado e devolve novamente apenas o "
                        "recurso atual, preservando o conteúdo que já está correto."
                        if scoped_resource_type
                        else "Corrige o problema indicado e devolve novamente o "
                        "artefacto completo, preservando o conteúdo que já está correto."
                    ),
                    "validation_error": validation_message,
                    "previous_artifact": (
                        raw_artifact if scoped_resource_type else artifact
                    ),
                }
                continue

            duration_ms = round((perf_counter() - started_at) * 1000)
            metadata = {
                "provider": self.provider_name,
                "model": request_model,
                "response_id": getattr(response, "id", "não disponível"),
                "duration_ms": duration_ms,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
                "validation_attempts": attempt,
                "guardrail_corrections": guardrail_corrections,
            }
            if scoped_resource_type:
                metadata["resource_generation_scope"] = scoped_resource_type
            return GenerationResult(
                artifact=artifact,
                metadata=metadata,
            )

        raise AgentGenerationError("A geração terminou sem produzir uma proposta válida.")


class IAeduPedagogicalAgent(OpenAIPedagogicalAgent):
    """Usa o agente configurado no IAedu com as mesmas validações pedagógicas."""

    def __init__(self) -> None:
        super().__init__(
            model=config_value("IAEDU_AGENT_NAME", "Agente IAedu"),
            client_factory=IAeduResponsesAdapter,
            provider_name="IAedu Agent Chat API",
            api_key_env="IAEDU_API_KEY",
        )


class OpenAIPedagogicalCritic:
    """Agente independente que critica a coerência pedagógica de uma proposta."""

    def __init__(
        self,
        model: str | None = None,
        *,
        client_factory: Callable[[], Any] | None = None,
        provider_name: str = "OpenAI Responses API",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model or config_value("OPENAI_CRITIC_MODEL") or config_value(
            "OPENAI_MODEL", DEFAULT_MODEL
        )
        self.timeout_seconds = float(config_value("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(config_value("OPENAI_MAX_RETRIES", "2"))
        self.max_output_tokens = int(
            config_value("OPENAI_CRITIC_MAX_OUTPUT_TOKENS", "2500")
        )
        self.reasoning_effort = config_value(
            "OPENAI_REASONING_EFFORT", "minimal"
        )
        self.client_factory = client_factory
        self.provider_name = provider_name
        self.api_key_env = api_key_env

    def review(
        self, stage: str, state: dict[str, Any], artifact: Any
    ) -> CritiqueResult:
        if not os.getenv(self.api_key_env):
            raise AgentGenerationError(
                f"A crítica agentic requer {self.api_key_env}."
            )
        OpenAI = None
        if self.client_factory is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise AgentGenerationError(
                    "A biblioteca OpenAI não está instalada."
                ) from error

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "passed": {"type": "boolean"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["warning", "blocking"],
                            },
                            "criterion": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["severity", "criterion", "message"],
                    },
                },
                "revision_instructions": {"type": "string"},
            },
            "required": ["passed", "findings", "revision_instructions"],
        }
        selected_taxonomy = validate_taxonomy_choice(
            state.get("course", {}).get("taxonomy_type", "SOLO")
        )
        instructions = (
            f"És um crítico pedagógico independente. Revê o artefacto da etapa "
            f"'{STAGE_ROLES[stage]}' em português europeu. Verifica fidelidade aos dados "
            "do docente, coerência com os artefactos anteriores, alinhamento construtivo, "
            f"adequação da exigência cognitiva {selected_taxonomy}, clareza e "
            "exequibilidade. Não alteres "
            "o artefacto. Marca passed=false apenas quando existir pelo menos um finding "
            "blocking; sugestões opcionais são warning. A validação determinística de IDs, "
            "cobertura e somas já foi executada."
        )
        context = {
            "stage": stage,
            "course": state.get("course", {}),
            "upstream": _upstream_context(state, stage),
            "proposed_artifact": artifact,
            "taxonomy": selected_taxonomy,
            "taxonomy_verb_catalogue": taxonomy_catalogue_for_prompt(
                selected_taxonomy
            ),
        }
        started_at = perf_counter()
        try:
            client = (
                self.client_factory()
                if self.client_factory is not None
                else OpenAI(
                    timeout=self.timeout_seconds,
                    max_retries=self.max_retries,
                )
            )
            request_options: dict[str, Any] = {
                "model": self.model,
                "instructions": instructions,
                "input": json.dumps(context, ensure_ascii=False),
                "max_output_tokens": self.max_output_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": f"coeria_critic_{stage}",
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
            if supports_reasoning_effort(self.model):
                request_options["reasoning"] = {
                    "effort": self.reasoning_effort
                }
            response = client.responses.create(**request_options)
            payload = json.loads(response.output_text)
        except Exception as error:
            raise AgentGenerationError(f"A revisão agentic não ficou disponível. {error}") from error

        findings = payload["findings"]
        passed = bool(payload["passed"]) and not any(
            item["severity"] == "blocking" for item in findings
        )
        usage = getattr(response, "usage", None)
        return CritiqueResult(
            passed=passed,
            findings=findings,
            revision_instructions=payload["revision_instructions"],
            metadata={
                "provider": self.provider_name,
                "role": "crítico pedagógico",
                "model": self.model,
                "response_id": getattr(response, "id", "não disponível"),
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            },
        )


class IAeduPedagogicalCritic(OpenAIPedagogicalCritic):
    """Crítico pedagógico executado pelo mesmo fornecedor IAedu selecionado."""

    def __init__(self) -> None:
        super().__init__(
            model=config_value("IAEDU_AGENT_NAME", "Agente IAedu"),
            client_factory=IAeduResponsesAdapter,
            provider_name="IAedu Agent Chat API",
            api_key_env="IAEDU_API_KEY",
        )


class AgenticPedagogicalTeam:
    """Ciclo limitado gerador–crítico, mantendo a aprovação humana no exterior."""

    DEFAULT_CRITIC_STAGES = (
        "learning_outcomes",
        "outcome_taxonomy",
        "assessment_activities",
        "teaching_activities",
        "alignment_matrix",
    )

    def __init__(
        self,
        generator: PedagogicalAgent,
        critic: PedagogicalCritic | None = None,
        enabled: bool | None = None,
        max_revisions: int | None = None,
        critic_stages: tuple[str, ...] | None = None,
    ) -> None:
        configured = config_value("AGENTIC_CRITIC_ENABLED", "true").casefold()
        self.enabled = enabled if enabled is not None else configured not in {"0", "false", "no"}
        self.generator = generator
        self.critic = critic or OpenAIPedagogicalCritic()
        self.max_revisions = max_revisions if max_revisions is not None else max(
            0, int(config_value("AGENTIC_MAX_REVISIONS", "1"))
        )
        configured_stages = tuple(
            item.strip()
            for item in config_value("AGENTIC_CRITIC_STAGES").split(",")
            if item.strip()
        )
        self.critic_stages = critic_stages or configured_stages or self.DEFAULT_CRITIC_STAGES

    def generate(self, stage: str, state: dict[str, Any]) -> GenerationResult:
        result = self.generator.generate(stage, state)
        if not self.enabled or stage not in self.critic_stages:
            return result

        runs: list[dict[str, Any]] = [{"role": "gerador", **result.metadata}]
        working_state = deepcopy(state)
        final_review: CritiqueResult | None = None
        critic_error = ""

        for revision_index in range(self.max_revisions + 1):
            try:
                final_review = self.critic.review(stage, working_state, result.artifact)
            except AgentGenerationError as error:
                critic_error = str(error)
                break
            runs.append(final_review.metadata)
            if final_review.passed or revision_index == self.max_revisions:
                break

            feedback = final_review.revision_instructions or "; ".join(
                finding["message"] for finding in final_review.findings
            )
            working_state.setdefault("feedback", {})[stage] = (
                "Revisão do crítico pedagógico: " + feedback
            )
            result = self.generator.generate(stage, working_state)
            runs.append({"role": "gerador após crítica", **result.metadata})

        total_tokens = sum(int(item.get("total_tokens", 0) or 0) for item in runs)
        metadata = {
            **result.metadata,
            "agentic": {
                "enabled": True,
                "critic_passed": final_review.passed if final_review else None,
                "findings": final_review.findings if final_review else [],
                "revision_instructions": (
                    final_review.revision_instructions if final_review else critic_error
                ),
                "automatic_revisions": max(
                    0, sum(1 for item in runs if item.get("role") == "gerador após crítica")
                ),
                "runs": runs,
            },
            "total_tokens": total_tokens,
        }
        return GenerationResult(artifact=result.artifact, metadata=metadata)


def build_pedagogical_team(provider: str | None) -> AgenticPedagogicalTeam:
    """Constrói gerador e crítico no mesmo fornecedor escolhido para a sessão."""

    selected = validate_ai_provider(provider)
    if selected == AI_PROVIDER_IAEDU:
        return AgenticPedagogicalTeam(
            IAeduPedagogicalAgent(),
            critic=IAeduPedagogicalCritic(),
        )
    if selected == AI_PROVIDER_OPENAI:
        return AgenticPedagogicalTeam(
            OpenAIPedagogicalAgent(),
            critic=OpenAIPedagogicalCritic(),
        )
    raise AgentGenerationError("Fornecedor de IA não suportado.")


class RuleBasedPedagogicalAgent:
    """Gerador determinístico reservado aos testes automatizados."""

    def __init__(self, generators: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self.generators = generators

    def generate(self, stage: str, state: dict[str, Any]) -> GenerationResult:
        return GenerationResult(
            artifact=self.generators[stage](state),
            metadata={
                "provider": "gerador determinístico de testes",
                "model": "n/a",
                "duration_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        )
