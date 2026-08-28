"""Definições dos formulários de edição manual dos artefactos pedagógicos."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .curriculum import (
    TAXONOMY_VERBS,
    next_learning_outcome_id,
    next_structured_activity_id,
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
                    _field("id", "ID", "learning_outcome_id"),
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
                "Tarefas e critérios de avaliação",
                (),
                (
                    _field("id", "ID", "assessment_task_id"),
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
                    _field("teaching_activity", "Atividade de ensino-aprendizagem", "long"),
                    _field("assessment", "Avaliação", "long"),
                ),
                {
                    "outcome_id": "",
                    "focus": "",
                    "teaching_activity": "",
                    "assessment": "",
                },
            ),
        ),
    ),
    "teaching_activities": EditorLayout(
        tables=(
            TableSpec(
                "Atividades de ensino-aprendizagem",
                (),
                (
                    _field("id", "ID", "teaching_activity_id"),
                    _field("outcome_ids", "Resultados", "linked_outcomes"),
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
                    _field(
                        "visual_items",
                        "Elementos do diagrama — 2 a 4, um por linha",
                        "lines",
                    ),
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
                    _field("prompt", "Questões", "long"),
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


def value_at_path(artifact: Any, path: tuple[str | int, ...] | list[str | int]) -> Any:
    value = artifact
    for key in path:
        value = value[key]
    return value


def set_value_at_path(
    artifact: Any,
    path: tuple[str | int, ...] | list[str | int],
    value: Any,
) -> None:
    parent = artifact
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value


def _replace_value_at_path(
    artifact: Any,
    path: list[str | int],
    value: Any,
) -> Any:
    if not path:
        return deepcopy(value)
    result = deepcopy(artifact)
    set_value_at_path(result, path, deepcopy(value))
    return result


def _paired_table_rows(
    before_rows: list[Any],
    after_rows: list[Any],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Alinha linhas estáveis sem permitir que a IA substitua IDs existentes."""

    identity_keys = ("id", "outcome_id", "order", "title", "heading", "criterion")
    pairs: list[tuple[int, int]] = []
    matched_before: set[int] = set()
    matched_after: set[int] = set()

    for identity_key in identity_keys:
        before_index: dict[str, int] = {}
        after_index: dict[str, int] = {}
        duplicate_before: set[str] = set()
        duplicate_after: set[str] = set()
        for index, row in enumerate(before_rows):
            if index in matched_before or not isinstance(row, dict):
                continue
            value = str(row.get(identity_key, "")).strip()
            if not value:
                continue
            if value in before_index:
                duplicate_before.add(value)
            else:
                before_index[value] = index
        for index, row in enumerate(after_rows):
            if index in matched_after or not isinstance(row, dict):
                continue
            value = str(row.get(identity_key, "")).strip()
            if not value:
                continue
            if value in after_index:
                duplicate_after.add(value)
            else:
                after_index[value] = index
        for value in before_index.keys() & after_index.keys():
            if value in duplicate_before or value in duplicate_after:
                continue
            before_position = before_index[value]
            after_position = after_index[value]
            pairs.append((before_position, after_position))
            matched_before.add(before_position)
            matched_after.add(after_position)

    remaining_before = [
        index for index in range(len(before_rows)) if index not in matched_before
    ]
    remaining_after = [
        index for index in range(len(after_rows)) if index not in matched_after
    ]
    substitutions = min(len(remaining_before), len(remaining_after))
    pairs.extend(zip(remaining_before[:substitutions], remaining_after[:substitutions]))
    pairs.sort(key=lambda item: item[0])
    return (
        pairs,
        remaining_before[substitutions:],
        remaining_after[substitutions:],
    )


def proposal_review_changes(
    stage: str,
    artifact: Any,
    scope_path: list[str | int],
    proposed_fragment: Any,
) -> list[dict[str, Any]]:
    """Decompõe uma proposta nos campos e linhas visíveis do editor manual."""

    proposed_artifact = _replace_value_at_path(
        artifact,
        list(scope_path),
        proposed_fragment,
    )
    layout = editor_layout(stage)
    changes: list[dict[str, Any]] = []

    def add_change(kind: str, path: list[str | int], **values: Any) -> None:
        changes.append(
            {
                "key": f"change-{len(changes) + 1}",
                "kind": kind,
                "path": list(path),
                **values,
            }
        )

    for scalar in layout.fields:
        try:
            before = deepcopy(value_at_path(artifact, scalar.path))
            after = deepcopy(value_at_path(proposed_artifact, scalar.path))
        except (KeyError, IndexError, TypeError):
            continue
        if before != after:
            add_change(
                "value",
                list(scalar.path),
                before=before,
                after=after,
                field_key=str(scalar.path[-1]),
                field_label=scalar.label,
                field_kind=scalar.kind,
                table_path=None,
                row_index=None,
            )

    for table in layout.tables:
        try:
            before_rows = value_at_path(artifact, table.path)
            after_rows = value_at_path(proposed_artifact, table.path)
        except (KeyError, IndexError, TypeError):
            continue
        if not isinstance(before_rows, list) or not isinstance(after_rows, list):
            continue

        paired_rows, removed_indexes, added_indexes = _paired_table_rows(
            before_rows,
            after_rows,
        )
        for before_index, after_index in paired_rows:
            before_row = before_rows[before_index]
            after_row = after_rows[after_index]
            if not isinstance(before_row, dict) or not isinstance(after_row, dict):
                continue
            row_identifier = str(
                before_row.get("id")
                or before_row.get("outcome_id")
                or before_index + 1
            )
            for field in table.fields:
                if field.key == "id":
                    continue
                before = deepcopy(before_row.get(field.key))
                after = deepcopy(after_row.get(field.key))
                if before == after:
                    continue
                add_change(
                    "value",
                    [*table.path, before_index, field.key],
                    before=before,
                    after=after,
                    field_key=field.key,
                    field_label=field.label,
                    field_kind=field.kind,
                    table_path=list(table.path),
                    table_title=table.title,
                    row_index=before_index,
                    row_identifier=row_identifier,
                    row_after=deepcopy(after_row),
                )

        for index in added_indexes:
            row = after_rows[index]
            if not isinstance(row, dict):
                continue
            add_change(
                "add_row",
                [*table.path, index],
                before=None,
                after=deepcopy(row),
                table_path=list(table.path),
                table_title=table.title,
                row_index=index,
                fields=[
                    {"key": field.key, "label": field.label, "kind": field.kind}
                    for field in table.fields
                ],
            )

        for index in removed_indexes:
            row = before_rows[index]
            if not isinstance(row, dict):
                continue
            add_change(
                "remove_row",
                [*table.path, index],
                before=deepcopy(row),
                after=None,
                table_path=list(table.path),
                table_title=table.title,
                row_index=index,
                fields=[
                    {"key": field.key, "label": field.label, "kind": field.kind}
                    for field in table.fields
                ],
            )

    return changes


def apply_proposal_review_changes(
    artifact: Any,
    changes: list[dict[str, Any]],
    selections: list[dict[str, Any]],
) -> Any:
    """Aplica apenas as alterações explicitamente aceites pelo docente."""

    selected = {
        str(item.get("key", "")): item
        for item in selections
        if isinstance(item, dict) and str(item.get("key", ""))
    }
    result = deepcopy(artifact)
    accepted = [
        (change, selected.get(str(change["key"]), {}))
        for change in changes
        if selected.get(str(change["key"]), {}).get("accept") is True
    ]
    if not accepted:
        raise ValueError("Aceite pelo menos uma alteração antes de aplicar a proposta.")

    for change, decision in accepted:
        if change["kind"] != "value":
            continue
        set_value_at_path(
            result,
            change["path"],
            deepcopy(decision.get("value", change.get("after"))),
        )

    removals = sorted(
        (
            (change, decision)
            for change, decision in accepted
            if change["kind"] == "remove_row"
        ),
        key=lambda item: (tuple(str(part) for part in item[0]["path"][:-1]), -int(item[0]["path"][-1])),
    )
    for change, _decision in removals:
        rows = value_at_path(result, change["path"][:-1])
        index = int(change["path"][-1])
        if not isinstance(rows, list) or index >= len(rows):
            raise ValueError("Uma linha proposta para remoção já não existe.")
        rows.pop(index)

    additions = sorted(
        (
            (change, decision)
            for change, decision in accepted
            if change["kind"] == "add_row"
        ),
        key=lambda item: (tuple(str(part) for part in item[0]["path"][:-1]), int(item[0]["path"][-1])),
    )
    for change, decision in additions:
        rows = value_at_path(result, change["path"][:-1])
        if not isinstance(rows, list):
            raise ValueError("A tabela proposta já não existe.")
        index = min(int(change["path"][-1]), len(rows))
        rows.insert(
            index,
            deepcopy(decision.get("value", change.get("after"))),
        )

    return result


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


PRESENTATION_INTERNAL_FIELDS = {
    "visual_asset_id",
    "visual_kind",
    "visual_source",
}


def available_presentation_images(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Lista as imagens que o docente pode associar manualmente a um slide."""

    assets: list[dict[str, Any]] = []
    for asset in state.get("source_images", []):
        if not isinstance(asset, dict) or not str(asset.get("id", "")).strip():
            continue
        assets.append(asset)
    for asset in state.get("generated_images", []):
        if not isinstance(asset, dict) or not str(asset.get("id", "")).strip():
            continue
        assets.append(asset)
    return assets


def presentation_image_label(asset: dict[str, Any]) -> str:
    """Cria uma descrição humana da proveniência sem expor o ID técnico."""

    if asset.get("origin_type") == "ai_generated":
        provider = str(asset.get("provider", "IA")).strip() or "IA"
        model = str(asset.get("model", "")).strip()
        return f"Gerada por IA — {provider}" + (f" — {model}" if model else "")
    if asset.get("origin_type") == "user_uploaded":
        source = str(asset.get("source_file", "")).strip() or "Imagem local"
        return f"Carregada pelo docente — {source}"
    source = str(asset.get("source_file", "")).strip() or "Documento de referência"
    location = str(asset.get("source_location", "")).strip()
    return source + (f" — {location}" if location else "")


def apply_presentation_image_choice(
    slide: dict[str, Any],
    asset: dict[str, Any] | None,
) -> None:
    """Associa uma imagem e deriva automaticamente os metadados técnicos."""

    if asset is None:
        slide["visual_mode"] = "diagrama"
        slide["visual_asset_id"] = ""
        slide["visual_prompt"] = ""
        slide["visual_source"] = (
            "Diagrama nativo gerado pelo CoerIA a partir dos artefactos aprovados."
        )
        return

    identifier = str(asset.get("id", "")).strip()
    if not identifier:
        raise ValueError("A imagem selecionada não possui um identificador válido.")
    is_ai = asset.get("origin_type") == "ai_generated" or identifier.startswith("ai-")
    slide["visual_mode"] = "ia" if is_ai else "documento"
    slide["visual_asset_id"] = identifier
    if is_ai:
        provider = str(asset.get("provider", "IA")).strip() or "IA"
        model = str(asset.get("model", "")).strip()
        slide["visual_prompt"] = str(asset.get("prompt", "")).strip()
        slide["visual_source"] = (
            f"Imagem gerada por IA — {provider}" + (f", modelo {model}." if model else ".")
        )
    elif asset.get("origin_type") == "user_uploaded":
        source_file = str(asset.get("source_file", "")).strip() or "imagem local"
        slide["visual_prompt"] = ""
        slide["visual_source"] = f"Imagem fornecida pelo docente — {source_file}."
    else:
        source_file = str(asset.get("source_file", "")).strip() or "documento fornecido"
        source_location = str(asset.get("source_location", "")).strip()
        slide["visual_prompt"] = ""
        slide["visual_source"] = f"Imagem extraída de {source_file}"
        if source_location:
            slide["visual_source"] += f", {source_location}"
        slide["visual_source"] += "."

    asset_alt_text = str(asset.get("alt_text", "")).strip()
    if asset_alt_text:
        slide["alt_text"] = asset_alt_text


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
        for asset in available_presentation_images(state):
            identifier = str(asset.get("id", "")).strip()
            options[identifier] = presentation_image_label(asset)
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


def assistance_scope_options(stage: str, artifact: Any) -> list[dict[str, Any]]:
    """Lista âmbitos estáveis que o docente pode entregar explicitamente à IA."""

    layout = editor_layout(stage)
    options: list[dict[str, Any]] = [
        {"label": "Toda a etapa", "path": []},
    ]
    for scalar in layout.fields:
        options.append({"label": f"Campo: {scalar.label}", "path": list(scalar.path)})
    for table in layout.tables:
        rows = value_at_path(artifact, table.path)
        if table.path:
            options.append(
                {"label": f"Tabela completa: {table.title}", "path": list(table.path)}
            )
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            identifier = ""
            if isinstance(row, dict):
                identifier = str(
                    row.get("id")
                    or row.get("outcome_id")
                    or row.get("title")
                    or row.get("heading")
                    or ""
                ).strip()
            row_label = f"Linha {index + 1}" + (f" ({identifier})" if identifier else "")
            row_path = [*table.path, index]
            options.append(
                {"label": f"{table.title} — {row_label}", "path": row_path}
            )
            if isinstance(row, dict):
                for field in table.fields:
                    if (
                        field.key in row
                        and field.key != "id"
                        and field.key not in PRESENTATION_INTERNAL_FIELDS
                    ):
                        options.append(
                            {
                                "label": f"{row_label} — campo {field.label}",
                                "path": [*row_path, field.key],
                            }
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
    existing_rows: list[Any] | None = None,
) -> dict[str, Any]:
    row = deepcopy(table.template)
    if any(field.kind == "learning_outcome_id" for field in table.fields):
        row["id"] = next_learning_outcome_id(existing_rows or [])
    elif any(field.kind == "teaching_activity_id" for field in table.fields):
        row["id"] = next_structured_activity_id(existing_rows or [], "AE")
    elif any(field.kind == "assessment_task_id" for field in table.fields):
        row["id"] = next_structured_activity_id(existing_rows or [], "TA")
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
