"""Definições dos formulários de edição manual dos artefactos pedagógicos."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"


@dataclass(frozen=True)
class ScalarSpec:
    path: tuple[str, ...]
    label: str
    kind: str = "text"


@dataclass(frozen=True)
class TableSpec:
    title: str
    path: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    template: dict[str, Any]


@dataclass(frozen=True)
class EditorLayout:
    fields: tuple[ScalarSpec, ...] = ()
    tables: tuple[TableSpec, ...] = ()


def _field(key: str, label: str, kind: str = "text") -> FieldSpec:
    return FieldSpec(key, label, kind)


EDITOR_LAYOUTS: dict[str, EditorLayout] = {
    "curriculum_analysis": EditorLayout(
        fields=(
            ScalarSpec(("summary",), "Síntese", "long"),
            ScalarSpec(("assumptions",), "Pressupostos — um por linha", "lines"),
        ),
        tables=(
            TableSpec(
                "Objetivos gerais",
                ("objectives",),
                (_field("id", "ID"), _field("statement", "Objetivo", "long")),
                {"id": "", "statement": ""},
            ),
            TableSpec(
                "Conteúdos identificados",
                ("contents",),
                (
                    _field("id", "ID"),
                    _field("title", "Conteúdo"),
                    _field("description", "Descrição", "long"),
                ),
                {"id": "", "title": "", "description": ""},
            ),
        ),
    ),
    "learning_outcomes": EditorLayout(
        tables=(
            TableSpec(
                "Resultados de aprendizagem",
                (),
                (
                    _field("id", "ID"),
                    _field("outcome_type", "Tipo"),
                    _field("content_links", "Conteúdos", "content_ids"),
                    _field("objective_ids", "Objetivos", "csv"),
                    _field("action_verb", "Verbo"),
                    _field("statement", "Resultado de aprendizagem", "long"),
                ),
                {
                    "id": "",
                    "theme": "",
                    "statement": "",
                    "action_verb": "",
                    "outcome_type": "Conhecimento",
                    "content_links": [],
                    "objective_ids": [],
                },
            ),
        )
    ),
    "outcome_taxonomy": EditorLayout(
        tables=(
            TableSpec(
                "Classificação taxonómica",
                (),
                (
                    _field("outcome_id", "Resultado"),
                    _field("taxonomy", "Taxonomia"),
                    _field("level", "Nível"),
                    _field("action_verb", "Verbo de ação"),
                ),
                {"outcome_id": "", "taxonomy": "", "level": "", "action_verb": ""},
            ),
        )
    ),
    "assessment_activities": EditorLayout(
        tables=(
            TableSpec(
                "Atividades de avaliação",
                (),
                (
                    _field("id", "ID"),
                    _field("outcome_ids", "Resultados", "linked_outcomes"),
                    _field("work_type", "Modalidade"),
                    _field("assessment_purpose", "Finalidade"),
                    _field("activity", "Atividade", "long"),
                    _field("evidence", "Evidência", "long"),
                    _field("criterion", "Critério", "long"),
                ),
                {
                    "id": "",
                    "outcome_id": "",
                    "outcome_ids": [],
                    "work_type": "",
                    "assessment_purpose": "Formativa",
                    "activity": "",
                    "evidence": "",
                    "criterion": "",
                },
            ),
        )
    ),
    "pedagogical_design": EditorLayout(
        fields=(ScalarSpec(("strategy",), "Estratégia pedagógica", "long"),),
        tables=(
            TableSpec(
                "Sequência pedagógica",
                ("sequence",),
                (
                    _field("outcome_id", "Resultado"),
                    _field("focus", "Foco", "long"),
                    _field("assessment", "Avaliação", "long"),
                ),
                {"outcome_id": "", "focus": "", "assessment": ""},
            ),
        ),
    ),
    "teaching_activities": EditorLayout(
        tables=(
            TableSpec(
                "Atividades de ensino-aprendizagem",
                (),
                (
                    _field("id", "ID"),
                    _field("outcome_ids", "Resultados", "linked_outcomes"),
                    _field("assessment_ids", "Avaliações", "csv"),
                    _field("learning_context", "Contexto"),
                    _field("activity", "Atividade", "long"),
                    _field("practice", "Prática", "long"),
                    _field("support", "Acompanhamento", "long"),
                    _field("feedback_strategy", "Feedback", "long"),
                ),
                {
                    "id": "",
                    "outcome_id": "",
                    "outcome_ids": [],
                    "assessment_ids": [],
                    "learning_context": "Presencial",
                    "activity": "",
                    "method": "",
                    "practice": "",
                    "support": "",
                    "feedback_strategy": "",
                },
            ),
        )
    ),
    "alignment_matrix": EditorLayout(
        tables=(
            TableSpec(
                "Matriz de alinhamento",
                (),
                (
                    _field("outcome_id", "Resultado"),
                    _field("objective_ids", "Objetivos", "csv"),
                    _field("content_ids", "Conteúdos", "csv"),
                    _field("taxonomy", "Taxonomia"),
                    _field("taxonomy_level", "Nível"),
                    _field("assessment_ids", "Avaliações", "csv"),
                    _field("assessment_purposes", "Finalidade", "csv"),
                    _field("teaching_activity_ids", "Atividades formativas", "csv"),
                    _field("resource_types", "Recursos", "csv"),
                    _field("status", "Alinhamento", "alignment_status"),
                    _field("rationale", "Justificação", "long"),
                ),
                {
                    "outcome_id": "",
                    "result": "",
                    "objective_ids": [],
                    "content_ids": [],
                    "taxonomy": "",
                    "taxonomy_level": "",
                    "assessment_ids": [],
                    "assessment_purposes": [],
                    "teaching_activity_ids": [],
                    "resource_types": [],
                    "assessment": "Não",
                    "teaching_activity": "Não",
                    "status": "Requer revisão",
                    "rationale": "",
                },
            ),
        )
    ),
    "resources": EditorLayout(
        fields=(
            ScalarSpec(("lesson_worksheet", "title"), "Ficha — título"),
            ScalarSpec(("lesson_worksheet", "overview"), "Ficha — enquadramento", "long"),
            ScalarSpec(("lesson_worksheet", "instructions"), "Ficha — instruções", "long"),
            ScalarSpec(("test", "title"), "Teste — título"),
            ScalarSpec(("test", "instructions"), "Teste — instruções", "long"),
            ScalarSpec(("test", "total_points"), "Teste — cotação total", "integer"),
            ScalarSpec(("practical_activity", "title"), "Atividade prática — título"),
            ScalarSpec(("practical_activity", "context"), "Atividade prática — contexto", "long"),
            ScalarSpec(("practical_activity", "duration_minutes"), "Duração em minutos", "integer"),
            ScalarSpec(("practical_activity", "materials"), "Materiais — um por linha", "lines"),
            ScalarSpec(("practical_activity", "deliverables"), "Entregáveis — um por linha", "lines"),
        ),
        tables=(
            TableSpec(
                "Slides da apresentação",
                ("presentation_outline",),
                (
                    _field("title", "Título"),
                    _field("bullets", "Pontos — um por linha", "lines"),
                    _field("outcome_id", "Resultado"),
                    _field("visual_kind", "Tipo visual"),
                    _field("visual_title", "Título visual"),
                    _field("visual_items", "Itens visuais — um por linha", "lines"),
                    _field("visual_source", "Origem visual", "long"),
                    _field("alt_text", "Texto alternativo", "long"),
                ),
                {
                    "title": "",
                    "bullets": [],
                    "outcome_id": "",
                    "visual_kind": "conceito",
                    "visual_title": "",
                    "visual_items": [],
                    "visual_source": "Conteúdo fornecido pelo docente",
                    "alt_text": "",
                },
            ),
            TableSpec(
                "Secções da ficha de aula",
                ("lesson_worksheet", "sections"),
                (
                    _field("heading", "Título"),
                    _field("content", "Conteúdo", "long"),
                    _field("outcome_ids", "Resultados — IDs separados por vírgulas", "csv"),
                    _field("activity", "Atividade", "long"),
                ),
                {"heading": "", "content": "", "outcome_ids": [], "activity": ""},
            ),
            TableSpec(
                "Questões do teste",
                ("test", "questions"),
                (
                    _field("id", "ID"),
                    _field("outcome_id", "Resultado"),
                    _field("prompt", "Enunciado", "long"),
                    _field("question_type", "Tipo"),
                    _field("points", "Pontos", "integer"),
                    _field("answer_key", "Chave de correção", "long"),
                ),
                {
                    "id": "",
                    "outcome_id": "",
                    "prompt": "",
                    "question_type": "Resposta aberta",
                    "points": 1,
                    "answer_key": "",
                },
            ),
            TableSpec(
                "Etapas da atividade prática",
                ("practical_activity", "steps"),
                (
                    _field("order", "Ordem", "integer"),
                    _field("instruction", "Instrução", "long"),
                    _field("outcome_ids", "Resultados — IDs separados por vírgulas", "csv"),
                ),
                {"order": 1, "instruction": "", "outcome_ids": []},
            ),
            TableSpec(
                "Critérios da atividade prática",
                ("practical_activity", "criteria"),
                (
                    _field("criterion", "Critério"),
                    _field("description", "Descrição", "long"),
                    _field("weight", "Peso (%)", "integer"),
                ),
                {"criterion": "", "description": "", "weight": 0},
            ),
        ),
    ),
}


def editor_layout(stage: str) -> EditorLayout:
    try:
        return EDITOR_LAYOUTS[stage]
    except KeyError as error:
        raise ValueError("Esta etapa ainda não suporta edição manual.") from error


def value_at_path(artifact: Any, path: tuple[str, ...]) -> Any:
    value = artifact
    for key in path:
        value = value[key]
    return value


def set_value_at_path(artifact: Any, path: tuple[str, ...], value: Any) -> None:
    parent = artifact
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value


def format_editor_value(value: Any, kind: str) -> Any:
    if kind == "lines":
        return "\n".join(str(item) for item in (value or []))
    if kind == "csv":
        return ", ".join(str(item) for item in (value or []))
    if kind == "content_links":
        return "\n".join(
            f"{item.get('content_id', '')} | {item.get('importance', 'Principal')}"
            for item in (value or [])
        )
    if kind == "integer":
        return int(value or 0)
    return str(value or "")


def parse_editor_value(value: Any, kind: str) -> Any:
    if kind == "integer":
        return int(float(value or 0))
    text = str(value or "")
    if kind == "lines":
        return [line.strip() for line in text.splitlines() if line.strip()]
    if kind == "csv":
        return [item.strip() for item in re.split(r"[,;\n]+", text) if item.strip()]
    if kind == "content_links":
        links = []
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            parts = [part.strip() for part in clean.split("|", maxsplit=1)]
            links.append(
                {
                    "content_id": parts[0],
                    "importance": parts[1] if len(parts) > 1 else "Principal",
                }
            )
        return links
    return text.strip()


def editor_field_value(target: dict[str, Any], field: FieldSpec) -> Any:
    """Apresenta apenas o valor pedagógico visível da coluna."""

    if field.kind == "content_ids":
        return ", ".join(
            str(item.get("content_id", ""))
            for item in target.get(field.key, [])
            if item.get("content_id")
        )
    if field.kind == "linked_outcomes":
        identifiers = target.get(field.key) or [target.get("outcome_id", "")]
        return ", ".join(str(item) for item in identifiers if item)
    return format_editor_value(target.get(field.key), field.kind)


def apply_editor_field_value(
    target: dict[str, Any],
    field: FieldSpec,
    value: Any,
) -> None:
    """Atualiza o modelo preservando relações técnicas não expostas na tabela."""

    if field.kind == "content_ids":
        identifiers = parse_editor_value(value, "csv")
        previous = {
            str(item.get("content_id", "")): str(
                item.get("importance", "Principal")
            )
            for item in target.get(field.key, [])
            if item.get("content_id")
        }
        target[field.key] = [
            {
                "content_id": identifier,
                "importance": previous.get(
                    identifier, "Principal" if index == 0 else "Secundária"
                ),
            }
            for index, identifier in enumerate(identifiers)
        ]
        return
    if field.kind == "linked_outcomes":
        identifiers = parse_editor_value(value, "csv")
        target[field.key] = identifiers
        target["outcome_id"] = identifiers[0] if identifiers else ""
        return
    if field.kind == "alignment_status":
        status = str(value or "").strip()
        target[field.key] = status
        evidence = "Sim" if status.casefold() == "coerente" else "Não"
        target["assessment"] = evidence
        target["teaching_activity"] = evidence
        return
    target[field.key] = parse_editor_value(value, field.kind)


def new_table_row(table: TableSpec) -> dict[str, Any]:
    return deepcopy(table.template)
