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
    taxonomy_catalogue_for_prompt,
    taxonomy_level_for_verb,
    taxonomy_verb_allowed,
    validate_taxonomy_choice,
)
from .providers import (
    AI_PROVIDER_IAEDU,
    AI_PROVIDER_OPENAI,
    IAeduResponsesAdapter,
    validate_ai_provider,
)


DEFAULT_MODEL = "gpt-5-nano"


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
        "Cada slide da apresentação inclui visual_kind, visual_title, visual_items, "
        "visual_source e alt_text. visual_items contém entre 2 e 4 textos não vazios; "
        "visual_title, visual_source e alt_text também nunca podem estar vazios. Os "
        "elementos visuais devem apoiar o conteúdo e não servir apenas de decoração. "
        "Cada recurso pedido deve cobrir exatamente todos os IDs dos resultados de "
        "aprendizagem, sem usar IDs desconhecidos. No teste, a soma dos pontos das "
        "questões deve ser igual a total_points. Na atividade prática, a união dos "
        "outcome_ids de todas as etapas deve cobrir exatamente todos os resultados e "
        "os pesos positivos dos critérios devem totalizar exatamente 100."
    ),
}


def _schema_for(stage: str) -> dict[str, Any]:
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
                            "title", "bullets", "outcome_id", "visual_kind",
                            "visual_title", "visual_items", "visual_source", "alt_text"
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
                                    "points": {"type": "integer"},
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
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"artifact": artifact_schemas[stage]},
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


def _canonicalize_resource_visuals(
    artifact: Any, state: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Completa metadados visuais derivados sem repetir toda a geração.

    A apresentação exportada usa diagramas nativos. Quando o fornecedor deixa
    vazios campos estruturais desses diagramas, os valores em falta podem ser
    derivados dos artefactos já aprovados sem alterar o conteúdo pedagógico.
    """

    if not isinstance(artifact, dict):
        return artifact, []
    requested = set(state.get("resource_types", []))
    slides = artifact.get("presentation_outline")
    if "Apresentação PowerPoint" not in requested or not isinstance(slides, list):
        return artifact, []

    allowed_kinds = {"capa", "conceito", "processo", "comparacao", "sintese"}
    kind_aliases = {"comparação": "comparacao", "síntese": "sintese"}
    outcomes = {
        str(item.get("id", "")): item
        for item in state.get("learning_outcomes", [])
        if item.get("id")
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

        visual_source = clean_text(slide.get("visual_source")) or (
            "Diagrama nativo gerado pelo CoerIA a partir dos artefactos aprovados."
        )
        alt_text = clean_text(slide.get("alt_text")) or (
            f"Diagrama «{visual_title}» com os elementos "
            + ", ".join(visual_items)
            + "."
        )
        canonical = {
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
            raise AgentGenerationError(
                "Os resultados devem cobrir todos e apenas os conteúdos curriculares."
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
            raise AgentGenerationError(
                "Os resultados devem cobrir todos e apenas os objetivos gerais."
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
            raise AgentGenerationError(
                "Cada resultado deve começar por exatamente um verbo de ação: "
                + ", ".join(invalid)
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
            invalid_slides = []
            for index, slide in enumerate(artifact["presentation_outline"], start=1):
                visual_items = slide.get("visual_items", [])
                valid_items = (
                    2 <= len(visual_items) <= 4
                    and all(str(item).strip() for item in visual_items)
                )
                if (
                    slide.get("visual_kind") not in allowed_visual_kinds
                    or not str(slide.get("visual_title", "")).strip()
                    or not valid_items
                    or not str(slide.get("visual_source", "")).strip()
                    or not str(slide.get("alt_text", "")).strip()
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
            points = sum(item["points"] for item in artifact["test"]["questions"])
            if (
                covered != expected
                or points != artifact["test"]["total_points"]
                or points <= 0
                or any(item["points"] <= 0 for item in artifact["test"]["questions"])
            ):
                raise AgentGenerationError(
                    "O teste deve cobrir todos os resultados e apresentar uma cotação coerente."
                )

        if "Atividade prática" in requested:
            covered = {
                outcome_id
                for step in artifact["practical_activity"]["steps"]
                for outcome_id in step["outcome_ids"]
            }
            weight = sum(item["weight"] for item in artifact["practical_activity"]["criteria"])
            steps = artifact["practical_activity"]["steps"]
            if (
                covered != expected
                or weight != 100
                or artifact["practical_activity"]["duration_minutes"] <= 0
                or any(item["order"] <= 0 for item in steps)
                or any(item["weight"] <= 0 for item in artifact["practical_activity"]["criteria"])
            ):
                raise AgentGenerationError(
                    "A atividade prática deve cobrir todos os resultados e totalizar 100% nos critérios."
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
        client_factory: Callable[[], Any] | None = None,
        provider_name: str = "OpenAI Responses API",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model or config_value("OPENAI_MODEL", DEFAULT_MODEL)
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
        instructions = (
            f"És o {STAGE_ROLES[stage]} numa aplicação de autoria pedagógica assistida. "
            "Responde em português europeu. Trabalha exclusivamente a partir dos dados "
            "fornecidos pelo docente e dos artefactos anteriores; não inventes fontes, "
            "regulamentos ou contextos institucionais. A sessão usa exclusivamente a "
            f"Taxonomia {selected_taxonomy}; nunca combines SOLO e Bloom. "
            "Quando houver feedback, aplica-o de modo explícito. "
            "A tua proposta será validada por um docente antes de o fluxo avançar. "
            f"Formato obrigatório do campo artifact: {STAGE_REQUIREMENTS[stage]} "
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

        for attempt in range(1, attempts + 1):
            request_context = dict(base_context)
            if repair_feedback:
                request_context["automatic_validation_feedback"] = repair_feedback

            try:
                response = client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    input=json.dumps(request_context, ensure_ascii=False),
                    reasoning={"effort": self.reasoning_effort},
                    max_output_tokens=self.max_output_tokens,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": f"coeria_{stage}",
                            "strict": True,
                            "schema": _schema_for(stage),
                        }
                    },
                )
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
            try:
                payload = json.loads(response.output_text)
                artifact = payload["artifact"]
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
                    artifact, guardrail_corrections = (
                        _canonicalize_resource_visuals(artifact, state)
                    )
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
                        "Corrige o problema indicado e devolve novamente o artefacto "
                        "completo, preservando o conteúdo que já está correto."
                    ),
                    "validation_error": validation_message,
                    "previous_artifact": artifact,
                }
                continue

            duration_ms = round((perf_counter() - started_at) * 1000)
            return GenerationResult(
                artifact=artifact,
                metadata={
                    "provider": self.provider_name,
                    "model": self.model,
                    "response_id": getattr(response, "id", "não disponível"),
                    "duration_ms": duration_ms,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_tokens,
                    "validation_attempts": attempt,
                    "guardrail_corrections": guardrail_corrections,
                },
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
            response = client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(context, ensure_ascii=False),
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=self.max_output_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": f"coeria_critic_{stage}",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
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
