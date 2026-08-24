"""Persistência local do estado partilhado e do histórico de decisões."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .auth import normalize_user_id
from .curriculum import (
    TAXONOMY_LEVELS,
    normalize_structured_activity_ids,
    taxonomy_level_for_verb,
    validate_taxonomy_choice,
)
from .providers import AI_PROVIDER_OPENAI, validate_ai_provider
from .relationships import content_ids_for_outcome


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "prism.db"


def migrate_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta os campos estruturais novos sem apagar artefactos históricos."""

    previous_version = int(state.get("schema_version", 1) or 1)
    if previous_version < 19:
        state.setdefault("migrated_from_schema_version", previous_version)
    state["schema_version"] = 19
    state["ai_provider"] = validate_ai_provider(
        state.get("ai_provider", AI_PROVIDER_OPENAI)
    )
    state.setdefault(
        "orchestration",
        {"mode": "bounded-generator-critic", "human_approval_required": True},
    )
    state.setdefault("source_images", [])
    state.setdefault("selected_source_image_ids", [])
    state.setdefault("source_reduction", {})
    state.setdefault(
        "source_original_text",
        str(state.get("course", {}).get("source_text", "") or ""),
    )
    state.setdefault("generated_images", [])
    state.setdefault("ai_image_generation_enabled", False)

    def migrate_presentation_visuals(resources: Any) -> None:
        if not isinstance(resources, dict):
            return
        slides = resources.get("presentation_outline", [])
        if not isinstance(slides, list):
            return
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            slide.setdefault("visual_mode", "diagrama")
            slide.setdefault("visual_asset_id", "")
            slide.setdefault("visual_prompt", "")
            slide.setdefault("visual_warning", "")

    migrate_presentation_visuals(state.get("resources"))
    version_map = state.get("versions", {})
    if isinstance(version_map, dict):
        for resource_version in version_map.get("resources", []):
            migrate_presentation_visuals(resource_version)
    for snapshot in state.get("revision_snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        artifacts = snapshot.get("artifacts", {})
        if isinstance(artifacts, dict):
            migrate_presentation_visuals(artifacts.get("resources"))

    course = state.setdefault("course", {})
    for key, default in {
        "program_name": "",
        "program_type": "",
        "academic_year": "",
        "semester": "1.º semestre",
        "cnaef_code": "",
        "cnaef_name": "",
        "ects_credits": 0.0,
        "contact_hours": 0.0,
        "autonomous_hours": 0.0,
        "general_aims": "",
        "bibliography": "",
        "taxonomy_type": "SOLO",
    }.items():
        course.setdefault(key, default)
    if not str(course.get("semester", "") or "").strip():
        course["semester"] = "1.º semestre"

    selected_taxonomy = validate_taxonomy_choice(course.get("taxonomy_type", "SOLO"))
    current_classifications = {
        str(item.get("outcome_id", "")): item
        for item in state.get("outcome_taxonomy", [])
        if isinstance(item, dict)
    }

    def migrate_outcome_levels(
        outcomes: Any,
        classifications: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(outcomes, list):
            return
        taxonomy_rows = (
            current_classifications if classifications is None else classifications
        )
        for item in outcomes:
            if not isinstance(item, dict):
                continue
            existing_level = str(item.get("taxonomy_level", "")).strip()
            classification = taxonomy_rows.get(str(item.get("id", "")), {})
            classified_level = str(classification.get("level", "")).strip()
            classified_taxonomy = str(classification.get("taxonomy", "")).strip()
            if existing_level in TAXONOMY_LEVELS[selected_taxonomy]:
                level = existing_level
            elif (
                classified_taxonomy == selected_taxonomy
                and classified_level in TAXONOMY_LEVELS[selected_taxonomy]
            ):
                level = classified_level
            else:
                level = (
                    taxonomy_level_for_verb(
                        selected_taxonomy, str(item.get("action_verb", ""))
                    )
                    or TAXONOMY_LEVELS[selected_taxonomy][0]
                )
            item["taxonomy_level"] = level

    migrate_outcome_levels(state.get("learning_outcomes"))
    if isinstance(version_map, dict):
        classification_versions = version_map.get("outcome_taxonomy", [])
        for index, outcome_version in enumerate(
            version_map.get("learning_outcomes", [])
        ):
            version_classifications = (
                classification_versions[index]
                if index < len(classification_versions)
                and isinstance(classification_versions[index], list)
                else []
            )
            migrate_outcome_levels(
                outcome_version,
                {
                    str(item.get("outcome_id", "")): item
                    for item in version_classifications
                    if isinstance(item, dict)
                },
            )
    for snapshot in state.get("revision_snapshots", []):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("artifacts"), dict):
            continue
        artifacts = snapshot["artifacts"]
        snapshot_classifications = {
            str(item.get("outcome_id", "")): item
            for item in artifacts.get("outcome_taxonomy", [])
            if isinstance(item, dict)
        }
        migrate_outcome_levels(
            artifacts.get("learning_outcomes"),
            snapshot_classifications,
        )

    analysis = state.get("curriculum_analysis")

    def migrate_curriculum_objectives(curriculum: Any) -> None:
        if not isinstance(curriculum, dict):
            return
        value = curriculum.get("objectives", "")
        if isinstance(value, list):
            statements = [
                str(item.get("statement", "")).strip()
                for item in value
                if isinstance(item, dict) and str(item.get("statement", "")).strip()
            ]
            text = "\n".join(statements)
        elif isinstance(value, dict):
            text = str(value.get("statement", "")).strip()
        else:
            text = str(value or "").strip()
        curriculum["objectives"] = text or str(
            curriculum.get("aims")
            or course.get("general_aims")
            or "Desenvolver os conhecimentos e competências previstos."
        ).strip()

    migrate_curriculum_objectives(analysis)
    if isinstance(version_map, dict):
        for curriculum_version in version_map.get("curriculum_analysis", []):
            migrate_curriculum_objectives(curriculum_version)
    for snapshot in state.get("revision_snapshots", []):
        if isinstance(snapshot, dict):
            migrate_curriculum_objectives(
                snapshot.get("artifacts", {}).get("curriculum_analysis")
                if isinstance(snapshot.get("artifacts"), dict)
                else None
            )

    if isinstance(analysis, dict):
        analysis.setdefault(
            "contents",
            [
                {"id": f"C{index + 1}", "title": theme, "description": theme}
                for index, theme in enumerate(analysis.get("themes", []))
            ],
        )
        content_by_theme = {
            str(item.get("title", "")).casefold(): item.get("id", "")
            for item in analysis.get("contents", [])
        }
    else:
        content_by_theme = {}

    for index, item in enumerate(state.get("solo_taxonomy", [])):
        item.setdefault(
            "content_id",
            content_by_theme.get(str(item.get("theme", "")).casefold(), f"C{index + 1}"),
        )

    for index, item in enumerate(state.get("learning_outcomes", [])):
        item.setdefault(
            "outcome_type",
            ("Conhecimento teórico", "Aptidão prática ou técnica", "Competência social")[index % 3],
        )
        if previous_version < 12:
            item.setdefault(
                "content_links",
                [{
                    "content_id": content_by_theme.get(
                        str(item.get("theme", "")).casefold(), f"C{index + 1}"
                    ),
                    "importance": "Principal",
                }],
            )

    def migrate_curriculum_relations(curriculum: Any) -> None:
        if not isinstance(curriculum, dict):
            return
        outcomes = [
            item
            for item in state.get("learning_outcomes", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        for index, content in enumerate(curriculum.get("contents", [])):
            if not isinstance(content, dict):
                continue
            content_id = str(content.get("id", ""))
            linked = [
                str(outcome["id"])
                for outcome in outcomes
                if content_id in {
                    str(link.get("content_id", ""))
                    for link in outcome.get("content_links", [])
                    if isinstance(link, dict)
                }
            ]
            if not linked and outcomes:
                linked = [str(outcomes[index % len(outcomes)]["id"])]
            content.setdefault("outcome_ids", linked)
    migrate_curriculum_relations(analysis)
    if isinstance(version_map, dict):
        for curriculum_version in version_map.get("curriculum_analysis", []):
            migrate_curriculum_relations(curriculum_version)
    for snapshot in state.get("revision_snapshots", []):
        if isinstance(snapshot, dict):
            migrate_curriculum_relations(
                snapshot.get("artifacts", {}).get("curriculum_analysis")
                if isinstance(snapshot.get("artifacts"), dict)
                else None
            )

    def migrate_assessment_rows(activities: Any) -> None:
        if not isinstance(activities, list):
            return
        for index, item in enumerate(activities):
            if not isinstance(item, dict):
                continue
            item.setdefault("id", f"AT{index + 1}")
            item.setdefault("outcome_ids", [item.get("outcome_id", "")])
            item.setdefault("work_type", "Não especificado")
            item.setdefault("assessment_purpose", "Sumativa")

    migrate_assessment_rows(state.get("assessment_activities"))
    if isinstance(version_map, dict):
        for assessment_version in version_map.get("assessment_activities", []):
            migrate_assessment_rows(assessment_version)
    for snapshot in state.get("revision_snapshots", []):
        if isinstance(snapshot, dict) and isinstance(snapshot.get("artifacts"), dict):
            migrate_assessment_rows(snapshot["artifacts"].get("assessment_activities"))

    def migrate_teaching_rows(activities: Any) -> None:
        if not isinstance(activities, list):
            return
        for index, item in enumerate(activities):
            if not isinstance(item, dict):
                continue
            item.setdefault("outcome_ids", [item.get("outcome_id", "")])
            item.setdefault("id", f"TLA{index + 1}")
            # As atividades alinham-se diretamente com os resultados. A ligação
            # a avaliações era redundante e impedia que esta etapa as precedesse.
            item.pop("assessment_ids", None)
            item.setdefault("learning_context", "Não especificado")
            item.setdefault("practice", item.get("activity", "Prática orientada."))
            item.setdefault("support", "Acompanhamento do docente.")
            item.setdefault("feedback_strategy", "Feedback formativo.")

    migrate_teaching_rows(state.get("teaching_activities"))
    if isinstance(version_map, dict):
        for teaching_version in version_map.get("teaching_activities", []):
            migrate_teaching_rows(teaching_version)
    for snapshot in state.get("revision_snapshots", []):
        if isinstance(snapshot, dict) and isinstance(snapshot.get("artifacts"), dict):
            migrate_teaching_rows(snapshot["artifacts"].get("teaching_activities"))

    def canonicalize_activity_ids(rows: Any, prefix: str) -> dict[str, str]:
        if not isinstance(rows, list):
            return {}
        before = [
            str(item.get("id", "")) if isinstance(item, dict) else ""
            for item in rows
        ]
        if previous_version < 19:
            normalized = normalize_structured_activity_ids(
                rows,
                prefix=prefix,
                sequential=True,
            )
            rows[:] = normalized
        after = [
            str(item.get("id", "")) if isinstance(item, dict) else ""
            for item in rows
        ]
        return {
            old: new
            for old, new in zip(before, after)
            if old and new
        }

    assessment_id_map = canonicalize_activity_ids(
        state.get("assessment_activities"),
        "AT",
    )
    teaching_id_map = canonicalize_activity_ids(
        state.get("teaching_activities"),
        "TLA",
    )
    assessment_version_maps = [
        canonicalize_activity_ids(version, "AT")
        for version in version_map.get("assessment_activities", [])
    ] if isinstance(version_map, dict) else []
    teaching_version_maps = [
        canonicalize_activity_ids(version, "TLA")
        for version in version_map.get("teaching_activities", [])
    ] if isinstance(version_map, dict) else []

    def remap_alignment_activity_ids(
        matrix: Any,
        assessment_mapping: dict[str, str],
        teaching_mapping: dict[str, str],
    ) -> None:
        rows = [matrix] if isinstance(matrix, dict) else matrix
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get("assessment_ids"), list):
                row["assessment_ids"] = [
                    assessment_mapping.get(str(identifier), str(identifier))
                    for identifier in row["assessment_ids"]
                ]
            if isinstance(row.get("teaching_activity_ids"), list):
                row["teaching_activity_ids"] = [
                    teaching_mapping.get(str(identifier), str(identifier))
                    for identifier in row["teaching_activity_ids"]
                ]

    remap_alignment_activity_ids(
        state.get("alignment_matrix"),
        assessment_id_map,
        teaching_id_map,
    )
    alignment_versions = (
        version_map.get("alignment_matrix", [])
        if isinstance(version_map, dict)
        else []
    )
    alignment_dependencies = state.get("version_dependencies", {}).get(
        "alignment_matrix", []
    )
    for index, matrix_version in enumerate(alignment_versions):
        dependencies = (
            alignment_dependencies[index]
            if index < len(alignment_dependencies)
            and isinstance(alignment_dependencies[index], dict)
            else {}
        )
        assessment_version = int(dependencies.get("assessment_activities", 0) or 0)
        teaching_version = int(dependencies.get("teaching_activities", 0) or 0)
        version_assessment_map = (
            assessment_version_maps[assessment_version - 1]
            if 0 < assessment_version <= len(assessment_version_maps)
            else assessment_id_map
        )
        version_teaching_map = (
            teaching_version_maps[teaching_version - 1]
            if 0 < teaching_version <= len(teaching_version_maps)
            else teaching_id_map
        )
        remap_alignment_activity_ids(
            matrix_version,
            version_assessment_map,
            version_teaching_map,
        )
    for snapshot in state.get("revision_snapshots", []):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("artifacts"), dict):
            continue
        artifacts = snapshot["artifacts"]
        snapshot_assessment_map = canonicalize_activity_ids(
            artifacts.get("assessment_activities"),
            "AT",
        )
        snapshot_teaching_map = canonicalize_activity_ids(
            artifacts.get("teaching_activities"),
            "TLA",
        )
        remap_alignment_activity_ids(
            artifacts.get("alignment_matrix"),
            snapshot_assessment_map,
            snapshot_teaching_map,
        )

    def remap_own_activity_ids(value: Any, mapping: dict[str, str]) -> None:
        if isinstance(value, list):
            for item in value:
                remap_own_activity_ids(item, mapping)
            return
        if not isinstance(value, dict):
            return
        identifier = str(value.get("id", ""))
        if identifier in mapping:
            value["id"] = mapping[identifier]
        for item in value.values():
            remap_own_activity_ids(item, mapping)

    if previous_version < 19:
        for proposal in state.get("ai_proposals", []):
            if not isinstance(proposal, dict):
                continue
            proposal_stage = str(proposal.get("stage", ""))
            if proposal_stage == "assessment_activities":
                remap_own_activity_ids(proposal.get("before"), assessment_id_map)
                remap_own_activity_ids(proposal.get("after"), assessment_id_map)
            elif proposal_stage == "teaching_activities":
                remap_own_activity_ids(proposal.get("before"), teaching_id_map)
                remap_own_activity_ids(proposal.get("after"), teaching_id_map)
            elif proposal_stage == "alignment_matrix":
                remap_alignment_activity_ids(
                    proposal.get("before"),
                    assessment_id_map,
                    teaching_id_map,
                )
                remap_alignment_activity_ids(
                    proposal.get("after"),
                    assessment_id_map,
                    teaching_id_map,
                )

    assessments = state.get("assessment_activities", [])

    def migrate_pedagogical_sequence(
        design: Any,
        teaching_activities: Any,
    ) -> None:
        if not isinstance(design, dict) or not isinstance(design.get("sequence"), list):
            return
        activities = teaching_activities if isinstance(teaching_activities, list) else []
        for item in design["sequence"]:
            if not isinstance(item, dict):
                continue
            outcome_id = str(item.get("outcome_id", ""))
            linked = [
                str(activity.get("activity", "")).strip()
                for activity in activities
                if isinstance(activity, dict)
                and outcome_id in (
                    activity.get("outcome_ids") or [activity.get("outcome_id")]
                )
                and str(activity.get("activity", "")).strip()
            ]
            item.setdefault(
                "teaching_activity",
                "; ".join(linked) or "A confirmar pelo docente.",
            )

    migrate_pedagogical_sequence(
        state.get("pedagogical_design"),
        state.get("teaching_activities"),
    )
    if isinstance(version_map, dict):
        for design_version in version_map.get("pedagogical_design", []):
            migrate_pedagogical_sequence(
                design_version,
                state.get("teaching_activities"),
            )
    for snapshot in state.get("revision_snapshots", []):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("artifacts"), dict):
            continue
        artifacts = snapshot["artifacts"]
        migrate_pedagogical_sequence(
            artifacts.get("pedagogical_design"),
            artifacts.get("teaching_activities"),
        )

    outcome_by_id = {
        str(item.get("id", "")): item
        for item in state.get("learning_outcomes", [])
    }
    for row in state.get("alignment_matrix", []):
        outcome_id = str(row.get("outcome_id", ""))
        row.pop("objective_ids", None)
        row.setdefault(
            "content_ids",
            content_ids_for_outcome(state, outcome_id),
        )
        row.setdefault(
            "assessment_ids",
            [
                item.get("id", "") for item in assessments
                if outcome_id in item.get("outcome_ids", [])
            ],
        )
        row.setdefault(
            "assessment_purposes",
            sorted(
                {
                    item.get("assessment_purpose", "Sumativa")
                    for item in assessments
                    if outcome_id in item.get("outcome_ids", [])
                }
            ),
        )
        row.setdefault(
            "taxonomy",
            selected_taxonomy,
        )
        row.setdefault(
            "taxonomy_level",
            outcome_by_id.get(outcome_id, {}).get(
                "taxonomy_level", TAXONOMY_LEVELS[selected_taxonomy][0]
            ),
        )
        row.setdefault(
            "teaching_activity_ids",
            [
                item.get("id", "") for item in state.get("teaching_activities", [])
                if outcome_id in item.get("outcome_ids", [])
            ],
        )
        row.setdefault("resource_types", list(state.get("resource_types", [])))

    if state.get("current_stage") == "solo_taxonomy":
        state["current_stage"] = "learning_outcomes"
    versions = state.setdefault("versions", {})
    from .workflow import (
        MANUAL_FIRST_MODE,
        STAGE_LABELS,
        STAGE_ORDER,
        artifact_has_content,
        ensure_manual_artifacts,
        formulate_learning_outcomes,
    )

    removed_stage_was_current = (
        previous_version < 14 and state.get("current_stage") == "outcome_taxonomy"
    )
    if removed_stage_was_current:
        state["current_stage"] = "learning_outcomes"
        state["status"] = "awaiting_review"
        state["review"] = {
            "stage": "learning_outcomes",
            "label": "Formulação dos resultados de aprendizagem",
            "message": (
                "A classificação taxonómica foi integrada nos resultados. "
                "Valide os resultados e os respetivos níveis antes de continuar."
            ),
        }

    state.pop("outcome_taxonomy", None)
    state.setdefault("feedback", {}).pop("outcome_taxonomy", None)

    if (
        previous_version < 12
        and state.get("current_stage") == "curriculum_analysis"
        and not state.get("learning_outcomes")
        and str(course.get("source_text", "")).strip()
    ):
        migrated_outcomes = formulate_learning_outcomes(state)
        state["learning_outcomes"] = migrated_outcomes["learning_outcomes"]
        state["audit"] = migrated_outcomes.get("audit", state.get("audit", []))
        versions.setdefault("learning_outcomes", []).append(
            state["learning_outcomes"]
        )
        state.setdefault("generation_metadata", {}).setdefault(
            "learning_outcomes", []
        ).append(
            {
                "provider": "CoerIA",
                "model": "Migração do fluxo Biggs",
                "duration_ms": 0,
                "total_tokens": 0,
                "validation_attempts": 1,
                "migration": True,
            }
        )
        state["current_stage"] = "learning_outcomes"
        state["status"] = "awaiting_review"
        state["review"] = {
            "stage": "learning_outcomes",
            "label": "Formulação dos resultados de aprendizagem",
            "message": (
                "Sessão atualizada para a sequência de alinhamento construtivo. "
                "Valide primeiro os resultados de aprendizagem."
            ),
        }

    sequential_flow_repositioned = (
        previous_version < 18
        and state.get("orchestration", {}).get("mode") != MANUAL_FIRST_MODE
        and state.get("status") != "completed"
        and state.get("current_stage") in {
            "assessment_activities",
            "pedagogical_design",
            "alignment_matrix",
            "resources",
            "final_validation",
        }
        and artifact_has_content(state.get("curriculum_analysis"))
        and not artifact_has_content(state.get("teaching_activities"))
    )
    if sequential_flow_repositioned:
        previous_stage = str(state.get("current_stage", ""))
        state["current_stage"] = "curriculum_analysis"
        state["status"] = "awaiting_review"
        state["review"] = {
            "stage": "curriculum_analysis",
            "label": STAGE_LABELS["curriculum_analysis"],
            "message": (
                "A sessão foi reposicionada para respeitar a sequência de alinhamento "
                "construtivo. Confirme esta etapa antes de gerar as atividades de "
                "ensino-aprendizagem."
            ),
        }
        state.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": "curriculum_analysis",
                "event": "Sessão sequencial reposicionada durante a migração.",
                "feedback": (
                    f"Etapa anterior: {previous_stage}. As versões posteriores foram "
                    "preservadas, mas deixaram de estar ativas."
                ),
            }
        )

    current_stage = state.get("current_stage", STAGE_ORDER[0])
    current_index = (
        STAGE_ORDER.index(current_stage)
        if current_stage in STAGE_ORDER
        else 0
    )
    existing_stage_statuses = state.setdefault("stage_statuses", {})
    existing_stage_statuses.pop("outcome_taxonomy", None)
    stage_statuses = (
        {}
        if previous_version < 12
        or removed_stage_was_current
        or sequential_flow_repositioned
        else existing_stage_statuses
    )
    for index, stage in enumerate(STAGE_ORDER):
        if stage in stage_statuses:
            continue
        if state.get("status") == "completed" and stage in state:
            stage_statuses[stage] = "approved"
        elif stage == current_stage and stage in state:
            stage_statuses[stage] = "awaiting_review"
        elif index < current_index and stage in state:
            stage_statuses[stage] = "approved"
        elif stage in state:
            stage_statuses[stage] = "stale"
        else:
            stage_statuses[stage] = "pending"
    state["stage_statuses"] = stage_statuses

    active_versions = state.setdefault("active_versions", {})
    active_versions.pop("outcome_taxonomy", None)
    if previous_version < 12 or removed_stage_was_current or sequential_flow_repositioned:
        for stage in STAGE_ORDER[current_index + 1 :]:
            if stage_statuses.get(stage) == "stale":
                active_versions.pop(stage, None)
    version_dependencies = state.setdefault("version_dependencies", {})
    version_dependencies.pop("outcome_taxonomy", None)
    for dependencies in version_dependencies.values():
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if isinstance(dependency, dict):
                    dependency.pop("outcome_taxonomy", None)
    if previous_version < 17:
        allowed_dependencies = {
            stage: set(STAGE_ORDER[:index])
            for index, stage in enumerate(STAGE_ORDER)
        }
        for stage, dependencies in version_dependencies.items():
            if not isinstance(dependencies, list):
                continue
            allowed = allowed_dependencies.get(stage, set())
            for dependency in dependencies:
                if not isinstance(dependency, dict):
                    continue
                for dependency_stage in list(dependency):
                    if dependency_stage not in allowed:
                        dependency.pop(dependency_stage, None)
        review = state.get("review")
        if isinstance(review, dict) and review.get("stage") in STAGE_LABELS:
            review["label"] = STAGE_LABELS[str(review["stage"])]
    for stage in STAGE_ORDER:
        stage_versions = versions.get(stage, [])
        if (
            stage in state
            and stage_versions
            and stage_statuses.get(stage) != "stale"
        ):
            active_versions.setdefault(stage, len(stage_versions))
        dependencies = version_dependencies.setdefault(stage, [])
        while len(dependencies) < len(stage_versions):
            dependencies.append({})
    state.setdefault("revision_snapshots", [])
    state.setdefault("ai_proposals", [])
    state.setdefault("ai_reviews", {})
    if previous_version < 15:
        state["orchestration"] = {
            "mode": MANUAL_FIRST_MODE,
            "human_approval_required": False,
            "llm_optional": True,
            "proposal_approval_required": True,
            "global_deterministic_validation_required": True,
        }
        ensure_manual_artifacts(state)
        migrated_statuses: dict[str, str] = {}
        for stage in STAGE_ORDER[:-1]:
            previous_status = str(stage_statuses.get(stage, "pending"))
            migrated_statuses[stage] = {
                "stale": "needs_review",
                "pending": "empty",
                "generating": "draft",
                "awaiting_review": "draft",
                "approved": "draft",
            }.get(previous_status, previous_status)
        migrated_statuses["final_validation"] = (
            "approved"
            if state.get("status") == "completed"
            else "checked"
            if state.get("final_validation")
            else "pending"
        )
        state["stage_statuses"] = migrated_statuses
        if state.get("status") != "completed":
            state["status"] = (
                "awaiting_review"
                if state.get("current_stage") == "final_validation"
                else "drafting"
            )
            current = state.get("current_stage", STAGE_ORDER[0])
            state["review"] = {
                "stage": current,
                "label": "Etapa de autoria",
                "message": (
                    "Sessão atualizada para autoria manual. O conteúdo existente "
                    "foi preservado e a IA passou a ser facultativa."
                ),
            }
    return state


class SQLiteSessionStore:
    """Armazena sessões CoerIA e respetivo rasto de auditoria em SQLite."""

    def __init__(self, database_path: Path | str | None = None) -> None:
        configured_path = os.getenv("COERIA_DATABASE_PATH", "").strip()
        selected_path = database_path or configured_path or DEFAULT_DATABASE_PATH
        self.database_path = Path(selected_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialise(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        session_id TEXT NOT NULL,
                        event_index INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        event TEXT NOT NULL,
                        feedback TEXT NOT NULL,
                        PRIMARY KEY (session_id, event_index),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(sessions)")
                }
                if "owner_id" not in columns:
                    connection.execute(
                        "ALTER TABLE sessions ADD COLUMN "
                        "owner_id TEXT NOT NULL DEFAULT 'LEGACY'"
                    )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated "
                    "ON sessions(owner_id, updated_at DESC)"
                )
        finally:
            connection.close()

    def save(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        owner_id: str = "LOCAL",
    ) -> str:
        """Cria ou atualiza uma sessão e substitui o respetivo rasto de auditoria."""

        owner = normalize_user_id(owner_id)
        if not owner:
            raise ValueError("A sessão necessita de um proprietário válido.")
        identifier = session_id or str(uuid4())
        updated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        audit = state.get("audit", [])
        stored_state = dict(state)
        stored_state["session_id"] = identifier

        connection = self._connect()
        try:
            with connection:
                existing = connection.execute(
                    "SELECT owner_id FROM sessions WHERE session_id = ?",
                    (identifier,),
                ).fetchone()
                if existing and existing["owner_id"] != owner:
                    raise PermissionError("A sessão pertence a outro utilizador.")
                connection.execute(
                    """
                    INSERT INTO sessions(session_id, owner_id, updated_at, state_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        state_json=excluded.state_json
                    """,
                    (
                        identifier,
                        owner,
                        updated_at,
                        json.dumps(stored_state, ensure_ascii=False),
                    ),
                )
                connection.execute(
                    "DELETE FROM audit_events WHERE session_id = ?",
                    (identifier,),
                )
                connection.executemany(
                    """
                    INSERT INTO audit_events(
                        session_id, event_index, timestamp, stage, event, feedback
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            identifier,
                            index,
                            event["timestamp"],
                            event["stage"],
                            event["event"],
                            event["feedback"],
                        )
                        for index, event in enumerate(audit)
                    ],
                )
        finally:
            connection.close()
        return identifier

    def load(
        self,
        session_id: str,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            if owner_id is None:
                row = connection.execute(
                    "SELECT state_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                owner = normalize_user_id(owner_id)
                row = connection.execute(
                    """
                    SELECT state_json FROM sessions
                    WHERE session_id = ? AND owner_id = ?
                    """,
                    (session_id, owner),
                ).fetchone()
        finally:
            connection.close()
        if not row:
            return None
        state = json.loads(row["state_json"])
        state["session_id"] = session_id
        return migrate_legacy_state(state)

    def list_sessions(
        self,
        limit: int = 100,
        owner_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Lista sessões recentes sem expor o conteúdo integral na interface."""

        if limit <= 0:
            return []
        connection = self._connect()
        try:
            if owner_id is None:
                rows = connection.execute(
                    """
                    SELECT session_id, updated_at, state_json
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                owner = normalize_user_id(owner_id)
                rows = connection.execute(
                    """
                    SELECT session_id, updated_at, state_json
                    FROM sessions
                    WHERE owner_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (owner, limit),
                ).fetchall()
        finally:
            connection.close()

        summaries: list[dict[str, str]] = []
        for row in rows:
            try:
                state = json.loads(row["state_json"])
                course = state.get("course", {})
                summaries.append(
                    {
                        "session_id": row["session_id"],
                        "updated_at": row["updated_at"],
                        "unit_name": str(course.get("unit_name", "Sessão sem título")),
                        "ai_provider": validate_ai_provider(
                            state.get("ai_provider", AI_PROVIDER_OPENAI)
                        ),
                        "current_stage": str(state.get("current_stage", "")),
                        "status": str(state.get("status", "")),
                    }
                )
            except (TypeError, json.JSONDecodeError):
                continue
        return summaries

    def delete(
        self,
        session_id: str,
        owner_id: str | None = None,
    ) -> bool:
        """Elimina uma sessão e o respetivo rasto de auditoria.

        Quando ``owner_id`` é fornecido, a operação só é executada se a
        sessão pertencer a esse utilizador.
        """

        identifier = str(session_id or "").strip()
        if not identifier:
            return False

        owner = normalize_user_id(owner_id) if owner_id is not None else None
        connection = self._connect()
        try:
            with connection:
                if owner is None:
                    row = connection.execute(
                        "SELECT 1 FROM sessions WHERE session_id = ?",
                        (identifier,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        SELECT 1 FROM sessions
                        WHERE session_id = ? AND owner_id = ?
                        """,
                        (identifier, owner),
                    ).fetchone()

                if row is None:
                    return False

                connection.execute(
                    "DELETE FROM audit_events WHERE session_id = ?",
                    (identifier,),
                )
                if owner is None:
                    cursor = connection.execute(
                        "DELETE FROM sessions WHERE session_id = ?",
                        (identifier,),
                    )
                else:
                    cursor = connection.execute(
                        """
                        DELETE FROM sessions
                        WHERE session_id = ? AND owner_id = ?
                        """,
                        (identifier, owner),
                    )
        finally:
            connection.close()

        return cursor.rowcount > 0
