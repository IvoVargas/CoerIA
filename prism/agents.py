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

from .ai_modes import (
    AI_MODE_ABOUT,
    AI_MODE_OFF,
    AI_MODE_ON,
    AI_MODES,
    canonical_ai_mode,
    lesson_ai_mode_issues,
    linked_ai_mode,
)
from .branding import config_value
from .curriculum import (
    ASSESSMENT_PURPOSES,
    BLOOM_LEVELS,
    has_single_action_verb,
    LEARNING_CONTEXTS,
    LESSON_TYPES,
    MAX_OUTCOMES,
    MIN_OUTCOMES,
    OUTCOME_TYPES,
    SOLO_LEVELS,
    TAXONOMY_LEVELS,
    TAXONOMY_VERBS,
    taxonomy_catalogue_for_prompt,
    taxonomy_level_for_verb,
    taxonomy_verb_allowed,
    is_learning_outcome_id,
    normalize_learning_outcome_ids,
    normalize_structured_activity_ids,
    is_structured_activity_id,
    starts_with_objective_action_verb,
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
from .quality import (
    PRESENTATION_ASSESSMENT_TITLE,
    evaluate_quality,
    presentation_assessment_overview_issues,
    presentation_visual_issues,
)
from .resource_catalog import slide_outcome_ids
from .validation_targets import available_validation_targets


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


class LocalizedAssistanceAgent(Protocol):
    def propose(
        self,
        stage: str,
        state: dict[str, Any],
        scope_path: list[str | int],
        scope_label: str,
        instruction: str,
        current_value: Any,
    ) -> GenerationResult:
        """Propõe apenas o fragmento selecionado, nunca o artefacto completo."""


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
    "teaching_activities": "especialista em atividades de ensino-aprendizagem",
    "assessment_activities": "especialista em tarefas e critérios de avaliação",
    "pedagogical_design": "especialista em planeamento de aulas",
    "resources": "especialista em recursos educativos",
}


STAGE_REQUIREMENTS = {
    "curriculum_analysis": (
        "Objeto com contents. contents contém "
        "4 a 10 objetos {id, title, description, outcome_ids}, com IDs C1, C2, ...; "
        "cada outcome_ids dos conteúdos usa exclusivamente "
        "resultados aprovados na etapa anterior. Em cada conteúdo, title é uma "
        "designação temática breve e description caracteriza conceitos, princípios, "
        "processos e limites em formulação expositiva. A descrição não começa por um "
        "verbo de ação, não se dirige ao estudante e não formula um objetivo ou resultado."
    ),
    "learning_outcomes": (
        "Lista de 4 a 10 objetos {id, theme, statement, action_verb, taxonomy_level, "
        "outcome_type, ai_mode}. Os IDs são obrigatoriamente RA1, RA2, ... pela ordem das linhas. "
        "Cada resultado contém exatamente um verbo de ação principal observável e começa "
        "por esse verbo. taxonomy_level pertence à taxonomia selecionada e é compatível "
        "com action_verb. ai_mode é AI-off, AI-on ou on-AI e é AI-off por defeito. "
        "O objeto da ação explicita o conhecimento ou competência em causa. "
        "Infinitivos subordinados podem surgir em complementos, mas não como ações "
        "principais coordenadas."
    ),
    "assessment_activities": (
        "Lista de objetos {id, teaching_activity_ids, outcome_ids, ai_mode, work_type, assessment_purpose, "
        "activity, evidence, criterion}. Os IDs são obrigatoriamente TA1, TA2, ... "
        "pela ordem das linhas. assessment_purpose é exclusivamente Formativa ou "
        "Sumativa. Cada tarefa liga-se a uma ou mais atividades de ensino-aprendizagem "
        "existentes e a evidência permite observar os verbos dos resultados trabalhados "
        "por essas atividades. ai_mode corresponde ao modo dos resultados e das atividades "
        "associadas. É válido o conjunto conter apenas avaliações sumativas."
    ),
    "pedagogical_design": (
        "Objeto com lessons. lessons é uma lista de aulas com "
        "{duration_minutes, session_type, component_ids, notes}. A duração é positiva, "
        "session_type usa um dos tipos permitidos, component_ids pode ficar vazio ou "
        "referenciar atividades AE e/ou tarefas TA existentes e notes pode ser texto vazio. "
        "A soma das durações corresponde exatamente às horas de contacto."
    ),
    "teaching_activities": (
        "Lista de objetos {id, outcome_id, outcome_ids, learning_context, "
        "ai_mode, activity, method, practice, support, feedback_strategy}. Os IDs são "
        "obrigatoriamente AE1, AE2, ... pela ordem das linhas; o conjunto deve "
        "cobrir todos os resultados, herdar o respetivo ai_mode e explicitar prática, "
        "acompanhamento e feedback."
    ),
    "resources": (
        "Conjunto de recursos selecionados pelo docente. A aplicação gera cada recurso "
        "generativo isoladamente; as apresentações das aulas são limitadas à aula atual "
        "e cada teste é limitado à respetiva tarefa de avaliação. O plano de aulas e a "
        "grelha de avaliação são derivados deterministicamente dos artefactos aprovados. "
        "Cada elemento deve indicar os resultados de aprendizagem associados ao seu âmbito. "
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
        "aprendizagem do respetivo âmbito, sem usar IDs desconhecidos. No teste, a soma dos pontos das "
        "questões deve ser igual a total_points. Na atividade prática, a união dos "
        "outcome_ids de todas as etapas deve cobrir exatamente todos os resultados e "
        "os pesos positivos dos critérios devem totalizar exatamente 100. Na apresentação, "
        "a aplicação acrescenta uma secção própria com todas as tarefas e critérios de "
        "avaliação aprovados."
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
        "Lista de slides com title, bullets, outcome_id, outcome_ids, visual_mode, visual_asset_id, "
        "visual_prompt, visual_kind, visual_title, visual_items, visual_source e alt_text. Cobre todos os "
        "resultados de aprendizagem e inclui slides de capa e síntese. A aplicação "
        "acrescenta deterministicamente, antes da síntese, uma secção dedicada às "
        "tarefas e critérios de avaliação aprovados."
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
    artifact_schemas: dict[str, dict[str, Any]] = {
        "curriculum_analysis": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "contents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": string,
                            "title": string,
                            "description": string,
                            "outcome_ids": {"type": "array", "items": string},
                        },
                        "required": ["id", "title", "description", "outcome_ids"],
                    },
                },
            },
            "required": ["contents"],
        },
        "learning_outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^RA[1-9][0-9]*$"},
                    "theme": string,
                    "statement": string,
                    "action_verb": string,
                    "taxonomy_level": {"type": "string", "enum": target_levels},
                    "outcome_type": {"type": "string", "enum": list(OUTCOME_TYPES)},
                    "ai_mode": {"type": "string", "enum": list(AI_MODES)},
                },
                "required": [
                    "id", "theme", "statement", "action_verb",
                    "taxonomy_level", "outcome_type", "ai_mode"
                ],
            },
        },
        "assessment_activities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^TA[1-9][0-9]*$"},
                    "teaching_activity_ids": {"type": "array", "items": string},
                    "outcome_ids": {"type": "array", "items": string},
                    "ai_mode": {"type": "string", "enum": list(AI_MODES)},
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
                    "id", "teaching_activity_ids", "outcome_ids", "ai_mode", "work_type",
                    "assessment_purpose",
                    "activity", "evidence", "criterion"
                ],
            },
        },
        "pedagogical_design": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lessons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "duration_minutes": {"type": "integer", "minimum": 1},
                            "session_type": {"type": "string", "enum": list(LESSON_TYPES)},
                            "component_ids": {"type": "array", "items": string},
                            "notes": string,
                        },
                        "required": [
                            "duration_minutes", "session_type", "component_ids", "notes"
                        ],
                    },
                },
            },
            "required": ["lessons"],
        },
        "teaching_activities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^AE[1-9][0-9]*$"},
                    "outcome_id": string,
                    "outcome_ids": {"type": "array", "items": string},
                    "ai_mode": {"type": "string", "enum": list(AI_MODES)},
                    "learning_context": {"type": "string", "enum": list(LEARNING_CONTEXTS)},
                    "activity": string,
                    "method": string,
                    "practice": string,
                    "support": string,
                    "feedback_strategy": string,
                },
                "required": [
                    "id", "outcome_id", "outcome_ids", "ai_mode",
                    "learning_context", "activity", "method", "practice",
                    "support", "feedback_strategy"
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
                            "outcome_ids": {"type": "array", "items": string},
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
                            "visual_items": {
                                "type": "array",
                                "items": string,
                                "minItems": 2,
                                "maxItems": 4,
                            },
                            "visual_source": string,
                            "alt_text": string,
                        },
                        "required": [
                            "title", "bullets", "outcome_id", "outcome_ids", "visual_mode",
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
    if stage == "resources":
        artifact_schema = deepcopy(artifact_schema)
        presentation_schema = deepcopy(
            artifact_schema["properties"]["presentation_outline"]
        )
        test_schema = deepcopy(artifact_schema["properties"]["test"])
        artifact_schema["properties"].update(
            {
                "lesson_presentations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "lesson_number": {"type": "integer", "minimum": 1},
                            "outcome_ids": {"type": "array", "items": string},
                            "presentation_outline": presentation_schema,
                        },
                        "required": [
                            "lesson_number",
                            "outcome_ids",
                            "presentation_outline",
                        ],
                    },
                },
                "tests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "assessment_task_id": string,
                            "outcome_ids": {"type": "array", "items": string},
                            "test": test_schema,
                        },
                        "required": ["assessment_task_id", "outcome_ids", "test"],
                    },
                },
                "lesson_plan": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "lessons": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "lesson_number": {"type": "integer"},
                                    "duration_minutes": {"type": "integer"},
                                    "session_type": string,
                                    "component_ids": {"type": "array", "items": string},
                                    "notes": string,
                                },
                                "required": [
                                    "lesson_number",
                                    "duration_minutes",
                                    "session_type",
                                    "component_ids",
                                    "notes",
                                ],
                            },
                        }
                    },
                    "required": ["lessons"],
                },
                "assessment_grid": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "rows": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "assessment_task_id": string,
                                    "teaching_activity_ids": {
                                        "type": "array",
                                        "items": string,
                                    },
                                    "outcome_ids": {"type": "array", "items": string},
                                    "assessment_purpose": string,
                                    "work_type": string,
                                    "activity": string,
                                    "evidence": string,
                                    "criterion": string,
                                },
                                "required": [
                                    "assessment_task_id",
                                    "teaching_activity_ids",
                                    "outcome_ids",
                                    "assessment_purpose",
                                    "work_type",
                                    "activity",
                                    "evidence",
                                    "criterion",
                                ],
                            },
                        }
                    },
                    "required": ["rows"],
                },
            }
        )
        artifact_schema["required"].extend(
            ["lesson_presentations", "tests", "lesson_plan", "assessment_grid"]
        )
    if stage == "curriculum_analysis" and state:
        artifact_schema = deepcopy(artifact_schema)
        outcome_ids = [
            str(item.get("id", ""))
            for item in state.get("learning_outcomes", [])
            if str(item.get("id", "")).strip()
        ]
        if outcome_ids:
            artifact_schema["properties"]["contents"]["items"]["properties"][
                "outcome_ids"
            ]["items"] = {"type": "string", "enum": outcome_ids}
        reduction = state.get("source_reduction", {})
        source_names = [
            str(item.get("source", "")).strip()
            for item in reduction.get("sources", [])
            if str(item.get("source", "")).strip()
        ]
        if reduction.get("applied") and source_names:
            artifact_schema["properties"]["source_coverage"] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source": {"type": "string", "enum": source_names},
                        "contribution": string,
                        "key_concepts": {"type": "array", "items": string},
                        "content_ids": {"type": "array", "items": string},
                    },
                    "required": [
                        "source", "contribution", "key_concepts", "content_ids"
                    ],
                },
            }
            artifact_schema["required"] = [
                *artifact_schema["required"],
                "source_coverage",
            ]
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
        item_schema = artifact_schema["items"]["properties"]
        item_schema["action_verb"] = {
            "type": "string",
            "enum": allowed_verbs,
        }
        item_schema["taxonomy_level"] = {
            "type": "string",
            "enum": list(TAXONOMY_LEVELS[selected_taxonomy]),
        }
    if stage == "assessment_activities" and state:
        artifact_schema = deepcopy(artifact_schema)
        teaching_activity_ids = [
            str(item.get("id", ""))
            for item in state.get("teaching_activities", [])
            if str(item.get("id", "")).strip()
        ]
        item_schema = artifact_schema["items"]["properties"]
        item_schema["teaching_activity_ids"]["items"] = {
            "type": "string",
            "enum": teaching_activity_ids,
        }
        outcome_ids = [
            str(item.get("id", ""))
            for item in state.get("learning_outcomes", [])
            if str(item.get("id", "")).strip()
        ]
        item_schema["outcome_ids"]["items"] = {
            "type": "string",
            "enum": outcome_ids,
        }
    if stage == "pedagogical_design" and state:
        artifact_schema = deepcopy(artifact_schema)
        component_ids = [
            str(item.get("id", ""))
            for item in state.get("teaching_activities", [])
            if str(item.get("id", "")).strip()
        ] + [
            str(item.get("id", ""))
            for item in state.get("assessment_activities", [])
            if str(item.get("id", "")).strip()
        ]
        item_schema = artifact_schema["properties"]["lessons"]["items"][
            "properties"
        ]
        item_schema["component_ids"]["items"] = {
            "type": "string",
            "enum": component_ids,
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
        elif scoped_resource_type == RESOURCE_PRESENTATION and state:
            outcome_ids = [
                str(item["id"])
                for item in state.get("learning_outcomes", [])
                if item.get("id")
            ]
            slide_properties = artifact_schema["items"]["properties"]
            slide_properties["outcome_id"] = {
                "type": "string",
                "enum": ["", *outcome_ids],
            }
            slide_properties["outcome_ids"]["items"] = {
                "type": "string",
                "enum": outcome_ids,
            }
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


def _schema_for_scope(
    stage: str,
    state: dict[str, Any],
    scope_path: list[str | int],
) -> dict[str, Any]:
    """Deriva do esquema da etapa o contrato exato de uma célula, linha ou tabela."""

    scoped_schema = deepcopy(_schema_for(stage, state)["properties"]["artifact"])
    for part in scope_path:
        if isinstance(part, int):
            if scoped_schema.get("type") != "array" or "items" not in scoped_schema:
                raise AgentGenerationError(
                    "O âmbito selecionado não corresponde a uma linha editável."
                )
            scoped_schema = deepcopy(scoped_schema["items"])
            continue
        properties = scoped_schema.get("properties", {})
        if part not in properties:
            raise AgentGenerationError(
                "O âmbito selecionado não corresponde a um campo editável."
            )
        scoped_schema = deepcopy(properties[part])
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"proposal": scoped_schema},
        "required": ["proposal"],
    }


def _source_image_description(asset: dict[str, Any]) -> str:
    """Descreve uma candidata documental sem expor os respetivos bytes."""

    explicit_description = str(
        asset.get("description") or asset.get("alt_text") or asset.get("caption") or ""
    ).strip()
    if explicit_description:
        return explicit_description

    kind = (
        "figura composta reconstruída localmente"
        if asset.get("candidate_kind") == "composite_render"
        else "imagem incorporada no documento"
    )
    source_file = str(asset.get("source_file", "")).strip()
    source_location = str(asset.get("source_location", "")).strip()
    width = int(asset.get("width_px", 0) or 0)
    height = int(asset.get("height_px", 0) or 0)
    parts = [kind]
    if source_file:
        parts.append(f"extraída de {source_file}")
    if source_location:
        parts.append(f"em {source_location}")
    if width and height:
        parts.append(f"com dimensões {width} × {height} píxeis")
    return "; ".join(parts) + "."


def _upstream_context(state: dict[str, Any], stage: str) -> dict[str, Any]:
    """Inclui apenas os dados pedagógicos relevantes na chamada ao modelo."""

    stage_order = (
        "learning_outcomes",
        "curriculum_analysis",
        "teaching_activities",
        "assessment_activities",
        "pedagogical_design",
        "resources",
    )
    stage_index = stage_order.index(stage)
    context = {
        "course": state["course"],
        "feedback_from_teacher": state.get("feedback", {}).get(stage, ""),
        "requested_resource_types": state.get("resource_types", []),
    }
    if stage == "resources" and isinstance(state.get("resource_item_scope"), dict):
        context["resource_item_scope"] = deepcopy(state["resource_item_scope"])
    if stage == "learning_outcomes":
        context["optional_assumptions_for_learning_outcomes"] = [
            str(item).strip()
            for item in state.get("learning_outcome_assumptions", [])
            if str(item).strip()
        ]
    assistance_request = state.get("_ai_assistance_request")
    if isinstance(assistance_request, dict):
        context["teacher_request"] = str(
            assistance_request.get("instruction", "")
        ).strip()
        context["current_stage_artifact_read_only"] = deepcopy(
            assistance_request.get("current_artifact")
        )
    for artifact_stage in stage_order[:stage_index]:
        if artifact_stage in state:
            context[artifact_stage] = state[artifact_stage]
    if stage == "curriculum_analysis":
        outcome_ids = [
            str(item.get("id", ""))
            for item in state.get("learning_outcomes", [])
            if str(item.get("id", "")).strip()
        ]
        if outcome_ids:
            context["curriculum_alignment_rules"] = {
                "required_outcome_ids": outcome_ids,
                "rule": (
                    "Cada conteúdo indica os resultados que suporta. A união dos "
                    "outcome_ids dos conteúdos deve corresponder exatamente aos "
                    "resultados aprovados, sem IDs desconhecidos."
                ),
            }
        reduction = state.get("source_reduction", {})
        source_stats = [
            {
                "source": str(item.get("source", "")),
                "original_chars": int(item.get("original_chars", 0) or 0),
                "initial_chunks": int(item.get("initial_chunks", 0) or 0),
            }
            for item in reduction.get("sources", [])
            if str(item.get("source", "")).strip()
        ]
        if reduction.get("applied") and source_stats:
            context["source_coverage_rules"] = {
                "sources": source_stats,
                "rule": (
                    "Analisa todas as fontes, independentemente da ordem ou tamanho. "
                    "A proposta deve mostrar a contribuição distintiva de cada fonte "
                    "em source_coverage e ligar cada fonte a pelo menos um conteúdo C*."
                ),
            }
    if stage == "assessment_activities":
        context["assessment_link_rules"] = {
            "rule": (
                "Cada teaching_activity_ids contém uma ou mais atividades de "
                "ensino-aprendizagem existentes. Cada outcome_ids contém um ou mais "
                "resultados avaliados diretamente. Para cada ligação TA→RA deve existir "
                "pelo menos uma atividade selecionada que desenvolva esse resultado."
            ),
            "allowed_purposes": list(ASSESSMENT_PURPOSES),
            "allowed_teaching_activities": [
                {
                    "id": activity.get("id", ""),
                    "outcome_ids": activity.get("outcome_ids")
                    or [activity.get("outcome_id", "")],
                    "ai_mode": activity.get("ai_mode", AI_MODE_OFF),
                    "activity": activity.get("activity", ""),
                }
                for activity in state.get("teaching_activities", [])
            ],
            "allowed_outcomes": [
                {
                    "id": outcome.get("id", ""),
                    "action_verb": outcome.get("action_verb", ""),
                    "ai_mode": outcome.get("ai_mode", AI_MODE_OFF),
                    "statement": outcome.get("statement", ""),
                }
                for outcome in state.get("learning_outcomes", [])
            ],
            "mixed_purpose_forbidden": True,
        }
    if stage == "pedagogical_design":
        outcomes = [
            item
            for item in state.get("learning_outcomes", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        contents = [
            item
            for item in state.get("curriculum_analysis", {}).get("contents", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        teaching_activities = [
            item
            for item in state.get("teaching_activities", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        assessment_tasks = [
            item
            for item in state.get("assessment_activities", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        contact_minutes = round(
            float(state.get("course", {}).get("contact_hours", 0) or 0) * 60
        )
        autonomous_minutes = round(
            float(state.get("course", {}).get("autonomous_hours", 0) or 0)
            * 60
        )
        alignment_chains = []
        for outcome in outcomes:
            outcome_id = str(outcome["id"])
            linked_teaching_ids = [
                str(item["id"])
                for item in teaching_activities
                if outcome_id
                in (item.get("outcome_ids") or [item.get("outcome_id", "")])
            ]
            alignment_chains.append(
                {
                    "outcome_id": outcome_id,
                    "statement": str(outcome.get("statement", "")),
                    "taxonomy_level": str(outcome.get("taxonomy_level", "")),
                    "content_ids": [
                        str(item["id"])
                        for item in contents
                        if outcome_id in item.get("outcome_ids", [])
                    ],
                    "teaching_activity_ids": linked_teaching_ids,
                    "assessment_task_ids": [
                        str(item["id"])
                        for item in assessment_tasks
                        if outcome_id in item.get("outcome_ids", [])
                        and set(linked_teaching_ids)
                        & set(item.get("teaching_activity_ids", []))
                    ],
                }
            )
        context["lesson_planning_brief"] = {
            "duration_targets": {
                "contact_minutes_for_lessons": contact_minutes,
                "autonomous_work_minutes_context_only": autonomous_minutes,
            },
            "contents": [
                {
                    "id": str(item["id"]),
                    "title": str(item.get("title", "")),
                    "description": str(item.get("description", "")),
                    "outcome_ids": list(item.get("outcome_ids", []) or []),
                }
                for item in contents
            ],
            "component_catalogue": [
                {
                    "id": str(item["id"]),
                    "kind": "atividade_de_ensino_aprendizagem",
                    "description": str(item.get("activity", "")),
                    "outcome_ids": list(
                        item.get("outcome_ids") or [item.get("outcome_id", "")]
                    ),
                    "learning_context": str(item.get("learning_context", "")),
                    "practice": str(item.get("practice", "")),
                }
                for item in teaching_activities
            ]
            + [
                {
                    "id": str(item["id"]),
                    "kind": "tarefa_de_avaliacao",
                    "description": str(item.get("activity", "")),
                    "outcome_ids": list(item.get("outcome_ids", []) or []),
                    "teaching_activity_ids": list(
                        item.get("teaching_activity_ids", []) or []
                    ),
                    "assessment_purpose": str(
                        item.get("assessment_purpose", "")
                    ),
                }
                for item in assessment_tasks
            ],
            "alignment_chains": alignment_chains,
        }
        context["lesson_planning_rules"] = {
            "allowed_component_ids": [
                str(item.get("id", ""))
                for item in state.get("teaching_activities", [])
                if str(item.get("id", "")).strip()
            ] + [
                str(item.get("id", ""))
                for item in state.get("assessment_activities", [])
                if str(item.get("id", "")).strip()
            ],
            "allowed_session_types": list(LESSON_TYPES),
            "rule": (
                "Planeia aulas ordenadas a partir de lesson_planning_brief. Cada aula tem "
                "duração positiva. component_ids é opcional: pode ficar vazio ou incluir "
                "atividades AE e/ou tarefas TA existentes quando forem relevantes nessa aula. "
                "Quando associa componentes, preserva as cadeias RA→AE→TA e agenda cada TA "
                "depois ou na mesma aula das AE que a preparam. Não é obrigatório distribuir "
                "todos os componentes pelo planeamento. Quando "
                "contact_minutes_for_lessons for positivo, a soma das durações deve ser "
                "exatamente esse valor. Numa proposta completa de IA, notes explicita o "
                "foco curricular e a progressão com base nos conteúdos e resultados; o "
                "docente pode posteriormente esvaziar esse texto opcional."
            ),
        }
    if stage == "resources" and "Apresentação PowerPoint" in state.get(
        "resource_types", []
    ):
        source_images = []
        for asset in state.get("source_images", []):
            if not isinstance(asset, dict) or not str(asset.get("id", "")).strip():
                continue
            if asset.get("origin_type") == "user_uploaded":
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
                    "description": _source_image_description(asset),
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


def _canonicalize_assessment_activities(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Normaliza os IDs e a finalidade sem inventar relações pedagógicas."""

    if not isinstance(artifact, list):
        return artifact, []
    allowed_teaching = {
        str(item.get("id", ""))
        for item in state.get("teaching_activities", [])
        if str(item.get("id", "")).strip()
    }
    allowed_outcomes = {
        str(item.get("id", ""))
        for item in state.get("learning_outcomes", [])
        if str(item.get("id", "")).strip()
    }
    normalized: list[Any] = []
    corrections: list[dict[str, Any]] = []
    for index, item in enumerate(artifact, start=1):
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        purpose = str(item.get("assessment_purpose", ""))
        canonical_purpose = next(
            (
                allowed_purpose
                for allowed_purpose in ASSESSMENT_PURPOSES
                if purpose.casefold() == allowed_purpose.casefold()
            ),
            purpose,
        )
        raw_teaching_links = item.get("teaching_activity_ids", [])
        teaching_links = list(
            dict.fromkeys(
                str(identifier)
                for identifier in (
                    raw_teaching_links if isinstance(raw_teaching_links, list) else []
                )
                if str(identifier) in allowed_teaching
            )
        )
        raw_outcome_links = item.get("outcome_ids", [])
        outcome_links = list(
            dict.fromkeys(
                str(identifier)
                for identifier in (
                    raw_outcome_links if isinstance(raw_outcome_links, list) else []
                )
                if str(identifier) in allowed_outcomes
            )
        )
        inherited_mode = linked_ai_mode(
            outcome_links,
            state.get("learning_outcomes", []),
        )
        canonical = {
            "id": f"TA{index}",
            "teaching_activity_ids": teaching_links,
            "outcome_ids": outcome_links,
            "ai_mode": inherited_mode or "",
            "assessment_purpose": canonical_purpose,
        }
        changes = {
            field: {"received": item.get(field), "used": value}
            for field, value in canonical.items()
            if item.get(field) != value
        }
        normalized.append(
            {key: value for key, value in {**item, **canonical}.items() if key != "outcome_id"}
        )
        if changes:
            corrections.append(
                {"assessment_id": item.get("id", ""), "changes": changes}
            )
    return normalized, corrections


def _canonicalize_teaching_activities(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Aplica IDs AE<n> e herda o AI-mode dos resultados associados."""

    if not isinstance(artifact, list):
        return artifact, []
    normalized = normalize_structured_activity_ids(
        artifact,
        prefix="AE",
        sequential=True,
    )
    corrections: list[dict[str, Any]] = []
    for received, item in zip(artifact, normalized):
        if not isinstance(received, dict) or not isinstance(item, dict):
            continue
        changes: dict[str, Any] = {}
        if received.get("id") != item.get("id"):
            changes["id"] = {
                "received": received.get("id"),
                "used": item.get("id"),
            }
        outcome_ids = item.get("outcome_ids") or [item.get("outcome_id", "")]
        inherited_mode = linked_ai_mode(
            outcome_ids,
            state.get("learning_outcomes", []),
        )
        canonical_mode = inherited_mode or ""
        if item.get("ai_mode") != canonical_mode:
            changes["ai_mode"] = {
                "received": item.get("ai_mode"),
                "used": canonical_mode,
            }
        item["ai_mode"] = canonical_mode
        if changes:
            corrections.append(
                {
                    "teaching_activity_id": item.get("id", ""),
                    "changes": changes,
                }
            )
    return normalized, corrections


def _canonicalize_lesson_planning(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Ajusta deterministicamente as durações da proposta às horas de contacto."""

    if not isinstance(artifact, dict) or not isinstance(artifact.get("lessons"), list):
        return artifact, []
    lessons = artifact["lessons"]
    expected_minutes = round(
        float(state.get("course", {}).get("contact_hours", 0) or 0) * 60
    )
    if not lessons or expected_minutes <= 0 or expected_minutes < len(lessons):
        return artifact, []
    durations = [
        lesson.get("duration_minutes") if isinstance(lesson, dict) else None
        for lesson in lessons
    ]
    if any(not isinstance(duration, int) or duration <= 0 for duration in durations):
        return artifact, []
    planned_minutes = sum(durations)
    if planned_minutes == expected_minutes:
        return artifact, []

    # Reserva um minuto por aula e distribui o restante proporcionalmente. A
    # aritmética inteira garante o total exato sem depender de uma nova chamada ao LLM.
    distributable = expected_minutes - len(lessons)
    quotients: list[int] = []
    remainders: list[tuple[int, int]] = []
    for index, duration in enumerate(durations):
        quotient, remainder = divmod(duration * distributable, planned_minutes)
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
    normalized_durations = [
        1 + quotient + (1 if index in recipients else 0)
        for index, quotient in enumerate(quotients)
    ]
    normalized = deepcopy(artifact)
    for lesson, duration in zip(normalized["lessons"], normalized_durations):
        lesson["duration_minutes"] = duration
    return normalized, [
        {
            "field": "lessons.duration_minutes",
            "reason": "total ajustado deterministicamente às horas de contacto",
            "received_total": planned_minutes,
            "used_total": expected_minutes,
            "used_durations": normalized_durations,
        }
    ]


def _canonicalize_learning_outcomes(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Deriva IDs e níveis controlados sem alterar a formulação do resultado."""

    if not isinstance(artifact, list):
        return artifact, []
    normalized_ids = normalize_learning_outcome_ids(artifact, sequential=True)
    selected_taxonomy = validate_taxonomy_choice(
        state.get("course", {}).get("taxonomy_type", "SOLO")
    )
    normalized: list[Any] = []
    corrections: list[dict[str, Any]] = []
    for received, item in zip(artifact, normalized_ids):
        if not isinstance(received, dict) or not isinstance(item, dict):
            normalized.append(item)
            continue
        changes: dict[str, Any] = {}
        if received.get("id") != item.get("id"):
            changes["id"] = {
                "received": received.get("id"),
                "used": item.get("id"),
            }
        canonical_level = taxonomy_level_for_verb(
            selected_taxonomy, str(item.get("action_verb", ""))
        )
        corrected = (
            {**item, "taxonomy_level": canonical_level}
            if canonical_level is not None
            else item
        )
        canonical_mode = canonical_ai_mode(corrected.get("ai_mode"))
        if corrected.get("ai_mode") != canonical_mode:
            changes["ai_mode"] = {
                "received": corrected.get("ai_mode"),
                "used": canonical_mode,
            }
        corrected = {**corrected, "ai_mode": canonical_mode}
        normalized.append(corrected)
        if canonical_level is not None and item.get("taxonomy_level") != canonical_level:
            changes["taxonomy_level"] = {
                "received": item.get("taxonomy_level"),
                "used": canonical_level,
            }
        if changes:
            corrections.append(
                {
                    "outcome_id": corrected.get("id", ""),
                    "changes": changes,
                }
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


_SOURCE_IMAGE_TEXT_FIELDS = (
    "id",
    "description",
    "source_file",
    "source_location",
    "filename",
    "media_type",
    "candidate_kind",
    "width_px",
    "height_px",
)


def _source_image_text_input(request_context: dict[str, Any]) -> str:
    """Serializa o contexto visual sem miniaturas nem imagens originais.

    A lista explícita funciona como uma fronteira de privacidade: mesmo que um
    campo binário seja acrescentado por engano ao catálogo, não chega ao pedido.
    """

    sanitized_context = dict(request_context)
    sanitized_context["source_image_catalogue"] = [
        {key: item[key] for key in _SOURCE_IMAGE_TEXT_FIELDS if key in item}
        for item in request_context.get("source_image_catalogue", [])
        if isinstance(item, dict)
    ]
    return json.dumps(sanitized_context, ensure_ascii=False)


def _canonicalize_resource_presentation_outcomes(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Normaliza ligações RA dos slides e remove marcadores inventados pelo modelo."""

    if not isinstance(artifact, dict):
        return artifact, []
    if RESOURCE_PRESENTATION not in set(state.get("resource_types", [])):
        return artifact, []
    slides = artifact.get("presentation_outline")
    if not isinstance(slides, list):
        return artifact, []

    allowed_ids = {
        str(item.get("id", "")).strip().upper()
        for item in state.get("learning_outcomes", [])
        if str(item.get("id", "")).strip()
    }
    corrections: list[dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        received_ids = slide_outcome_ids(slide)
        normalized_ids = slide_outcome_ids(
            slide,
            allowed_ids,
            infer_from_text=True,
        )
        legacy_value = str(slide.get("outcome_id", "")).strip()
        canonical_legacy = normalized_ids[0] if len(normalized_ids) == 1 else ""
        if (
            slide.get("outcome_ids") != normalized_ids
            or legacy_value != canonical_legacy
        ):
            corrections.append(
                {
                    "resource": RESOURCE_PRESENTATION,
                    "changes": {
                        f"slide_{index}_outcome_ids": {
                            "received": received_ids,
                            "used": normalized_ids,
                        }
                    },
                }
            )
        slide["outcome_ids"] = normalized_ids
        slide["outcome_id"] = canonical_legacy
    return artifact, corrections


def _canonicalize_presentation_assessment_overview(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Insere uma secção legível com todas as tarefas de avaliação aprovadas."""

    if not isinstance(artifact, dict):
        return artifact, []
    if RESOURCE_PRESENTATION not in set(state.get("resource_types", [])):
        return artifact, []
    slides = artifact.get("presentation_outline")
    if not isinstance(slides, list):
        return artifact, []

    assessments = [
        item
        for item in state.get("assessment_activities", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]
    if not assessments:
        return artifact, []

    def clean(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def compact(value: Any, limit: int = 72) -> str:
        text = clean(value) or "A confirmar pelo docente"
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    assessment_slides: list[dict[str, Any]] = []
    chunks = [
        assessments[offset : offset + 3]
        for offset in range(0, len(assessments), 3)
    ]
    for chunk_index, chunk in enumerate(chunks, start=1):
        title = PRESENTATION_ASSESSMENT_TITLE
        if len(chunks) > 1:
            title += f" ({chunk_index}/{len(chunks)})"
        bullets = []
        visual_items = []
        task_ids = []
        slide_outcomes: list[str] = []
        for task in chunk:
            task_id = clean(task.get("id")).upper()
            purpose = compact(task.get("assessment_purpose"), 24)
            outcome_ids = ", ".join(
                clean(identifier).upper()
                for identifier in task.get("outcome_ids", [])
                if clean(identifier)
            )
            bullets.append(
                f"{task_id} · {purpose} — {compact(task.get('activity'))}"
                + (f" | Resultados: {outcome_ids}" if outcome_ids else "")
                + f" | Evidência: {compact(task.get('evidence'))}"
                + f" | Critério: {compact(task.get('criterion'))}"
            )
            visual_items.append(f"{task_id} · {purpose}")
            task_ids.append(task_id)
            slide_outcomes.extend(
                clean(identifier).upper()
                for identifier in task.get("outcome_ids", [])
                if clean(identifier)
            )
        slide_outcomes = list(dict.fromkeys(slide_outcomes))
        if len(visual_items) == 1:
            visual_items.extend(["Evidência observável", "Critérios explícitos"])
        assessment_slides.append(
            {
                "title": title,
                "bullets": bullets,
                "outcome_id": slide_outcomes[0] if len(slide_outcomes) == 1 else "",
                "outcome_ids": slide_outcomes,
                "visual_mode": "diagrama",
                "visual_asset_id": "",
                "visual_prompt": "",
                "visual_kind": "processo",
                "visual_title": "Tarefas, evidências e critérios",
                "visual_items": visual_items,
                "visual_source": (
                    "Diagrama nativo gerado pelo CoerIA a partir das tarefas e "
                    "critérios aprovados pelo docente."
                ),
                "alt_text": (
                    "Síntese das tarefas de avaliação "
                    + ", ".join(task_ids)
                    + ", respetivas evidências e critérios."
                ),
            }
        )

    title_prefix = PRESENTATION_ASSESSMENT_TITLE.casefold()
    retained_slides = [
        slide
        for slide in slides
        if not (
            isinstance(slide, dict)
            and clean(slide.get("title")).casefold().startswith(title_prefix)
        )
    ]
    insert_at = max(len(retained_slides) - 1, 0)
    normalized_slides = [
        *retained_slides[:insert_at],
        *assessment_slides,
        *retained_slides[insert_at:],
    ]
    if normalized_slides == slides:
        return artifact, []
    return (
        {**artifact, "presentation_outline": normalized_slides},
        [
            {
                "resource": RESOURCE_PRESENTATION,
                "changes": {
                    "assessment_overview": {
                        "used": [slide["title"] for slide in assessment_slides]
                    }
                },
            }
        ],
    )


def _canonicalize_resource_visuals(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Completa e valida deterministicamente a especificação visual dos slides.

    Os diagramas nativos continuam sempre disponíveis como fallback editável. Uma
    imagem documental só usa IDs existentes no catálogo extraído; as imagens são
    candidatas e não são impostas aos slides. A capa e o slide final permanecem com
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
    source_assets = {
        str(item.get("id", "")): item
        for item in state.get("source_images", [])
        if isinstance(item, dict)
        and str(item.get("id", "")).strip()
        and item.get("origin_type") != "user_uploaded"
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

        outcome_links = slide_outcome_ids(slide, set(outcomes))
        outcome_id = outcome_links[0] if outcome_links else ""
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
        content_ids = [item.get("id") for item in contents]
        if (
            not MIN_OUTCOMES <= len(contents) <= MAX_OUTCOMES
            or len(content_ids) != len(set(content_ids))
            or any(not item.get("title") for item in contents)
            or any(not str(item.get("description", "")).strip() for item in contents)
        ):
            raise AgentGenerationError(
                "A análise curricular deve conter conteúdos com IDs únicos, título "
                "e descrição."
            )

        objective_like_descriptions = [
            str(item.get("id", "?"))
            for item in contents
            if starts_with_objective_action_verb(
                str(item.get("description", ""))
            )
        ]
        if objective_like_descriptions:
            raise AgentGenerationError(
                "As descrições dos conteúdos devem caracterizar a matéria em linguagem "
                "expositiva e não começar por verbos de objetivo ou desempenho. "
                "Temas a corrigir: "
                + ", ".join(objective_like_descriptions)
                + "."
            )

        expected_outcomes = {
            str(item.get("id", ""))
            for item in state.get("learning_outcomes", [])
            if str(item.get("id", "")).strip()
        }
        if expected_outcomes:
            content_outcomes = {
                str(identifier)
                for item in contents
                for identifier in item.get("outcome_ids", [])
                if str(identifier).strip()
            }
            rows_without_links = [
                str(item.get("id", "?"))
                for item in contents
                if not item.get("outcome_ids")
            ]
            if (
                content_outcomes != expected_outcomes
                or rows_without_links
            ):
                raise AgentGenerationError(
                    "Os conteúdos devem estar associados exatamente aos resultados de "
                    "aprendizagem aprovados, sem linhas ou IDs desligados."
                )

        reduction = state.get("source_reduction", {})
        expected_sources = [
            str(item.get("source", "")).strip()
            for item in reduction.get("sources", [])
            if str(item.get("source", "")).strip()
        ]
        if reduction.get("applied") and expected_sources:
            coverage = artifact.get("source_coverage", [])
            received_sources = [
                str(item.get("source", "")).strip()
                for item in coverage
                if isinstance(item, dict)
            ]
            known_content_ids = {str(identifier) for identifier in content_ids}
            invalid_rows = [
                item
                for item in coverage
                if not isinstance(item, dict)
                or not str(item.get("contribution", "")).strip()
                or not [
                    concept for concept in item.get("key_concepts", [])
                    if str(concept).strip()
                ]
                or not [
                    identifier for identifier in item.get("content_ids", [])
                    if str(identifier).strip()
                ]
                or any(
                    str(identifier) not in known_content_ids
                    for identifier in item.get("content_ids", [])
                )
            ]
            if (
                set(received_sources) != set(expected_sources)
                or len(received_sources) != len(set(received_sources))
                or invalid_rows
            ):
                missing = sorted(set(expected_sources) - set(received_sources))
                raise AgentGenerationError(
                    "A análise curricular deve demonstrar cobertura de todas as fontes "
                    "reduzidas, com contribuição, conceitos-chave e conteúdos associados"
                    + (f" (em falta: {', '.join(missing)})." if missing else ".")
                )
        return

    if stage in {
        "learning_outcomes",
        "assessment_activities",
        "teaching_activities",
    }:
        if not isinstance(artifact, list) or not artifact:
            raise AgentGenerationError("O agente devolveu uma lista vazia para esta etapa.")

    if stage == "learning_outcomes":
        if not MIN_OUTCOMES <= len(artifact) <= MAX_OUTCOMES:
            raise AgentGenerationError("Devem existir entre 4 e 10 resultados de aprendizagem.")
        outcome_ids = [item["id"] for item in artifact]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise AgentGenerationError("Os resultados de aprendizagem contêm IDs duplicados.")
        if not all(is_learning_outcome_id(identifier) for identifier in outcome_ids):
            raise AgentGenerationError(
                "Os resultados de aprendizagem devem usar IDs RA1, RA2, ..."
            )
        invalid_ai_modes = [
            item["id"]
            for item in artifact
            if str(item.get("ai_mode", "")).strip() not in AI_MODES
        ]
        if invalid_ai_modes:
            raise AgentGenerationError(
                "Cada resultado deve indicar AI-off, AI-on ou on-AI. Corrigir: "
                + ", ".join(invalid_ai_modes)
                + "."
            )

        taxonomy_type = validate_taxonomy_choice(
            state["course"].get("taxonomy_type", "SOLO")
        )
        invalid = [
            item["id"] for item in artifact
            if not taxonomy_verb_allowed(
                taxonomy_type,
                str(item.get("taxonomy_level", "")),
                str(item.get("action_verb", "")),
            )
            or not has_single_action_verb(
                str(item.get("statement", "")),
                str(item.get("action_verb", "")),
                taxonomy_type,
            )
        ]
        if invalid:
            invalid_by_id = {item["id"]: item for item in artifact if item["id"] in invalid}
            details = "; ".join(
                f"{identifier}: verbo='{invalid_by_id[identifier].get('action_verb', '')}', "
                f"nível='{invalid_by_id[identifier].get('taxonomy_level', '')}', "
                f"enunciado='{invalid_by_id[identifier].get('statement', '')}'"
                for identifier in invalid
            )
            raise AgentGenerationError(
                "Cada resultado deve usar um nível e verbo compatíveis, começar pelo "
                "action_verb declarado e conter um único verbo de ação principal. "
                "São permitidos infinitivos subordinados "
                "em complementos (por exemplo, 'explicar como configurar'), mas não "
                "coordenações de duas ações principais do tipo 'e/ou + infinitivo'. "
                "Se o objetivo geral de origem tiver várias ações coordenadas, distribui-as "
                "por resultados diferentes em vez de copiares a coordenação. Corrigir: " + details
            )

    if stage in {"assessment_activities", "teaching_activities"}:
        identifiers = [item["id"] for item in artifact]
        expected_prefix = "TA" if stage == "assessment_activities" else "AE"
        if (
            len(identifiers) != len(set(identifiers))
            or not all(
                is_structured_activity_id(identifier, expected_prefix)
                for identifier in identifiers
            )
        ):
            raise AgentGenerationError(
                f"A proposta deve usar IDs {expected_prefix}1, {expected_prefix}2, ... "
                "sem duplicados."
            )

    if stage == "teaching_activities":
        expected = {item["id"] for item in state["learning_outcomes"]}
        covered = set(_flattened_ids(artifact, "outcome_ids", "outcome_id"))
        if covered != expected:
            raise AgentGenerationError(
                "As atividades de ensino-aprendizagem devem cobrir todos e apenas "
                "os resultados definidos."
            )
        invalid_ai_mode_rows = []
        for item in artifact:
            inherited_mode = linked_ai_mode(
                item.get("outcome_ids") or [item.get("outcome_id", "")],
                state.get("learning_outcomes", []),
            )
            if (
                inherited_mode is None
                or str(item.get("ai_mode", "")).strip() != inherited_mode
            ):
                invalid_ai_mode_rows.append(str(item.get("id", "?")))
        if invalid_ai_mode_rows:
            raise AgentGenerationError(
                "Cada atividade de ensino-aprendizagem deve ter o mesmo AI-mode "
                "de todos os resultados associados. Separe atividades que liguem "
                "resultados com modos diferentes. Corrigir: "
                + ", ".join(invalid_ai_mode_rows)
                + "."
            )

    if stage == "assessment_activities":
        teaching_by_id = {
            str(item.get("id", "")): item
            for item in state.get("teaching_activities", [])
        }
        allowed_teaching = set(teaching_by_id)
        expected_outcomes = {
            str(item.get("id", ""))
            for item in state.get("learning_outcomes", [])
            if str(item.get("id", "")).strip()
        }
        invalid_assessments = []
        for item in artifact:
            problems = []
            teaching_links = item.get("teaching_activity_ids", [])
            outcome_links = item.get("outcome_ids", [])
            if not teaching_links:
                problems.append("sem atividades de ensino-aprendizagem")
            elif set(teaching_links) - allowed_teaching:
                problems.append("contém atividades de ensino-aprendizagem desconhecidas")
            if not outcome_links:
                problems.append("sem resultados avaliados diretamente")
            elif set(outcome_links) - expected_outcomes:
                problems.append("contém resultados desconhecidos")
            for outcome_id in outcome_links:
                if not any(
                    outcome_id
                    in (
                        teaching_by_id[teaching_id].get("outcome_ids")
                        or [teaching_by_id[teaching_id].get("outcome_id", "")]
                    )
                    for teaching_id in teaching_links
                    if teaching_id in teaching_by_id
                ):
                    problems.append(
                        f"{outcome_id} não é desenvolvido pelas atividades selecionadas"
                    )
            inherited_mode = linked_ai_mode(
                outcome_links,
                state.get("learning_outcomes", []),
            )
            received_mode = str(item.get("ai_mode", "")).strip()
            if inherited_mode is None:
                problems.append("associa resultados com modos de IA diferentes")
            elif received_mode != inherited_mode:
                problems.append("modo de IA diferente dos resultados associados")
            if any(
                str(teaching_by_id[teaching_id].get("ai_mode", "")).strip()
                != received_mode
                for teaching_id in teaching_links
                if teaching_id in teaching_by_id
            ):
                problems.append(
                    "modo de IA diferente das atividades de ensino-aprendizagem"
                )
            if item.get("assessment_purpose") not in ASSESSMENT_PURPOSES:
                problems.append("finalidade diferente de Formativa ou Sumativa")
            if problems:
                invalid_assessments.append(
                    f"{item.get('id', '?')}: " + ", ".join(problems)
                )
        if invalid_assessments:
            raise AgentGenerationError(
                "Cada avaliação deve ligar diretamente resultados às atividades que os "
                "desenvolvem e ser Formativa ou Sumativa. "
                + "; ".join(invalid_assessments)
            )
        covered_outcomes = {
            str(outcome_id)
            for item in artifact
            for outcome_id in item.get("outcome_ids", [])
            if str(outcome_id).strip()
        }
        if covered_outcomes != expected_outcomes:
            raise AgentGenerationError(
                "As tarefas devem cobrir diretamente todos e apenas os resultados de aprendizagem."
            )

    if stage == "teaching_activities":
        if any(
            not item.get("practice")
            or not item.get("support")
            or not item.get("feedback_strategy")
            for item in artifact
        ):
            raise AgentGenerationError(
                "Cada atividade de ensino-aprendizagem deve explicitar prática, "
                "acompanhamento e feedback."
            )

    if stage == "pedagogical_design":
        if not isinstance(artifact, dict):
            raise AgentGenerationError(
                "O planeamento das aulas deve ser um objeto estruturado."
            )
        lessons = artifact.get("lessons", [])
        if not isinstance(lessons, list) or not lessons:
            raise AgentGenerationError(
                "O planeamento deve conter pelo menos uma aula."
            )
        known_components = {
            str(item.get("id", ""))
            for stage_name in ("teaching_activities", "assessment_activities")
            for item in state.get(stage_name, [])
            if str(item.get("id", "")).strip()
        }
        invalid_lessons: list[str] = []
        complete_ai_proposal = (
            isinstance(state.get("_ai_assistance_request"), dict)
            and state["_ai_assistance_request"].get("mode")
            == "complete_stage_proposal"
        )
        for index, lesson in enumerate(lessons, start=1):
            problems: list[str] = []
            duration = lesson.get("duration_minutes")
            components = lesson.get("component_ids", [])
            if not isinstance(duration, int) or duration <= 0:
                problems.append("duração inválida")
            if lesson.get("session_type") not in LESSON_TYPES:
                problems.append("tipo de sessão inválido")
            if not isinstance(components, list):
                problems.append("atividades ou avaliações inválidas")
            elif set(components) - known_components:
                problems.append("contém componentes desconhecidos")
            if not isinstance(lesson.get("notes", ""), str):
                problems.append("texto opcional inválido")
            elif complete_ai_proposal and not str(lesson.get("notes", "")).strip():
                problems.append(
                    "a proposta completa de IA deve explicitar o foco curricular em notes"
                )
            if problems:
                invalid_lessons.append(f"Aula {index}: " + ", ".join(problems))
        expected_contact_minutes = round(
            float(state.get("course", {}).get("contact_hours", 0) or 0) * 60
        )
        if expected_contact_minutes > 0:
            planned_minutes = sum(
                int(lesson.get("duration_minutes", 0) or 0)
                for lesson in lessons
                if isinstance(lesson, dict)
                and isinstance(lesson.get("duration_minutes"), int)
            )
            if planned_minutes != expected_contact_minutes:
                invalid_lessons.append(
                    "Duração total das aulas: "
                    f"{planned_minutes} minutos; deve corresponder às horas de contacto "
                    f"({expected_contact_minutes} minutos)"
                )
        invalid_lessons.extend(
            lesson_ai_mode_issues(
                {**state, "pedagogical_design": artifact}
            )
        )
        if invalid_lessons:
            raise AgentGenerationError(
                "O planeamento das aulas está incompleto. " + "; ".join(invalid_lessons)
            )

    if stage == "resources":
        selected = set(artifact["selected_types"])
        requested = set(state.get("resource_types", []))
        if selected != requested or len(artifact["selected_types"]) != len(selected):
            raise AgentGenerationError("Os recursos devolvidos não respeitam a seleção do docente.")

        if not state.get("resource_generation_scope"):
            quality = evaluate_quality(state, artifact)
            errors = [
                str(check.get("detail", ""))
                for check in quality.get("checks", [])
                if check.get("status") == "error"
            ]
            if RESOURCE_TEST in requested:
                test_entries = artifact.get("tests", [])
                if not test_entries and artifact.get("test", {}).get("questions"):
                    test_entries = [{"test": artifact["test"]}]
                for entry in test_entries:
                    test_data = entry.get("test", {})
                    question_ids = [
                        str(item.get("id", ""))
                        for item in test_data.get("questions", [])
                    ]
                    if len(question_ids) != len(set(question_ids)):
                        errors.append("Um teste contém IDs de questão duplicados.")
                    if any(
                        int(item.get("points", 0) or 0) <= 0
                        for item in test_data.get("questions", [])
                    ):
                        errors.append("Todas as questões devem ter cotação positiva.")
            if RESOURCE_PRACTICAL in requested:
                practical = artifact.get("practical_activity", {})
                if int(practical.get("duration_minutes", 0) or 0) <= 0:
                    errors.append("A duração deve ser positiva.")
                if any(
                    int(item.get("order", 0) or 0) <= 0
                    for item in practical.get("steps", [])
                ):
                    errors.append("A ordem das etapas da atividade deve ser positiva.")
                if any(
                    int(item.get("weight", 0) or 0) <= 0
                    for item in practical.get("criteria", [])
                ):
                    errors.append("Os critérios da atividade devem ter peso positivo.")
            if errors:
                raise AgentGenerationError(
                    "Os recursos contêm incoerências: " + "; ".join(errors)
                )
            return

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
            invalid_slides: list[str] = []
            for index, slide in enumerate(artifact["presentation_outline"], start=1):
                issues = presentation_visual_issues(state, slide)
                if issues:
                    invalid_slides.append(
                        f"slide {index}: " + "; ".join(issues)
                    )
            if invalid_slides:
                raise AgentGenerationError(
                    "A especificação visual está incompleta — "
                    + " | ".join(invalid_slides)
                    + "."
                )
            assessment_overview_issues = presentation_assessment_overview_issues(
                state,
                artifact["presentation_outline"],
            )
            if assessment_overview_issues:
                raise AgentGenerationError(
                    "A apresentação não inclui corretamente a secção de avaliação — "
                    + "; ".join(assessment_overview_issues)
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


def _learning_outcome_retry_instructions(
    validation_message: str,
    state: dict[str, Any],
) -> str:
    """Instruções fortes para reparar resultados rejeitados pelo guardrail.

    O feedback de validação faz parte das instruções (não apenas do contexto JSON)
    para reduzir a probabilidade de o modelo repetir coordenações já rejeitadas.
    """

    return (
        "\n\nREPARAÇÃO OBRIGATÓRIA DA TENTATIVA ANTERIOR. "
        "A resposta anterior foi rejeitada pelo validador e não pode ser repetida. "
        f"Erro concreto: {validation_message} "
        "Reescreve apenas o necessário, preservando os resultados que já estão corretos. "
        "Para cada resultado indicado em 'Corrigir', mantém exatamente um verbo de ação "
        "principal. Se existir uma construção 'verbo 1 ... e/ou verbo 2 ...', tens de: "
        "(a) reformular o resultado para conservar apenas uma ação principal; ou "
        "(b) separar as ações em dois resultados distintos, cada um iniciado por um verbo "
        "do catálogo controlado. Não copies literalmente intenções gerais coordenadas. "
        "Depois da reparação, confirma novamente que existem entre 4 e 10 resultados, "
        "com IDs únicos e um único verbo de ação principal em cada enunciado."
    )


def _simplify_coordinated_learning_outcome_statement(
    statement: str,
    declared_verb: str,
) -> str | None:
    """Último fallback: remove uma segunda ação principal coordenada.

    Só atua quando o enunciado já começa pelo verbo declarado. Não inventa verbos nem
    altera ligações curriculares. É usado apenas depois de esgotadas as retentativas do
    modelo, evitando bloquear a sessão por coordenações persistentes.
    """

    text = str(statement or "").strip()
    verb = str(declared_verb or "").strip()
    if not text or not verb:
        return None
    if not re.match(rf"^{re.escape(verb)}\b", text, flags=re.IGNORECASE):
        return None

    match = re.search(
        r"\s+(?:e|ou)\s+([A-Za-zÀ-ÖØ-öø-ÿ]+(?:ar|er|ir))\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None

    before = text[: match.start()].strip(" ,;:")
    second_verb_end = match.end()
    if before.casefold() == verb.casefold():
        rest = text[second_verb_end:].strip(" ,;:")
        if not rest:
            return None
        candidate = f"{text[:len(verb)]} {rest}"
    else:
        candidate = before

    candidate = candidate.rstrip(" .;:") + "."
    return candidate


def _fallback_repair_learning_outcome_coordination(
    artifact: Any,
    state: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Repara coordenações persistentes apenas como fallback final.

    A reparação só é aceite se o artefacto completo passar a validação normal.
    """

    if not isinstance(artifact, list):
        return artifact, []
    taxonomy = validate_taxonomy_choice(
        state.get("course", {}).get("taxonomy_type", "SOLO")
    )
    repaired = deepcopy(artifact)
    corrections: list[dict[str, Any]] = []
    for item in repaired:
        statement = str(item.get("statement", ""))
        declared = str(item.get("action_verb", ""))
        if has_single_action_verb(statement, declared, taxonomy):
            continue
        candidate = _simplify_coordinated_learning_outcome_statement(
            statement, declared
        )
        if candidate is None or not has_single_action_verb(
            candidate, declared, taxonomy
        ):
            return artifact, []
        item["statement"] = candidate
        corrections.append(
            {
                "field": f"{item.get('id', '?')}.statement",
                "reason": "segunda ação principal removida após retentativas de IA",
                "from": statement,
                "to": candidate,
            }
        )
    return repaired, corrections


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
        if isinstance(state.get("_ai_assistance_request"), dict):
            instructions += (
                " Esta é uma proposta de substituição da etapa completa. Considera o "
                "teacher_request e o current_stage_artifact_read_only enviados no contexto: "
                "preserva o que já estiver adequado, corrige ou completa o restante e não "
                "ignores relações ou dados válidos do rascunho atual."
            )
        if stage == "learning_outcomes":
            instructions += (
                f" Usa exclusivamente este catálogo controlado de verbos {selected_taxonomy}: "
                + json.dumps(
                    taxonomy_catalogue_for_prompt(selected_taxonomy),
                    ensure_ascii=False,
                )
                + "."
            )
        if stage == "curriculum_analysis":
            required_outcomes = [
                item["id"] for item in state.get("learning_outcomes", [])
            ]
            if required_outcomes:
                instructions += (
                    " Os resultados de aprendizagem já foram aprovados pelo docente e "
                    "constituem a referência desta etapa. Em cada conteúdo, "
                    "outcome_ids nunca pode estar vazio e usa apenas IDs desta lista: "
                    f"{required_outcomes}. A união dos outcome_ids dos conteúdos deve "
                    "ser exatamente essa lista. Não alteres nem reformules os resultados. "
                    "Para cada conteúdo, usa um título "
                    "temático nominal e uma descrição expositiva da matéria abrangida. "
                    "Não inicies description por verbos como identificar, compreender, "
                    "analisar, aplicar ou desenvolver; essas formulações pertencem aos "
                    "resultados de aprendizagem."
                )
            reduction = state.get("source_reduction", {})
            source_names = [
                str(item.get("source", "")).strip()
                for item in reduction.get("sources", [])
                if str(item.get("source", "")).strip()
            ]
            if reduction.get("applied") and source_names:
                instructions += (
                    " As fontes documentais foram reduzidas automaticamente, mas todas devem "
                    "ser analisadas. Não dês prioridade automática à primeira fonte, à mais "
                    "curta ou à ficha formal da UC. Usa os metadados explícitos da UC e os "
                    "documentos curriculares para delimitar o âmbito, e usa as restantes fontes "
                    "para enriquecer os conteúdos com contributos distintivos que estejam "
                    "realmente presentes nos textos. Preserva nomes de modelos, teorias, "
                    "princípios e frameworks relevantes. Em source_coverage inclui exatamente "
                    f"uma linha para cada uma destas fontes: {source_names}. Cada linha deve "
                    "explicar a contribuição específica da fonte, listar conceitos-chave "
                    "observáveis nela e ligar essa contribuição a pelo menos um ID C*. Antes "
                    "de responder, confirma que nenhuma fonte ficou sem representação. "
                )
        if stage == "learning_outcomes":
            instructions += (
                " Em cada resultado, statement começa exatamente pelo action_verb declarado. "
                "taxonomy_level pertence à taxonomia selecionada e action_verb pertence ao "
                "catálogo desse nível. Esse é o único verbo de ação principal. Podes usar "
                "infinitivos subordinados "
                "quando forem necessários para completar o sentido (por exemplo, 'explicar como "
                "configurar'), mas evita coordenar duas ações principais com 'e + infinitivo' "
                "ou 'ou + infinitivo'. Se uma intenção geral contiver várias ações coordenadas, "
                "não a copies literalmente: distribui essas ações por resultados diferentes. "
                "Usa a informação de referência e os objetivos gerais introduzidos pelo docente "
                "apenas como contexto para definir o que o estudante deverá demonstrar; a "
                "estrutura curricular detalhada será produzida e associada na etapa seguinte. "
                "Se optional_assumptions_for_learning_outcomes contiver elementos, considera-os "
                "como condições contextuais facultativas indicadas pelo docente; se estiver "
                "vazio, não inventes pressupostos nem bloqueies a formulação. "
                "Em ai_mode usa AI-off por defeito. Usa AI-on apenas quando o resultado "
                "pretende competência disciplinar realizada com IA e on-AI apenas quando "
                "a utilização, supervisão ou avaliação da própria IA é objeto de aprendizagem."
            )
        if stage == "assessment_activities":
            instructions += (
                " Em cada avaliação, assessment_purpose tem exatamente um valor: "
                "Formativa ou Sumativa, nunca Mista. teaching_activity_ids nunca pode "
                "estar vazio e usa apenas os IDs indicados em assessment_link_rules. "
                "outcome_ids também nunca pode estar vazio e liga diretamente cada tarefa "
                "aos resultados avaliados. Cada resultado ligado deve ser desenvolvido por "
                "pelo menos uma das atividades selecionadas. O conjunto das tarefas deve "
                "cobrir diretamente todos os resultados. Em evidence e "
                "criterion torna observável o desempenho expresso pelos verbos dos "
                "resultados associados às atividades selecionadas. ai_mode deve ser "
                "exatamente o modo comum dos resultados e atividades associados. Em "
                "AI-off exige desempenho autónomo; em AI-on mantém o estudante responsável "
                "pelo produto; em on-AI avalia o processo e o julgamento sobre a IA."
            )
        if stage == "teaching_activities":
            instructions += (
                " Em activity e practice torna explícitas ações através das quais o "
                "estudante pratica os verbos dos resultados indicados em outcome_ids. "
                "ai_mode deve ser exatamente o modo comum desses resultados. Em AI-off "
                "preserva prática autónoma; em AI-on promove colaboração significativa "
                "com IA; em on-AI trabalha prompting, orquestração, revisão crítica ou "
                "decisão fundamentada sobre a utilização da IA."
            )
        if stage == "pedagogical_design":
            instructions += (
                " Usa lesson_planning_brief como fonte de verdade e planeia aulas numa ordem "
                "pedagogicamente útil. duration_minutes é um inteiro positivo, session_type "
                "usa lesson_planning_rules e component_ids pode ficar vazio ou conter referências "
                "AE e/ou TA permitidas. Quando associa componentes, não quebres as cadeias de "
                "alinhamento; não é obrigatório distribuir todos os componentes. Numa proposta "
                "completa, a soma das durações "
                "corresponde a contact_minutes_for_lessons e notes nunca fica vazio: resume o "
                "tema, os resultados trabalhados e a progressão prevista com base nos artefactos "
                "anteriores. Na edição manual, notes continua a ser opcional."
            )
        if stage == "resources":
            outcome_ids = [item["id"] for item in state.get("learning_outcomes", [])]
            instructions += (
                " Os únicos identificadores de resultados de aprendizagem permitidos são: "
                f"{', '.join(outcome_ids)}. Confirma aritmeticamente as somas antes de responder. "
                "Nas instruções de cada recurso, respeita o ai_mode do resultado: AI-off "
                "indica realização autónoma sem IA; AI-on permite a IA como meio mantendo "
                "responsabilidade e verificação humanas; on-AI solicita evidências do "
                "processo, revisão crítica ou justificação da (não) utilização da IA."
            )
            item_scope = state.get("resource_item_scope")
            if isinstance(item_scope, dict) and item_scope.get("kind") == "lesson":
                instructions += (
                    " Esta apresentação destina-se exclusivamente à aula indicada em "
                    "resource_item_scope. Usa a duração, o tipo, as notas e apenas os "
                    "componentes e resultados desse âmbito. Inclui uma agenda da aula, "
                    "conteúdo para lecionação, atividades previstas e uma síntese. "
                    "Não introduzas resultados ou avaliações de outras aulas."
                )
            if (
                isinstance(item_scope, dict)
                and item_scope.get("kind") == "assessment_task"
            ):
                instructions += (
                    " Este teste corresponde exclusivamente à tarefa indicada em "
                    "resource_item_scope. Usa a sua finalidade, modalidade, evidência e "
                    "critério; cobre exatamente os resultados associados a essa tarefa."
                )
            if scoped_resource_type in {None, RESOURCE_PRESENTATION}:
                instructions += (
                    " Para cada slide, visual_mode pode ser diagrama, documento ou ia. "
                    "Capa e síntese final devem usar diagrama. "
                    "Não cries uma síntese global das tarefas de avaliação: depois da "
                    "resposta, a aplicação insere antes da síntese final uma secção "
                    f'«{PRESENTATION_ASSESSMENT_TITLE}», construída diretamente a partir '
                    "das tarefas, evidências e critérios aprovados. "
                )
                if any(
                    isinstance(asset, dict)
                    and str(asset.get("id", "")).strip()
                    and asset.get("origin_type") != "user_uploaded"
                    for asset in state.get("source_images", [])
                ):
                    instructions += (
                        "source_image_catalogue contém apenas descrições textuais e metadados "
                        "das imagens documentais candidatas; nenhuma imagem ou miniatura está "
                        "anexada ao pedido. Usa uma candidata somente quando a descrição textual "
                        "for claramente adequada ao conteúdo do slide; não assumes conteúdo "
                        "visual que não esteja descrito e não tens de usar nenhuma. Para uma "
                        "imagem adequada, copia exatamente o id para visual_asset_id, "
                        "define visual_mode=documento e deixa visual_prompt vazio. Não inventes "
                        "IDs nem uses uma imagem meramente decorativa. Uma imagem documental "
                        "claramente adequada tem prioridade sobre gerar uma imagem por IA. "
                    )
                else:
                    instructions += (
                        "Não existem imagens documentais disponíveis; nunca uses documento e "
                        "não inventes visual_asset_id. "
                    )
                if state.get("ai_image_generation_enabled"):
                    instructions += (
                        "A geração de imagens por IA foi autorizada. Podes usar ia apenas em "
                        "slides de conteúdo onde uma ilustração acrescente valor pedagógico real "
                        "e nenhuma imagem documental adequada esteja disponível; "
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
                attempt_instructions = instructions
                if repair_feedback and stage == "learning_outcomes":
                    attempt_instructions += _learning_outcome_retry_instructions(
                        str(repair_feedback.get("validation_error", "")),
                        state,
                    )
                request_input = json.dumps(request_context, ensure_ascii=False)
                if (
                    stage == "resources"
                    and scoped_resource_type in {None, RESOURCE_PRESENTATION}
                ):
                    request_input = _source_image_text_input(request_context)
                request_options = {
                    "model": request_model,
                    "instructions": attempt_instructions,
                    "input": request_input,
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
                if stage == "learning_outcomes":
                    artifact, guardrail_corrections = (
                        _canonicalize_learning_outcomes(artifact, state)
                    )
                elif stage == "assessment_activities":
                    artifact, guardrail_corrections = (
                        _canonicalize_assessment_activities(artifact, state)
                    )
                elif stage == "teaching_activities":
                    artifact, guardrail_corrections = (
                        _canonicalize_teaching_activities(artifact, state)
                    )
                elif stage == "pedagogical_design":
                    artifact, guardrail_corrections = (
                        _canonicalize_lesson_planning(artifact, state)
                    )
                elif stage == "resources":
                    artifact, test_corrections = _canonicalize_resource_test(
                        artifact,
                        state,
                    )
                    artifact, practical_corrections = (
                        _canonicalize_resource_practical(artifact, state)
                    )
                    artifact, assessment_overview_corrections = (
                        _canonicalize_presentation_assessment_overview(
                            artifact,
                            state,
                        )
                    )
                    artifact, presentation_outcome_corrections = (
                        _canonicalize_resource_presentation_outcomes(
                            artifact,
                            state,
                        )
                    )
                    artifact, visual_corrections = (
                        _canonicalize_resource_visuals(artifact, state)
                    )
                    guardrail_corrections = [
                        *test_corrections,
                        *practical_corrections,
                        *assessment_overview_corrections,
                        *presentation_outcome_corrections,
                        *visual_corrections,
                    ]
                _validate_artifact(stage, artifact, state)
            except (AgentGenerationError, json.JSONDecodeError, KeyError, TypeError) as error:
                validation_message = (
                    str(error)
                    if isinstance(error, AgentGenerationError)
                    else "A resposta estruturada está incompleta ou contém tipos inválidos."
                )
                fallback_accepted = False
                if attempt == attempts:
                    if (
                        stage == "learning_outcomes"
                        and isinstance(error, AgentGenerationError)
                        and validation_message.startswith("Cada resultado deve usar")
                    ):
                        repaired_artifact, fallback_corrections = (
                            _fallback_repair_learning_outcome_coordination(
                                artifact, state
                            )
                        )
                        if fallback_corrections:
                            try:
                                _validate_artifact(
                                    stage, repaired_artifact, state
                                )
                            except AgentGenerationError:
                                pass
                            else:
                                artifact = repaired_artifact
                                guardrail_corrections = [
                                    *guardrail_corrections,
                                    *fallback_corrections,
                                ]
                                fallback_accepted = True
                    if not fallback_accepted:
                        raise AgentGenerationError(
                            f"{validation_message} A geração foi repetida automaticamente "
                            f"{attempts} vezes sem produzir uma proposta válida."
                        ) from error
                if not fallback_accepted:
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


class OpenAILocalizedAssistanceAgent:
    """Pede ao fornecedor apenas o fragmento explicitamente escolhido pelo docente."""

    def __init__(
        self,
        model: str | None = None,
        *,
        client_factory: Callable[[], Any] | None = None,
        provider_name: str = "OpenAI Responses API",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model or config_value("OPENAI_MODEL", DEFAULT_MODEL)
        self.timeout_seconds = float(config_value("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(config_value("OPENAI_MAX_RETRIES", "2"))
        self.max_output_tokens = int(
            config_value("OPENAI_ASSISTANCE_MAX_OUTPUT_TOKENS", "4000")
        )
        self.reasoning_effort = config_value("OPENAI_REASONING_EFFORT", "minimal")
        self.client_factory = client_factory
        self.provider_name = provider_name
        self.api_key_env = api_key_env

    def propose(
        self,
        stage: str,
        state: dict[str, Any],
        scope_path: list[str | int],
        scope_label: str,
        instruction: str,
        current_value: Any,
    ) -> GenerationResult:
        if not scope_path:
            raise AgentGenerationError(
                "O assistente localizado requer uma célula, linha ou tabela concreta."
            )
        if not os.getenv(self.api_key_env):
            raise AgentGenerationError(
                f"A assistência localizada requer {self.api_key_env}."
            )
        OpenAI = None
        if self.client_factory is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise AgentGenerationError(
                    "A biblioteca OpenAI não está instalada."
                ) from error

        selected_taxonomy = validate_taxonomy_choice(
            state.get("course", {}).get("taxonomy_type", "SOLO")
        )
        schema = _schema_for_scope(stage, state, scope_path)
        instructions = (
            "És um assistente de autoria pedagógica. Responde em português europeu. "
            "Propõe exclusivamente um valor de substituição para o âmbito indicado pelo "
            "docente. Não devolvas o artefacto completo, campos irmãos, índices, alternativas "
            "ou explicações fora do objeto estruturado. Conserva IDs e relações existentes "
            "salvo quando o âmbito escolhido os inclua explicitamente. Usa apenas os dados "
            "fornecidos e respeita exclusivamente a Taxonomia "
            f"{selected_taxonomy}. O campo proposal tem de corresponder exatamente ao "
            "esquema do fragmento selecionado."
        )
        context = {
            "stage": stage,
            "scope": {"label": scope_label, "path": scope_path},
            "teacher_instruction": instruction,
            "current_value": current_value,
            "current_stage_artifact_read_only": state.get(stage),
            "pedagogical_context": _upstream_context(state, stage),
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
                        "name": f"coeria_assistance_{stage}",
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
            if supports_reasoning_effort(self.model):
                request_options["reasoning"] = {"effort": self.reasoning_effort}
            response = client.responses.create(**request_options)
            payload = json.loads(response.output_text)
            proposal = payload["proposal"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AgentGenerationError(
                "A IA não devolveu um fragmento compatível com o âmbito escolhido."
            ) from error
        except AgentGenerationError:
            raise
        except Exception as error:
            raise AgentGenerationError(
                f"A assistência localizada não ficou disponível. {error}"
            ) from error

        usage = getattr(response, "usage", None)
        return GenerationResult(
            artifact=proposal,
            metadata={
                "provider": self.provider_name,
                "role": "assistente localizado",
                "model": self.model,
                "response_id": getattr(response, "id", "não disponível"),
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                "scope_path": list(scope_path),
            },
        )


class IAeduLocalizedAssistanceAgent(OpenAILocalizedAssistanceAgent):
    """Assistência localizada através do fornecedor IAedu selecionado."""

    def __init__(self) -> None:
        super().__init__(
            model=config_value("IAEDU_AGENT_NAME", "Agente IAedu"),
            client_factory=IAeduResponsesAdapter,
            provider_name="IAedu Agent Chat API",
            api_key_env="IAEDU_API_KEY",
        )


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
                            "target": {"type": "string"},
                        },
                        "required": [
                            "severity",
                            "criterion",
                            "message",
                            "target",
                        ],
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
            "cobertura e somas já foi executada: não repitas nem contradigas esses controlos. "
            "Em criterion escreve um rótulo curto e legível em português europeu; nunca uses "
            "identificadores técnicos, inglês ou snake_case. Em cada finding, usa em target "
            "exatamente uma das chaves fornecidas em available_finding_targets. Escolhe o elemento "
            "mais específico relacionado com a observação e usa __stage__ apenas quando a "
            "observação se aplicar realmente a toda a etapa."
        )
        context = {
            "stage": stage,
            "course": state.get("course", {}),
            "upstream": _upstream_context(state, stage),
            "proposed_artifact": artifact,
            "available_finding_targets": available_validation_targets(
                stage, artifact
            ),
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
        "teaching_activities",
        "assessment_activities",
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


def build_localized_assistance_agent(
    provider: str | None,
) -> LocalizedAssistanceAgent:
    """Constrói o assistente que só pode devolver o fragmento selecionado."""

    selected = validate_ai_provider(provider)
    if selected == AI_PROVIDER_IAEDU:
        return IAeduLocalizedAssistanceAgent()
    if selected == AI_PROVIDER_OPENAI:
        return OpenAILocalizedAssistanceAgent()
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
