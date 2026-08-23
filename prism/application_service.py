"""Casos de uso da aplicação, independentes da tecnologia de interface."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable

from .assistance import build_initial_form_assistant, validate_initial_fields
from .auth import normalize_user_id
from .exporter import export_resource_package, normalize_document_formats
from .ingestion import (
    build_raw_source_text,
    extract_source_images,
    recover_direct_source_text,
)
from .models import (
    CourseInput,
    RESOURCE_PRESENTATION,
    SEMESTER_OPTIONS,
    validate_resource_types,
)
from .persistence import SQLiteSessionStore
from .source_reduction import reduce_source_text
from .providers import configured_ai_provider
from .workflow import (
    ResourceGenerationError,
    STAGE_LABELS,
    apply_manual_edit,
    create_session,
    decide_ai_proposal,
    navigate_to_stage,
    reopen_completed_manual_session,
    reopen_stage,
    request_ai_assistance,
    restore_stage_version,
    review_current_stage,
    revision_impact,
    update_manual_resource_settings,
    version_restore_impact,
    verify_stage_with_ai,
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

    def _prepare_source_for_ai(self, state: dict[str, Any]) -> dict[str, Any]:
        """Executa uma única vez a redução adiada, imediatamente antes de usar IA."""

        reduction = state.get("source_reduction", {})
        if not reduction.get("deferred"):
            return state
        original = str(
            state.get("source_original_text")
            or state.get("course", {}).get("source_text", "")
            or ""
        ).strip()
        result = reduce_source_text(
            original,
            provider=str(state.get("ai_provider") or configured_ai_provider()),
            allow_ai=True,
        )
        updated = deepcopy(state)
        updated["source_original_text"] = original
        updated.setdefault("course", {})["source_text"] = result.text
        updated["source_reduction"] = result.metadata
        updated.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": "Fontes documentais",
                "event": "Redução adiada executada antes do primeiro pedido à IA.",
                "feedback": "O texto original foi preservado fora do contexto enviado ao modelo.",
            }
        )
        return updated

    def list_sessions(self) -> list[dict[str, str]]:
        return self.store.list_sessions(owner_id=self.owner_id)

    def start_session(
        self,
        form: dict[str, Any],
        source_files: list[str] | str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if progress_callback is not None:
            progress_callback("A preparar os dados da unidade curricular…")
        source_text = str(form.get("source_text", "") or "")
        selected_provider = str(
            form.get("ai_provider", configured_ai_provider())
            or configured_ai_provider()
        )
        raw_source = build_raw_source_text(source_text, source_files)
        reduction = reduce_source_text(
            raw_source,
            provider=selected_provider,
            progress_callback=progress_callback,
            allow_ai=False,
        )
        consolidated_source = reduction.text
        source_images = extract_source_images(source_files)
        ai_image_generation_enabled = bool(
            form.get("ai_image_generation_enabled", True)
        )
        contact_hours = float(form.get("contact_hours", 0) or 0)
        autonomous_hours = float(form.get("autonomous_hours", 0) or 0)
        calculated_duration = contact_hours + autonomous_hours
        duration_hours = (
            calculated_duration
            if calculated_duration > 0
            else float(form.get("duration_hours", 0) or 0)
        )
        course = CourseInput.create(
            str(form.get("unit_name", "") or ""),
            consolidated_source,
            str(
                form.get("program_type")
                or form.get("audience")
                or "Ensino superior"
            ),
            duration_hours,
            taxonomy_type=str(form.get("taxonomy_type", "SOLO") or "SOLO"),
            program_name=str(form.get("program_name", "") or ""),
            program_type=str(form.get("program_type", "") or ""),
            academic_year=str(form.get("academic_year", "") or ""),
            semester=str(form.get("semester", "") or ""),
            cnaef_code=str(form.get("cnaef_code", "") or ""),
            cnaef_name=str(form.get("cnaef_name", "") or ""),
            ects_credits=float(form.get("ects_credits", 0) or 0),
            contact_hours=contact_hours,
            autonomous_hours=autonomous_hours,
            general_aims=str(form.get("general_aims", "") or ""),
            bibliography=str(form.get("bibliography", "") or ""),
        )
        state = create_session(
            course,
            list(form.get("resource_types", []) or []),
            ai_provider=selected_provider,
            ai_image_generation_enabled=ai_image_generation_enabled,
            source_reduction=reduction.metadata,
            progress_callback=progress_callback,
        )
        state["source_input_text"] = source_text.strip()
        state["source_original_text"] = raw_source
        state["source_images"] = source_images
        state["source_reduction"] = reduction.metadata
        if progress_callback is not None:
            progress_callback("A guardar a sessão e as estruturas de autoria manual…")
        return self._persist(state)

    def navigate_session(
        self,
        state: dict[str, Any] | None,
        target_stage: str,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = self._persist(navigate_to_stage(state, target_stage))
        return updated, f"Etapa aberta: {STAGE_LABELS[target_stage]}."

    @staticmethod
    def version_restore_impact(
        state: dict[str, Any] | None,
        selected_version: str,
    ) -> dict[str, Any]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        return version_restore_impact(state, selected_version)

    def restore_session_version(
        self,
        state: dict[str, Any] | None,
        selected_version: str,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = restore_stage_version(state, selected_version)
        updated = self._persist(updated)
        review = updated.get("review", {})
        return updated, str(
            review.get("message") or "Versão histórica novamente ativa."
        )

    def request_assistance(
        self,
        state: dict[str, Any] | None,
        target_stage: str,
        scope_path: list[str | int],
        scope_label: str,
        instruction: str,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        prepared = self._prepare_source_for_ai(state)
        updated = request_ai_assistance(
            prepared,
            target_stage,
            scope_path,
            scope_label,
            instruction,
        )
        updated = self._persist(updated)
        return updated, "Proposta da IA recebida. Reveja-a antes de decidir."

    def decide_assistance(
        self,
        state: dict[str, Any] | None,
        proposal_id: str,
        accept: bool,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = self._persist(decide_ai_proposal(state, proposal_id, accept))
        return (
            updated,
            "Proposta aplicada como nova versão."
            if accept
            else "Proposta rejeitada; o rascunho permaneceu inalterado.",
        )

    def verify_stage(
        self,
        state: dict[str, Any] | None,
        target_stage: str,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        prepared = self._prepare_source_for_ai(state)
        updated = self._persist(verify_stage_with_ai(prepared, target_stage))
        return updated, "Verificação facultativa da IA guardada; pode continuar."

    def update_resource_settings(
        self,
        state: dict[str, Any] | None,
        resource_types: list[str],
        selected_source_image_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = update_manual_resource_settings(
            state,
            resource_types,
            selected_source_image_ids,
        )
        return self._persist(updated), "Seleção de recursos guardada sem executar a IA."

    def load_session(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            raise ValueError("Selecione uma sessão para retomar.")
        state = self.store.load(session_id, owner_id=self.owner_id)
        if not state:
            raise ValueError("A sessão selecionada já não está disponível.")
        return state

    def delete_session(self, session_id: str | None) -> None:
        """Elimina definitivamente uma sessão pertencente ao utilizador atual."""

        if not session_id:
            raise ValueError("Selecione uma sessão para eliminar.")
        deleted = self.store.delete(session_id, owner_id=self.owner_id)
        if not deleted:
            raise ValueError("A sessão selecionada já não está disponível.")

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
            "duration_hours": float(course.get("duration_hours", 12)),
            "taxonomy_type": str(course.get("taxonomy_type", "SOLO")),
            "source_text": str(direct_source),
            "program_name": str(course.get("program_name", "")),
            "program_type": str(course.get("program_type", "")),
            "academic_year": str(course.get("academic_year", "")),
            "semester": str(course.get("semester") or SEMESTER_OPTIONS[0]),
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
            "ai_image_generation_enabled": bool(
                state.get("ai_image_generation_enabled", False)
            ),
        }

    def review_session(
        self,
        state: dict[str, Any] | None,
        decision: str,
        feedback: str = "",
        revision_stage: str | None = None,
        resource_types: list[str] | None = None,
        selected_source_image_ids: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError(
                "Inicie ou retome primeiro uma sessão de autoria pedagógica."
            )
        if progress_callback is not None:
            progress_callback("A validar a decisão e os dados da etapa atual…")
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

        if selected_source_image_ids is not None:
            if state.get("current_stage") != "alignment_matrix":
                raise ValueError(
                    "A seleção de imagens documentais só pode ser alterada antes da geração dos recursos."
                )
            if working_state is state:
                working_state = deepcopy(state)
            available_ids = {
                str(item.get("id", "")).strip()
                for item in working_state.get("source_images", [])
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            }
            requested_ids = [
                str(item).strip()
                for item in selected_source_image_ids
                if str(item).strip()
            ]
            requested_ids = list(dict.fromkeys(requested_ids))
            unknown = [item for item in requested_ids if item not in available_ids]
            if unknown:
                raise ValueError(
                    "A seleção contém imagens que já não estão disponíveis: "
                    + ", ".join(unknown)
                )
            presentation_selected = RESOURCE_PRESENTATION in working_state.get(
                "resource_types", []
            )
            content_slide_capacity = len(working_state.get("learning_outcomes", []))
            if presentation_selected and len(requested_ids) > content_slide_capacity:
                raise ValueError(
                    "Foram selecionadas mais imagens documentais do que os slides de "
                    "conteúdo previstos. Selecione no máximo "
                    f"{content_slide_capacity} imagem(ns) para garantir que todas são "
                    "usadas na apresentação."
                )
            working_state["selected_source_image_ids"] = (
                requested_ids if presentation_selected else []
            )

        try:
            updated = review_current_stage(
                working_state,
                decision=decision,
                feedback=feedback,
                revision_stage=revision_stage,
                progress_callback=progress_callback,
            )
        except ResourceGenerationError as error:
            draft_state = deepcopy(working_state)
            draft_state["resource_generation_drafts"] = deepcopy(error.drafts)
            persisted_draft_state = self._persist(draft_state)
            state.clear()
            state.update(deepcopy(persisted_draft_state))
            raise
        if progress_callback is not None:
            progress_callback("A guardar a nova etapa e a rastreabilidade…")
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
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        if progress_callback is not None:
            progress_callback("A validar o impacto da reformulação…")
        manual = state.get("orchestration", {}).get("mode") == "manual-first"
        if manual:
            updated = reopen_completed_manual_session(state, target_stage, feedback)
        else:
            updated = reopen_stage(
                state,
                target_stage,
                feedback,
                progress_callback=progress_callback,
            )
        if progress_callback is not None:
            progress_callback("A guardar a nova versão e as dependências…")
        updated = self._persist(updated)
        if manual:
            return (
                updated,
                f"Sessão reaberta em {STAGE_LABELS[target_stage]}. "
                "A exportação volta a ficar disponível após nova verificação global.",
            )
        return (
            updated,
            "Nova versão criada em "
            f"{STAGE_LABELS[target_stage]}. As etapas dependentes ficaram "
            "assinaladas para nova validação.",
        )

    def save_manual_edit(
        self,
        state: dict[str, Any] | None,
        target_stage: str,
        artifact: Any,
        reason: str = "",
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = apply_manual_edit(state, target_stage, artifact, reason)
        updated = self._persist(updated)
        return (
            updated,
            "Edição manual guardada em "
            f"{STAGE_LABELS[target_stage]}. As etapas dependentes ficaram "
            "assinaladas para nova validação.",
        )

    def export_session(
        self,
        state: dict[str, Any] | None,
        document_formats: list[str] | tuple[str, ...] | str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if not state:
            raise ValueError("Inicie ou retome uma sessão antes de exportar.")
        formats = normalize_document_formats(document_formats)
        format_labels = {
            "word": "Word",
            "latex": "LaTeX",
        }
        updated = deepcopy(state)
        updated["last_export_document_formats"] = list(formats)
        updated.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": "Exportação",
                "event": "Pacote final exportado e rastreabilidade finalizada.",
                "feedback": "Formatos documentais: "
                + ", ".join(format_labels[item] for item in formats)
                + ".",
            }
        )
        package_path = export_resource_package(updated, formats)
        return package_path, self._persist(updated)

    @staticmethod
    def validate_initial_form(form: dict[str, Any]) -> dict[str, Any]:
        return validate_initial_fields(form)

    @staticmethod
    def propose_initial_form(form: dict[str, Any]) -> dict[str, Any]:
        original = dict(form)
        provider = original.pop("ai_provider", configured_ai_provider())
        original.pop("resource_types", None)
        original.pop("ai_image_generation_enabled", None)
        return build_initial_form_assistant(str(provider)).propose(original)
