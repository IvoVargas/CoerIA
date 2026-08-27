"""Apresentação textual dos artefactos e do histórico do CoerIA."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .curriculum import taxonomy_level_label
from .models import (
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
)
from .workflow import STAGE_LABELS, STAGE_ORDER


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    divider = ["---"] * len(headers)
    body = "\n".join(
        "| " + " | ".join(str(item).replace("|", "\\|") for item in row) + " |"
        for row in rows
    )
    return (
        "| " + " | ".join(headers) + " |\n"
        + "| " + " | ".join(divider) + " |\n"
        + body
    )


def _validation_icon(item: dict[str, Any]) -> str:
    status = str(item.get("status", ""))
    if status == "warning":
        return "⚠️"
    if status == "error":
        return "❌"
    if status == "pass":
        return "✅"
    return "✅" if item.get("passed") else "❌"


def _metadata_text(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return ""
    details = [
        f"Gerado por {metadata.get('provider', 'agente')}",
        f"modelo {metadata.get('model', 'não registado')}",
    ]
    if metadata.get("duration_ms") is not None:
        details.append(f"{metadata.get('duration_ms', 0)} ms")
    if metadata.get("total_tokens"):
        details.append(f"{metadata['total_tokens']} tokens")
    resource_generations = metadata.get("resource_generations", [])
    if resource_generations:
        details.append(
            f"{len(resource_generations)} recursos gerados separadamente"
        )
    elif metadata.get("validation_attempts", 1) > 1:
        details.append(
            f"{metadata['validation_attempts']} tentativas de validação automática"
        )
    guardrail_corrections = metadata.get("guardrail_corrections", [])
    if guardrail_corrections:
        details.append(
            f"{len(guardrail_corrections)} correções automáticas de guardrail"
        )
    agentic = metadata.get("agentic", {})
    if agentic.get("enabled"):
        result = (
            "crítica pedagógica aprovada"
            if agentic.get("critic_passed") is True
            else "crítica pedagógica com observações"
            if agentic.get("critic_passed") is False
            else "crítica pedagógica indisponível"
        )
        details.append(result)
        if agentic.get("automatic_revisions"):
            details.append(f"{agentic['automatic_revisions']} revisão agentic")
    return "_" + " · ".join(details) + "._\n\n"


def _render_resources(artifact: dict[str, Any]) -> str:
    selected = artifact.get("selected_types", [])
    resource_rows: list[list[Any]] = []
    if "Apresentação PowerPoint" in selected:
        resource_rows.append([
            "Apresentação PowerPoint",
            len(artifact.get("presentation_outline", [])),
            "slides",
        ])
    if "Ficha de aula" in selected:
        resource_rows.append([
            "Ficha de aula",
            len(artifact.get("lesson_worksheet", {}).get("sections", [])),
            "secções",
        ])
    if "Teste" in selected:
        resource_rows.append([
            "Teste",
            len(artifact.get("test", {}).get("questions", [])),
            "questões",
        ])
    if "Atividade prática" in selected:
        resource_rows.append([
            "Atividade prática",
            len(artifact.get("practical_activity", {}).get("steps", [])),
            "etapas",
        ])

    return (
        f"**Tipos selecionados:** {', '.join(selected) or 'nenhum'}\n\n"
        + "## Recursos produzidos\n\n"
        + _table(["Recurso", "Quantidade", "Unidade"], resource_rows)
    )


def render_resource_detail_sections(
    artifact: dict[str, Any],
) -> list[dict[str, str]]:
    """Devolve o conteúdo integral de cada recurso selecionado para a UI."""

    selected = set(artifact.get("selected_types", []))
    sections: list[dict[str, str]] = []

    if RESOURCE_PRESENTATION in selected:
        rows = []
        for index, slide in enumerate(artifact.get("presentation_outline", []), start=1):
            mode = str(slide.get("visual_mode", "diagrama"))
            mode_label = (
                "Imagem documental"
                if mode == "documento"
                else "Imagem gerada por IA"
                if mode == "ia"
                else "Diagrama nativo"
            )
            rows.append(
                [
                    index,
                    slide.get("title", ""),
                    slide.get("outcome_id", "—"),
                    " · ".join(str(item) for item in slide.get("bullets", [])),
                    mode_label,
                    slide.get("visual_title", ""),
                    slide.get("alt_text", ""),
                ]
            )
        sections.append(
            {
                "id": "presentation",
                "label": "Apresentação",
                "icon": "slideshow",
                "content": (
                    f"**{len(rows)} slides**\n\n"
                    + _table(
                        [
                            "Slide",
                            "Título",
                            "Resultado",
                            "Conteúdo",
                            "Modo visual",
                            "Elemento visual",
                            "Texto alternativo",
                        ],
                        rows,
                    )
                ),
            }
        )

    if RESOURCE_WORKSHEET in selected:
        worksheet = artifact.get("lesson_worksheet", {})
        rows = [
            [
                index,
                item.get("heading", ""),
                ", ".join(str(value) for value in item.get("outcome_ids", [])),
                item.get("content", ""),
                item.get("activity", ""),
            ]
            for index, item in enumerate(worksheet.get("sections", []), start=1)
        ]
        sections.append(
            {
                "id": "worksheet",
                "label": "Ficha de aula",
                "icon": "description",
                "content": (
                    f"## {worksheet.get('title') or 'Ficha de aula'}\n\n"
                    f"**Enquadramento:** {worksheet.get('overview') or '—'}\n\n"
                    f"**Instruções:** {worksheet.get('instructions') or '—'}\n\n"
                    + _table(
                        ["Secção", "Título", "Resultados", "Conteúdo", "Atividade"],
                        rows,
                    )
                ),
            }
        )

    if RESOURCE_TEST in selected:
        test = artifact.get("test", {})
        rows = [
            [
                item.get("id", index),
                item.get("outcome_id", "—"),
                item.get("question_type", ""),
                item.get("points", 0),
                item.get("prompt", ""),
                item.get("answer_key", ""),
            ]
            for index, item in enumerate(test.get("questions", []), start=1)
        ]
        sections.append(
            {
                "id": "test",
                "label": "Teste",
                "icon": "quiz",
                "content": (
                    f"## {test.get('title') or 'Teste'}\n\n"
                    f"**Instruções:** {test.get('instructions') or '—'}\n\n"
                    f"**Cotação total:** {test.get('total_points', 0)} pontos\n\n"
                    + _table(
                        [
                            "ID",
                            "Resultado",
                            "Tipo",
                            "Pontos",
                            "Enunciado",
                            "Chave de correção",
                        ],
                        rows,
                    )
                ),
            }
        )

    if RESOURCE_PRACTICAL in selected:
        practical = artifact.get("practical_activity", {})
        step_rows = [
            [
                item.get("order", index),
                ", ".join(str(value) for value in item.get("outcome_ids", [])),
                item.get("instruction", ""),
            ]
            for index, item in enumerate(practical.get("steps", []), start=1)
        ]
        criterion_rows = [
            [
                item.get("criterion", ""),
                item.get("description", ""),
                f"{item.get('weight', 0)}%",
            ]
            for item in practical.get("criteria", [])
        ]
        materials = " · ".join(
            str(item) for item in practical.get("materials", [])
        ) or "—"
        deliverables = " · ".join(
            str(item) for item in practical.get("deliverables", [])
        ) or "—"
        sections.append(
            {
                "id": "practical",
                "label": "Atividade prática",
                "icon": "construction",
                "content": (
                    f"## {practical.get('title') or 'Atividade prática'}\n\n"
                    f"**Contexto:** {practical.get('context') or '—'}\n\n"
                    f"**Duração:** {practical.get('duration_minutes', 0)} minutos\n\n"
                    f"**Materiais:** {materials}\n\n"
                    f"**Entregáveis:** {deliverables}\n\n"
                    "### Etapas\n\n"
                    + _table(["Ordem", "Resultados", "Instrução"], step_rows)
                    + "\n\n### Critérios\n\n"
                    + _table(["Critério", "Descrição", "Peso"], criterion_rows)
                ),
            }
        )

    return sections


def render_artifact(
    state: dict[str, Any],
    stage: str,
    artifact: Any,
    version_number: int,
    metadata: dict[str, Any] | None = None,
    is_current: bool = False,
) -> str:
    """Converte um artefacto estruturado num documento Markdown legível."""

    progress = STAGE_ORDER.index(stage) + 2
    if is_current:
        stage_status = state.get("stage_statuses", {}).get(stage)
        review_status = (
            "versão ativa aprovada"
            if stage_status == "approved" or state.get("status") == "completed"
            else "a aguardar validação do docente"
            if stage_status == "awaiting_review" or stage == state.get("current_stage")
            else "versão ativa"
        )
    else:
        review_status = "versão guardada para consulta"
    header = (
        f"# {STAGE_LABELS[stage]} — versão {version_number}\n\n"
        f"**Etapa {progress} de {len(STAGE_ORDER) + 1}** · estado: **{review_status}**\n\n"
        + _metadata_text(metadata)
    )

    if stage == "curriculum_analysis":
        contents = artifact.get("contents") or [
            {"id": f"C{index + 1}", "title": theme, "description": theme}
            for index, theme in enumerate(artifact["themes"])
        ]
        content_rows = [
            [
                item["id"],
                ", ".join(item.get("outcome_ids", [])),
                item["title"],
                item.get("description", ""),
            ]
            for item in contents
        ]
        objectives = str(artifact.get("objectives", "")).strip()
        assumptions = "\n".join(
            f"- {item}" for item in artifact.get("assumptions", [])
        )
        source_rows = [
            [
                item.get("source", "—"),
                item.get("contribution", ""),
                ", ".join(str(value) for value in item.get("key_concepts", [])),
                ", ".join(str(value) for value in item.get("content_ids", [])),
            ]
            for item in artifact.get("source_coverage", [])
            if isinstance(item, dict)
        ]
        source_section = (
            "\n\n## Cobertura das fontes documentais\n\n"
            + _table(
                ["Fonte", "Contributo curricular", "Conceitos-chave", "Conteúdos"],
                source_rows,
            )
            if source_rows
            else ""
        )
        return (
            header
            + f"{artifact['summary']}\n\n## Objetivos gerais\n\n"
            + (objectives or "A confirmar pelo docente.")
            + "\n\n## Conteúdos identificados\n\n"
            + _table(["ID", "Resultados", "Conteúdo", "Descrição"], content_rows)
            + source_section
            + f"\n\n## Pressupostos\n{assumptions}"
        )

    if stage == "learning_outcomes":
        rows = [
            [
                item["id"],
                item.get("outcome_type", "—"),
                item.get("theme", "—"),
                taxonomy_level_label(
                    state.get("course", {}).get("taxonomy_type", "SOLO"),
                    item.get("taxonomy_level", "—"),
                ),
                item["action_verb"],
                item["statement"],
            ]
            for item in artifact
        ]
        return header + _table(
            [
                "ID", "Tipo", "Tema ou objeto", "Nível", "Verbo",
                "Resultado de aprendizagem",
            ],
            rows,
        )

    if stage == "assessment_activities":
        rows = [
            [
                item.get("id", "—"),
                ", ".join(item.get("outcome_ids", [item.get("outcome_id", "")])),
                item.get("work_type", "—"),
                item.get("assessment_purpose", "—"),
                item["activity"],
                item["evidence"],
                item["criterion"],
            ]
            for item in artifact
        ]
        return header + _table(
            ["ID", "Resultados", "Modalidade", "Finalidade", "Atividade", "Evidência", "Critério"],
            rows,
        )

    if stage == "pedagogical_design":
        sequence_rows = [
            [
                item["outcome_id"],
                item["focus"],
                item.get("teaching_activity", "—"),
                item["assessment"],
            ]
            for item in artifact["sequence"]
        ]
        return (
            header
            + f"**Estratégia:** {artifact['strategy']}\n\n"
            + "## Sequência pedagógica\n\n"
            + _table(
                ["Resultado", "Foco", "Atividade de ensino-aprendizagem", "Avaliação"],
                sequence_rows,
            )
        )

    if stage == "teaching_activities":
        rows = [
            [
                item.get("id", "—"),
                ", ".join(item.get("outcome_ids", [item.get("outcome_id", "")])),
                item.get("learning_context", "—"),
                item["activity"],
                item["practice"],
                item["support"],
                item["feedback_strategy"],
            ]
            for item in artifact
        ]
        return header + _table(
            ["ID", "Resultados", "Contexto", "Atividade", "Prática", "Acompanhamento", "Feedback"],
            rows,
        )

    if stage == "resources":
        return header + _render_resources(artifact)
    if stage == "final_validation":
        rows = [
            [
                _validation_icon(item),
                item.get("label", ""),
                item.get("detail", ""),
            ]
            for item in artifact.get("checks", [])
        ]
        result = (
            header
            + artifact.get("message", "")
            + "\n\n"
            + _table(["", "Verificação final", "Detalhe"], rows)
        )
        resource_rows = [
            [
                _validation_icon(item),
                item.get("label", ""),
                item.get("detail", ""),
            ]
            for item in artifact.get("resource_quality_checks", [])
        ]
        if resource_rows:
            result += (
                "\n\n## Qualidade automática dos recursos\n\n"
                + _table(["", "Controlo", "Detalhe"], resource_rows)
            )
        return result
    return header


def render_current_artifact(state: dict[str, Any]) -> str:
    stage = state["current_stage"]
    versions = state.get("versions", {}).get(stage, [])
    metadata = state.get("generation_metadata", {}).get(stage, [])
    version_number = int(
        state.get("active_versions", {}).get(stage) or len(versions) or 1
    )
    return render_artifact(
        state,
        stage,
        state[stage],
        version_number=version_number,
        metadata=(
            metadata[version_number - 1]
            if 0 < version_number <= len(metadata)
            else None
        ),
        is_current=True,
    )


def active_stage_artifact(state: dict[str, Any], stage: str) -> Any:
    """Devolve uma cópia da versão ativa de uma etapa."""

    if stage not in STAGE_ORDER:
        raise ValueError("A etapa selecionada já não está disponível.")
    versions = state.get("versions", {}).get(stage, [])
    active_version = state.get("active_versions", {}).get(stage)
    version_number = int(active_version or len(versions) or 1)
    if 0 < version_number <= len(versions):
        return deepcopy(versions[version_number - 1])
    if stage in state:
        return deepcopy(state[stage])
    raise ValueError("A etapa selecionada ainda não possui uma versão ativa.")


def render_stage_artifact(state: dict[str, Any], stage: str) -> str:
    """Apresenta a versão ativa de uma etapa sem alterar o fluxo da sessão."""

    try:
        artifact = active_stage_artifact(state, stage)
    except ValueError as error:
        return str(error)
    versions = state.get("versions", {}).get(stage, [])
    active_version = state.get("active_versions", {}).get(stage)
    version_number = int(active_version or len(versions) or 1)
    metadata_versions = state.get("generation_metadata", {}).get(stage, [])
    return render_artifact(
        state,
        stage,
        artifact,
        version_number=version_number,
        metadata=(
            metadata_versions[version_number - 1]
            if version_number <= len(metadata_versions)
            else None
        ),
        is_current=True,
    )


def current_history_value(state: dict[str, Any]) -> str | None:
    stage = state.get("current_stage")
    versions = state.get("versions", {}).get(stage, [])
    active_version = state.get("active_versions", {}).get(stage)
    if stage and versions:
        index = int(active_version or len(versions)) - 1
        return f"{stage}::{index}"
    return None


def history_choices(state: dict[str, Any]) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    versions = state.get("versions", {})
    active_versions = state.get("active_versions", {})
    stage_statuses = state.get("stage_statuses", {})
    for stage in STAGE_ORDER:
        for index, _artifact in enumerate(versions.get(stage, [])):
            value = f"{stage}::{index}"
            is_active = active_versions.get(stage) == index + 1
            is_latest_stale = (
                stage_statuses.get(stage) == "stale"
                and index == len(versions.get(stage, [])) - 1
            )
            suffix = (
                " (ativa)"
                if is_active
                else " (desatualizada)"
                if is_latest_stale
                else ""
            )
            choices.append(
                (f"{STAGE_LABELS[stage]} — versão {index + 1}{suffix}", value)
            )
    return choices


def render_history_artifact(
    selected_version: str | None,
    state: dict[str, Any] | None,
) -> str:
    if not state or not selected_version:
        return "Ainda não existem etapas geradas para consulta."
    try:
        stage, index_text = selected_version.rsplit("::", maxsplit=1)
        index = int(index_text)
        artifact = state["versions"][stage][index]
    except (KeyError, ValueError, IndexError):
        return "A versão selecionada já não está disponível."

    stage_versions = state["versions"][stage]
    metadata_versions = state.get("generation_metadata", {}).get(stage, [])
    is_current = state.get("active_versions", {}).get(stage) == index + 1
    return render_artifact(
        state,
        stage,
        artifact,
        version_number=index + 1,
        metadata=metadata_versions[index] if index < len(metadata_versions) else None,
        is_current=is_current,
    )


def audit_rows(state: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "timestamp": str(item.get("timestamp", "")),
            "stage": str(item.get("stage", "")),
            "event": str(item.get("event", "")),
            "feedback": str(item.get("feedback", "")),
        }
        for item in state.get("audit", [])
    ]
