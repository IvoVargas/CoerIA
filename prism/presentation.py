"""Apresentação textual dos artefactos e do histórico do CoerIA."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

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
    if metadata.get("validation_attempts", 1) > 1:
        details.append(
            f"{metadata['validation_attempts']} tentativas de validação automática"
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
    return (
        f"**Tipos selecionados:** {', '.join(selected) or 'nenhum'}\n\n"
        + "## Recursos produzidos\n\n"
        + _table(["Recurso", "Quantidade", "Unidade"], resource_rows)
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
            [item["id"], item["title"], item.get("description", "")]
            for item in contents
        ]
        objective_rows = [
            [item.get("id", "—"), item.get("statement", "")]
            for item in artifact.get("objectives", [])
        ]
        assumptions = "\n".join(
            f"- {item}" for item in artifact.get("assumptions", [])
        )
        return (
            header
            + f"{artifact['summary']}\n\n## Objetivos gerais\n\n"
            + _table(["ID", "Objetivo"], objective_rows)
            + "\n\n## Conteúdos identificados\n\n"
            + _table(["ID", "Conteúdo", "Descrição"], content_rows)
            + f"\n\n## Pressupostos\n{assumptions}"
        )

    if stage == "learning_outcomes":
        rows = [
            [
                item["id"],
                item.get("outcome_type", "—"),
                ", ".join(
                    link.get("content_id", "")
                    for link in item.get("content_links", [])
                ),
                ", ".join(item.get("objective_ids", [])),
                item["action_verb"],
                item["statement"],
            ]
            for item in artifact
        ]
        return header + _table(
            ["ID", "Tipo", "Conteúdos", "Objetivos", "Verbo", "Resultado de aprendizagem"],
            rows,
        )

    if stage == "outcome_taxonomy":
        rows = [
            [
                item.get("outcome_id", "—"),
                item["taxonomy"],
                item["level"],
                item["action_verb"],
            ]
            for item in artifact
        ]
        return header + _table(
            ["Resultado", "Taxonomia", "Nível", "Verbo de ação"], rows
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
        sequence = "\n".join(
            f"- **{item['outcome_id']}** — {item['focus']} — avaliação: {item['assessment']}"
            for item in artifact["sequence"]
        )
        return (
            header
            + f"**Estratégia:** {artifact['strategy']}\n\n"
            + f"## Sequência pedagógica\n{sequence}"
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
                ", ".join(item.get("objective_ids", [])),
                ", ".join(item.get("content_ids", [])),
                f"{item.get('taxonomy', '—')} — {item.get('taxonomy_level', '—')}",
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
                "Resultado", "Objetivos", "Conteúdos", "Taxonomia",
                "Avaliações", "Finalidade", "Atividades formativas",
                "Recursos", "Alinhamento", "Justificação",
            ],
            rows,
        )

    if stage == "resources":
        return header + _render_resources(artifact)
    if stage == "final_validation":
        rows = [
            ["✅" if item.get("passed") else "❌", item.get("label", "")]
            for item in artifact.get("checks", [])
        ]
        return (
            header
            + artifact.get("message", "")
            + "\n\n"
            + _table(["", "Verificação final"], rows)
        )
    return header


def render_current_artifact(state: dict[str, Any]) -> str:
    stage = state["current_stage"]
    versions = state.get("versions", {}).get(stage, [])
    metadata = state.get("generation_metadata", {}).get(stage, [])
    return render_artifact(
        state,
        stage,
        state[stage],
        version_number=len(versions) or 1,
        metadata=metadata[-1] if metadata else None,
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
