"""Apresentação textual dos artefactos e do histórico do CoerIA."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .curriculum import taxonomy_level_label
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


def _quality_mark(status: str) -> str:
    return {"pass": "✅", "warning": "⚠️", "error": "❌"}.get(status, "•")


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

    quality = artifact.get("quality", {})
    check_rows = []
    for check in quality.get("checks", []):
        if isinstance(check, str):
            check_rows.append(["•", check, ""])
        else:
            check_rows.append([
                _quality_mark(check.get("status", "")),
                check.get("label", ""),
                check.get("detail", ""),
            ])
    visual_section = ""
    if "Apresentação PowerPoint" in selected:
        visual_rows = []
        for index, slide in enumerate(artifact.get("presentation_outline", []), start=1):
            mode = str(slide.get("visual_mode", "diagrama"))
            mode_label = (
                "Imagem documental"
                if mode == "documento"
                else "Imagem gerada por IA"
                if mode == "ia"
                else "Diagrama nativo"
            )
            visual_rows.append([
                index,
                slide.get("title", ""),
                mode_label,
                slide.get("visual_source", ""),
            ])
        if visual_rows:
            visual_section = (
                "\n\n## Elementos visuais da apresentação\n\n"
                + _table(["Slide", "Título", "Modo", "Fonte"], visual_rows)
            )

    return (
        f"**Tipos selecionados:** {', '.join(selected) or 'nenhum'}\n\n"
        + "## Recursos produzidos\n\n"
        + _table(["Recurso", "Quantidade", "Unidade"], resource_rows)
        + visual_section
        + f"\n\n## Validação automática — {quality.get('status', 'Não calculada')}\n\n"
        + _table(["", "Verificação", "Resultado"], check_rows)
    )


def render_artifact(
    state: dict[str, Any],
    stage: str,
    artifact: Any,
    version_number: int,
    metadata: dict[str, Any] | None = None,
    is_current: bool = False,
) -> str:
    """Converte um artefacto estruturado num documento Markdown legível."""

    progress = STAGE_ORDER.index(stage) + 1
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
        f"**Etapa {progress} de {len(STAGE_ORDER)}** · estado: **{review_status}**\n\n"
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
            [item["outcome_id"], item["focus"], item["assessment"]]
            for item in artifact["sequence"]
        ]
        return (
            header
            + f"**Estratégia:** {artifact['strategy']}\n\n"
            + "## Sequência pedagógica\n\n"
            + _table(["Resultado", "Foco", "Avaliação"], sequence_rows)
        )

    if stage == "teaching_activities":
        rows = [
            [
                item.get("id", "—"),
                ", ".join(item.get("outcome_ids", [item.get("outcome_id", "")])),
                ", ".join(item.get("assessment_ids", [])),
                item.get("learning_context", "—"),
                item["activity"],
                item["practice"],
                item["support"],
                item["feedback_strategy"],
            ]
            for item in artifact
        ]
        return header + _table(
            ["ID", "Resultados", "Avaliações", "Contexto", "Atividade", "Prática", "Acompanhamento", "Feedback"],
            rows,
        )

    if stage == "alignment_matrix":
        rows = [
            [
                item["outcome_id"],
                ", ".join(item.get("content_ids", [])),
                taxonomy_level_label(
                    item.get("taxonomy", "SOLO"),
                    item.get("taxonomy_level", "—"),
                ),
                ", ".join(item.get("assessment_ids", [])),
                ", ".join(item.get("assessment_purposes", [])),
                ", ".join(item.get("teaching_activity_ids", [])),
                ", ".join(item.get("resource_types", [])),
                item["status"],
                item.get("rationale", ""),
            ]
            for item in artifact
        ]
        return header + _table(
            [
                "Resultado", "Conteúdos", "Nível",
                "Avaliações", "Finalidade", "Atividades formativas",
                "Recursos", "Alinhamento", "Justificação",
            ],
            rows,
        )

    if stage == "resources":
        return header + _render_resources(artifact)
    if stage == "final_validation":
        rows = [
            [
                "✅" if item.get("passed") else "❌",
                item.get("label", ""),
                item.get("detail", ""),
            ]
            for item in artifact.get("checks", [])
        ]
        return (
            header
            + artifact.get("message", "")
            + "\n\n"
            + _table(["", "Verificação final", "Detalhe"], rows)
        )
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
