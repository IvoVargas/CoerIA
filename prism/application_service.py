"""Casos de uso da aplicação, independentes da tecnologia de interface."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .assistance import build_initial_form_assistant, validate_initial_fields
from .auth import normalize_user_id
from .exporter import export_resource_package
from .ingestion import build_source_text, recover_direct_source_text
from .models import CourseInput, validate_resource_types
from .persistence import SQLiteSessionStore
from .providers import configured_ai_provider
from .workflow import (
    STAGE_LABELS,
    create_session,
    reopen_stage,
    review_current_stage,
    revision_impact,
)


class ApplicationService:
    """Coordena sessões sem devolver componentes específicos da interface."""

    def __init__(
        self,
        store: SQLiteSessionStore | None = None,
        owner_id: str = "LOCAL",
    ) -> None:
        self.store = store or SQLiteSessionStore()
        self.owner_id = normalize_user_id(owner_id)
        if not self.owner_id:
            raise ValueError("A aplicação necessita de um utilizador válido.")

    def _persist(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            state["session_id"] = self.store.save(
                state,
                session_id=state.get("session_id"),
                owner_id=self.owner_id,
            )
        except PermissionError as error:
            raise ValueError(
                "A sessão selecionada já não está disponível."
            ) from error
        return state

    def list_sessions(self) -> list[dict[str, str]]:
        return self.store.list_sessions(owner_id=self.owner_id)

    def start_session(
        self,
        form: dict[str, Any],
        source_files: list[str] | str | None = None,
    ) -> dict[str, Any]:
        source_text = str(form.get("source_text", "") or "")
        consolidated_source = build_source_text(source_text, source_files)
        course = CourseInput.create(
            str(form.get("unit_name", "") or ""),
            consolidated_source,
            str(form.get("audience", "") or ""),
            int(form.get("duration_hours", 0) or 0),
            taxonomy_type=str(form.get("taxonomy_type", "SOLO") or "SOLO"),
            program_name=str(form.get("program_name", "") or ""),
            program_type=str(form.get("program_type", "") or ""),
            academic_year=str(form.get("academic_year", "") or ""),
            semester=str(form.get("semester", "") or ""),
            cnaef_code=str(form.get("cnaef_code", "") or ""),
            cnaef_name=str(form.get("cnaef_name", "") or ""),
            ects_credits=float(form.get("ects_credits", 0) or 0),
            contact_hours=float(form.get("contact_hours", 0) or 0),
            autonomous_hours=float(form.get("autonomous_hours", 0) or 0),
            general_aims=str(form.get("general_aims", "") or ""),
            bibliography=str(form.get("bibliography", "") or ""),
        )
        state = create_session(
            course,
            list(form.get("resource_types", []) or []),
            ai_provider=str(
                form.get("ai_provider", configured_ai_provider())
                or configured_ai_provider()
            ),
        )
        state["source_input_text"] = source_text.strip()
        return self._persist(state)

    def load_session(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            raise ValueError("Selecione uma sessão para retomar.")
        state = self.store.load(session_id, owner_id=self.owner_id)
        if not state:
            raise ValueError("A sessão selecionada já não está disponível.")
        return state

    @staticmethod
    def restored_initial_fields(state: dict[str, Any]) -> dict[str, Any]:
        course = state.get("course", {})
        direct_source = state.get("source_input_text")
        if direct_source is None:
            direct_source = recover_direct_source_text(
                str(course.get("source_text", ""))
            )
        return {
            "unit_name": str(course.get("unit_name", "")),
            "audience": str(course.get("audience", "Ensino superior")),
            "duration_hours": int(course.get("duration_hours", 12)),
            "taxonomy_type": str(course.get("taxonomy_type", "SOLO")),
            "source_text": str(direct_source),
            "program_name": str(course.get("program_name", "")),
            "program_type": str(course.get("program_type", "")),
            "academic_year": str(course.get("academic_year", "")),
            "semester": str(course.get("semester", "")),
            "cnaef_code": str(course.get("cnaef_code", "")),
            "cnaef_name": str(course.get("cnaef_name", "")),
            "ects_credits": float(course.get("ects_credits", 0) or 0),
            "contact_hours": float(course.get("contact_hours", 0) or 0),
            "autonomous_hours": float(course.get("autonomous_hours", 0) or 0),
            "general_aims": str(course.get("general_aims", "")),
            "bibliography": str(course.get("bibliography", "")),
            "ai_provider": str(
                state.get("ai_provider", configured_ai_provider())
            ),
            "resource_types": list(state.get("resource_types", [])),
        }

    def review_session(
        self,
        state: dict[str, Any] | None,
        decision: str,
        feedback: str = "",
        revision_stage: str | None = None,
        resource_types: list[str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError(
                "Inicie ou retome primeiro uma sessão de autoria pedagógica."
            )
        working_state = state
        if resource_types is not None and state.get("current_stage") == "alignment_matrix":
            working_state = deepcopy(state)
            selected = validate_resource_types(resource_types)
            working_state["resource_types"] = selected
            for row in working_state.get("alignment_matrix", []):
                row["resource_types"] = list(selected)
            versions = working_state.get("versions", {}).get("alignment_matrix", [])
            if versions:
                versions[-1] = deepcopy(working_state.get("alignment_matrix", []))
        elif resource_types is not None and state.get("current_stage") == "resources":
            selected = validate_resource_types(resource_types)
            if selected != state.get("resource_types", []):
                raise ValueError(
                    "Para alterar os recursos, solicite a revisão da matriz de alinhamento."
                )

        updated = review_current_stage(
            working_state,
            decision=decision,
            feedback=feedback,
            revision_stage=revision_stage,
        )
        updated = self._persist(updated)
        if updated["status"] == "completed":
            message = "Validação final aprovada. O pacote final já pode ser exportado."
        elif decision == "approve":
            message = (
                "Proposta aprovada. A etapa "
                f"{STAGE_LABELS[updated['current_stage']]} está pronta para revisão."
            )
        else:
            message = (
                "Reformulação registada em "
                f"{STAGE_LABELS[updated['current_stage']]}."
            )
        return updated, message

    @staticmethod
    def revision_impact(
        state: dict[str, Any] | None,
        target_stage: str,
    ) -> dict[str, Any]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        return revision_impact(state, target_stage)

    def reopen_session(
        self,
        state: dict[str, Any] | None,
        target_stage: str,
        feedback: str,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = reopen_stage(state, target_stage, feedback)
        updated = self._persist(updated)
        return (
            updated,
            "Nova versão criada em "
            f"{STAGE_LABELS[target_stage]}. As etapas dependentes ficaram "
            "assinaladas para nova validação.",
        )

    def export_session(
        self,
        state: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        if not state:
            raise ValueError("Inicie ou retome uma sessão antes de exportar.")
        updated = deepcopy(state)
        updated.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": "Exportação",
                "event": "Pacote final exportado e rastreabilidade finalizada.",
                "feedback": "—",
            }
        )
        package_path = export_resource_package(updated)
        return package_path, self._persist(updated)

    @staticmethod
    def validate_initial_form(form: dict[str, Any]) -> dict[str, Any]:
        return validate_initial_fields(form)

    @staticmethod
    def propose_initial_form(form: dict[str, Any]) -> dict[str, Any]:
        original = dict(form)
        provider = original.pop("ai_provider", configured_ai_provider())
        original.pop("resource_types", None)
        return build_initial_form_assistant(str(provider)).propose(original)
