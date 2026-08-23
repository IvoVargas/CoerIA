"""Definições dos formulários de edição manual dos artefactos pedagógicos."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .curriculum import (
    TAXONOMY_VERBS,
    taxonomy_level_options,
    validate_taxonomy_choice,
)


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
            ScalarSpec(("objectives",), "Objetivos gerais", "long"),
            ScalarSpec(("assumptions",), "Pressupostos — um por linha", "lines"),
        ),
        tables=(
            TableSpec(
                "Conteúdos identificados",
                ("contents",),
                (
                    _field("id", "ID"),
                    _field("outcome_ids", "Resultados", "linked_outcomes"),
                    _field("title", "Conteúdo"),
                    _field("description", "Descrição", "long"),
                ),
                {"id": "", "title": "", "description": "", "outcome_ids": []},
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
                    _field("theme", "Tema ou objeto"),
                    _field("taxonomy_level", "Nível", "taxonomy_level"),
                    _field("action_verb", "Verbo", "taxonomy_verb"),
                    _field("statement", "Resultado de aprendizagem", "long"),
                ),
                {
                    "id": "",
                    "theme": "",
                    "statement": "",
                    "action_verb": "",
                    "taxonomy_level": "",
                    "outcome_type": "Conhecimento",
                },
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
                    _field("content_ids", "Conteúdos", "csv"),
                    _field("taxonomy_level", "Nível", "taxonomy_level"),
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
                    _field("visual_mode", "Modo visual"),
                    _field("visual_asset_id", "Imagem associada"),
                    _field("visual_prompt", "Instrução da imagem IA", "long"),
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
                    "visual_mode": "diagrama",
                    "visual_asset_id": "",
                    "visual_prompt": "",
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
    if kind in {"lines", "csv"} and isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
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


REFERENCE_FIELDS = {
    "content_links": ("curriculum_analysis", "contents", "title"),
    "content_ids": ("curriculum_analysis", "contents", "title"),
    "outcome_id": ("learning_outcomes", None, "statement"),
    "outcome_ids": ("learning_outcomes", None, "statement"),
    "assessment_ids": ("assessment_activities", None, "activity"),
    "teaching_activity_ids": ("teaching_activities", None, "activity"),
}


def editor_reference_options(
    state: dict[str, Any],
    field: FieldSpec,
) -> dict[str, str] | None:
    """Devolve opções controladas para relações e escolhas estruturais."""

    if field.key == "visual_mode":
        return {
            "diagrama": "Diagrama nativo editável",
            "documento": "Imagem extraída de documento",
            "ia": "Imagem gerada por IA",
        }
    if field.key == "visual_asset_id":
        options = {"": "Sem imagem documental"}
        selected_source_ids = {
            str(item).strip()
            for item in state.get("selected_source_image_ids", [])
            if str(item).strip()
        }
        for asset in state.get("source_images", []):
            if not isinstance(asset, dict):
                continue
            identifier = str(asset.get("id", "")).strip()
            if not identifier or identifier not in selected_source_ids:
                continue
            source_file = str(asset.get("source_file", "")).strip()
            location = str(asset.get("source_location", "")).strip()
            filename = str(asset.get("filename", "")).strip()
            description = source_file
            if location:
                description += f" — {location}"
            if filename and filename != source_file:
                description += f" — {filename}"
            options[identifier] = description or identifier
        for asset in state.get("generated_images", []):
            if not isinstance(asset, dict):
                continue
            identifier = str(asset.get("id", "")).strip()
            if not identifier:
                continue
            provider = str(asset.get("provider", "IA")).strip()
            model = str(asset.get("model", "")).strip()
            options[identifier] = (
                f"Gerada por IA — {provider}" + (f" — {model}" if model else "")
            )
        return options

    source = REFERENCE_FIELDS.get(field.key)
    if source is None:
        return None
    stage, nested_key, description_key = source
    artifact = state.get(stage, {})
    rows = artifact.get(nested_key, []) if nested_key else artifact
    if not isinstance(rows, list):
        rows = []
    options: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("id", "")).strip()
        if not identifier:
            continue
        description = " ".join(
            str(row.get(description_key, "")).strip().split()
        )
        if len(description) > 88:
            description = description[:85].rstrip() + "…"
        options[identifier] = (
            f"{identifier} — {description}" if description else identifier
        )
    return options


def editor_taxonomy_level_options(
    state: dict[str, Any],
    field: FieldSpec,
) -> dict[str, str] | None:
    """Limita a escolha aos níveis da taxonomia selecionada para a sessão."""

    if field.kind != "taxonomy_level":
        return None
    taxonomy = validate_taxonomy_choice(
        str(state.get("course", {}).get("taxonomy_type", "SOLO"))
    )
    return taxonomy_level_options(taxonomy)


def editor_taxonomy_verb_options(
    state: dict[str, Any],
    target: dict[str, Any],
    field: FieldSpec,
) -> dict[str, str] | None:
    """Limita o verbo aos valores do nível selecionado na mesma linha."""

    if field.kind != "taxonomy_verb":
        return None
    taxonomy = validate_taxonomy_choice(
        str(state.get("course", {}).get("taxonomy_type", "SOLO"))
    )
    level = str(target.get("taxonomy_level", "")).strip()
    return {
        verb: verb
        for verb in TAXONOMY_VERBS[taxonomy].get(level, ())
    }


def editor_reference_value(target: dict[str, Any], field: FieldSpec) -> Any:
    """Converte a relação interna no valor esperado por um seletor NiceGUI."""

    if field.kind == "content_ids":
        return [
            str(item.get("content_id", ""))
            for item in target.get(field.key, [])
            if item.get("content_id")
        ]
    if field.kind == "linked_outcomes":
        return list(target.get(field.key) or [target.get("outcome_id", "")])
    if field.kind == "csv":
        return list(target.get(field.key) or [])
    if field.kind == "taxonomy_verb":
        return str(target.get(field.key, "") or "").strip() or None
    return str(target.get(field.key, "") or "")


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
    if field.key == "visual_mode":
        mode = str(value or "diagrama").strip() or "diagrama"
        target[field.key] = mode
        if mode not in {"documento", "ia"}:
            target["visual_asset_id"] = ""
            target["visual_prompt"] = ""
        elif mode == "documento":
            target["visual_prompt"] = ""
        return
    if field.key == "visual_asset_id":
        identifier = str(value or "").strip()
        target[field.key] = identifier
        if identifier.startswith("ai-"):
            target["visual_mode"] = "ia"
        else:
            target["visual_mode"] = "documento" if identifier else "diagrama"
        return
    target[field.key] = parse_editor_value(value, field.kind)


def new_table_row(
    table: TableSpec,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = deepcopy(table.template)
    if state is not None and "taxonomy" in row:
        row["taxonomy"] = validate_taxonomy_choice(
            str(state.get("course", {}).get("taxonomy_type", "SOLO"))
        )
    if state is not None and "taxonomy_level" in row and not row["taxonomy_level"]:
        taxonomy = validate_taxonomy_choice(
            str(state.get("course", {}).get("taxonomy_type", "SOLO"))
        )
        row["taxonomy_level"] = next(iter(taxonomy_level_options(taxonomy)))
    return row
