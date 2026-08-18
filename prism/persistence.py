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
from .providers import AI_PROVIDER_OPENAI, validate_ai_provider


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "prism.db"


def migrate_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta os campos estruturais novos sem apagar artefactos históricos."""

    previous_version = int(state.get("schema_version", 1) or 1)
    if previous_version < 11:
        state.setdefault("migrated_from_schema_version", previous_version)
    state["schema_version"] = 11
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
        "semester": "",
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

    analysis = state.get("curriculum_analysis")
    if isinstance(analysis, dict):
        legacy_aims = (
            analysis.get("aims")
            or course.get("general_aims")
            or "Desenvolver os conhecimentos e competências previstos."
        )
        analysis.setdefault(
            "objectives",
            [{"id": "OG1", "statement": str(legacy_aims)}],
        )
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
        objective_ids = [
            objective.get("id", "")
            for objective in (
                analysis.get("objectives", []) if isinstance(analysis, dict) else []
            )
            if objective.get("id")
        ]
        item.setdefault("objective_ids", objective_ids[:1] or ["OG1"])

    if "outcome_taxonomy" not in state and state.get("learning_outcomes"):
        state["outcome_taxonomy"] = [
            {
                "outcome_id": item.get("id", f"RA{index + 1}"),
                "taxonomy": "SOLO",
                "level": item.get("solo_level", "Uni-estrutural"),
                "action_verb": item.get("action_verb", "identificar"),
            }
            for index, item in enumerate(state.get("learning_outcomes", []))
        ]
        item.setdefault(
            "content_links",
            [{
                "content_id": content_by_theme.get(
                    str(item.get("theme", "")).casefold(), f"C{index + 1}"
                ),
                "importance": "Principal",
            }],
        )

    assessments = state.get("assessment_activities", [])
    for index, item in enumerate(assessments):
        item.setdefault("id", f"AV{index + 1}")
        item.setdefault("outcome_ids", [item.get("outcome_id", "")])
        item.setdefault("work_type", "Não especificado")
        item.setdefault("assessment_purpose", "Sumativa")

    for index, item in enumerate(state.get("teaching_activities", [])):
        outcome_ids = item.setdefault("outcome_ids", [item.get("outcome_id", "")])
        item.setdefault("id", f"EA{index + 1}")
        item.setdefault(
            "assessment_ids",
            [
                assessment.get("id", "")
                for assessment in assessments
                if set(outcome_ids) & set(assessment.get("outcome_ids", []))
            ],
        )
        item.setdefault("learning_context", "Não especificado")
        item.setdefault("practice", item.get("activity", "Prática orientada."))
        item.setdefault("support", "Acompanhamento do docente.")
        item.setdefault("feedback_strategy", "Feedback formativo.")

    outcome_by_id = {
        str(item.get("id", "")): item for item in state.get("learning_outcomes", [])
    }
    taxonomy_by_outcome = {
        str(item.get("outcome_id", "")): item
        for item in state.get("outcome_taxonomy", [])
    }
    for row in state.get("alignment_matrix", []):
        outcome_id = str(row.get("outcome_id", ""))
        row.setdefault(
            "objective_ids",
            list(outcome_by_id.get(outcome_id, {}).get("objective_ids", [])),
        )
        row.setdefault(
            "content_ids",
            [
                link.get("content_id", "")
                for link in outcome_by_id.get(outcome_id, {}).get("content_links", [])
            ],
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
            taxonomy_by_outcome.get(outcome_id, {}).get("taxonomy", "SOLO"),
        )
        row.setdefault(
            "taxonomy_level",
            taxonomy_by_outcome.get(outcome_id, {}).get(
                "level", "Uni-estrutural"
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
    if state.get("outcome_taxonomy") and "outcome_taxonomy" not in versions:
        versions["outcome_taxonomy"] = [state["outcome_taxonomy"]]
    from .workflow import STAGE_ORDER

    current_stage = state.get("current_stage", STAGE_ORDER[0])
    current_index = (
        STAGE_ORDER.index(current_stage)
        if current_stage in STAGE_ORDER
        else 0
    )
    stage_statuses = state.setdefault("stage_statuses", {})
    for index, stage in enumerate(STAGE_ORDER):
        if stage in stage_statuses:
            continue
        if state.get("status") == "completed" and stage in state:
            stage_statuses[stage] = "approved"
        elif stage == current_stage and stage in state:
            stage_statuses[stage] = "awaiting_review"
        elif index < current_index and stage in state:
            stage_statuses[stage] = "approved"
        else:
            stage_statuses[stage] = "pending"

    active_versions = state.setdefault("active_versions", {})
    version_dependencies = state.setdefault("version_dependencies", {})
    for stage in STAGE_ORDER:
        stage_versions = versions.get(stage, [])
        if stage in state and stage_versions:
            active_versions.setdefault(stage, len(stage_versions))
        dependencies = version_dependencies.setdefault(stage, [])
        while len(dependencies) < len(stage_versions):
            dependencies.append({})
    state.setdefault("revision_snapshots", [])
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
