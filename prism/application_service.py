"""Casos de uso da aplicação, independentes da tecnologia de interface."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .assistance import build_initial_form_assistant, validate_initial_fields
from .auth import normalize_user_id
from .exporter import export_resource_package, normalize_document_formats
from .image_generation import (
    OpenAIImageGenerator,
    build_image_prompt,
    build_uploaded_image_asset,
    configured_max_additional_editor_images,
    manual_editor_image_count,
    suggest_image_prompt,
)
from .ingestion import (
    build_raw_source_text,
    extract_source_images,
    recover_direct_source_text,
    replace_direct_source_text,
    source_file_names,
)
from .models import (
    CourseInput,
    SEMESTER_OPTIONS,
    validate_resource_types,
)
from .persistence import SQLiteSessionStore, migrate_legacy_state
from .quality import attach_quality_report
from .source_reduction import reduce_source_text
from .providers import configured_ai_provider
from .session_backup import (
    capture_source_attachments,
    create_session_backup,
    read_session_backup,
)
from .workflow import (
    ResourceGenerationError,
    SCHEMA_VERSION,
    STAGE_LABELS,
    STAGE_ORDER,
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
    update_initial_context,
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
        for attachment in state.get("source_attachments", []):
            if isinstance(attachment, dict):
                attachment.pop("data_base64", None)
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

    @staticmethod
    def _consume_temporary_download(path_value: str) -> tuple[bytes, str]:
        """Lê um resultado temporário e remove-o mesmo quando a leitura falha."""

        path = Path(path_value)
        try:
            return path.read_bytes(), path.name
        finally:
            path.unlink(missing_ok=True)

    def backup_session(
        self,
        session_id: str | None,
    ) -> tuple[bytes, str]:
        """Cria uma cópia portátil sem alterar a sessão de origem."""

        state = self.load_session(session_id, include_source_attachments=True)
        return self._consume_temporary_download(
            create_session_backup(state)
        )

    def restore_session_backup(
        self,
        data: bytes,
    ) -> dict[str, Any]:
        """Restaura uma cópia como nova sessão do utilizador autenticado."""

        imported_state, manifest = read_session_backup(data)
        try:
            imported_schema = int(imported_state.get("schema_version", 1) or 1)
        except (TypeError, ValueError) as error:
            raise ValueError("A cópia contém uma versão de dados inválida.") from error
        if imported_schema > SCHEMA_VERSION:
            raise ValueError(
                "A cópia foi criada por uma versão mais recente do CoerIA. "
                "Atualize a aplicação antes de restaurar."
            )
        try:
            restored = migrate_legacy_state(deepcopy(imported_state))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "A cópia contém um estado de sessão incompatível ou incompleto."
            ) from error
        course = restored.get("course")
        if not isinstance(course, dict) or not str(course.get("unit_name", "")).strip():
            raise ValueError("A cópia não contém a identificação da sessão.")
        if restored.get("current_stage") not in STAGE_ORDER:
            raise ValueError("A cópia contém uma etapa atual inválida.")
        audit = restored.get("audit")
        if not isinstance(audit, list) or any(
            not isinstance(item, dict)
            or any(
                key not in item or not isinstance(item.get(key), str)
                for key in ("timestamp", "stage", "event", "feedback")
            )
            for item in audit
        ):
            raise ValueError("A cópia contém um histórico de auditoria inválido.")

        source_session_id = str(
            manifest.get("source_session_id")
            or imported_state.get("session_id")
            or "desconhecida"
        )[:128]
        restored_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        restored.pop("session_id", None)
        restored["restored_from_backup"] = {
            "source_session_id": source_session_id,
            "format_version": manifest.get("format_version"),
            "backup_created_at": str(manifest.get("created_at", "")),
            "restored_at": restored_at,
        }
        restored.setdefault("audit", []).append(
            {
                "timestamp": restored_at,
                "stage": "Cópia de segurança",
                "event": "Sessão restaurada a partir de uma cópia de segurança.",
                "feedback": f"Sessão de origem: {source_session_id}.",
            }
        )
        return self._persist(restored)

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
        source_attachments = capture_source_attachments(source_files)
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
            isced_f_code=str(form.get("isced_f_code", "") or ""),
            isced_f_name=str(form.get("isced_f_name", "") or ""),
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
        state["source_attachments"] = source_attachments
        state["source_reduction"] = reduction.metadata
        if progress_callback is not None:
            progress_callback("A guardar a sessão e as estruturas de autoria manual…")
        return self._persist(state)

    def update_session_initial_data(
        self,
        state: dict[str, Any] | None,
        form: dict[str, Any],
        source_files: list[str] | str | None = None,
        removed_source_files: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Guarda alterações iniciais e conserva o trabalho pedagógico existente."""

        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        if state.get("status") == "completed":
            raise ValueError(
                "A sessão concluída está em modo de consulta. Reabra-a explicitamente "
                "antes de alterar os dados iniciais."
            )
        if progress_callback is not None:
            progress_callback("A validar as alterações aos dados iniciais…")

        direct_source = str(form.get("source_text", "") or "").strip()
        selected_provider = str(
            form.get("ai_provider", state.get("ai_provider", configured_ai_provider()))
            or configured_ai_provider()
        )
        old_direct_source = str(
            state.get("source_input_text")
            if state.get("source_input_text") is not None
            else recover_direct_source_text(str(state.get("source_original_text", "")))
        ).strip()
        has_new_files = bool(source_files)
        removed_sources = {
            str(name).strip()
            for name in (removed_source_files or [])
            if str(name).strip()
        }
        sources_changed = (
            direct_source != old_direct_source or has_new_files or bool(removed_sources)
        )
        if sources_changed:
            raw_source = replace_direct_source_text(
                str(state.get("source_original_text", "")),
                direct_source,
                source_files,
                removed_sources,
            )
            reduction = reduce_source_text(
                raw_source,
                provider=selected_provider,
                progress_callback=progress_callback,
                allow_ai=False,
            )
            consolidated_source = reduction.text
            reduction_metadata = reduction.metadata
        else:
            raw_source = str(
                state.get("source_original_text")
                or state.get("course", {}).get("source_text", "")
            )
            consolidated_source = str(state.get("course", {}).get("source_text", ""))
            reduction_metadata = deepcopy(state.get("source_reduction", {}))

        contact_hours = float(form.get("contact_hours", 0) or 0)
        autonomous_hours = float(form.get("autonomous_hours", 0) or 0)
        calculated_duration = contact_hours + autonomous_hours
        duration_hours = (
            calculated_duration
            if calculated_duration > 0
            else float(
                form.get("duration_hours")
                or state.get("course", {}).get("duration_hours", 0)
                or 0
            )
        )
        course = CourseInput.create(
            str(form.get("unit_name", "") or ""),
            consolidated_source,
            str(form.get("program_type") or form.get("audience") or "Ensino superior"),
            duration_hours,
            taxonomy_type=str(form.get("taxonomy_type", "SOLO") or "SOLO"),
            program_name=str(form.get("program_name", "") or ""),
            program_type=str(form.get("program_type", "") or ""),
            academic_year=str(form.get("academic_year", "") or ""),
            semester=str(form.get("semester", "") or ""),
            cnaef_code=str(form.get("cnaef_code", "") or ""),
            cnaef_name=str(form.get("cnaef_name", "") or ""),
            isced_f_code=str(form.get("isced_f_code", "") or ""),
            isced_f_name=str(form.get("isced_f_name", "") or ""),
            ects_credits=float(form.get("ects_credits", 0) or 0),
            contact_hours=contact_hours,
            autonomous_hours=autonomous_hours,
            general_aims=str(form.get("general_aims", "") or ""),
            bibliography=str(form.get("bibliography", "") or ""),
        )
        source_images = [
            deepcopy(asset)
            for asset in state.get("source_images", [])
            if not isinstance(asset, dict)
            or str(asset.get("source_file", "")).strip() not in removed_sources
        ]
        if has_new_files:
            known_ids = {
                str(asset.get("id", ""))
                for asset in source_images
                if isinstance(asset, dict)
            }
            for asset in extract_source_images(source_files):
                if str(asset.get("id", "")) not in known_ids:
                    source_images.append(asset)
                    known_ids.add(str(asset.get("id", "")))

        source_attachments = [
            deepcopy(attachment)
            for attachment in state.get("source_attachments", [])
            if not isinstance(attachment, dict)
            or str(attachment.get("source_file", "")).strip()
            not in removed_sources
        ]
        if has_new_files:
            known_attachment_ids = {
                str(attachment.get("id", ""))
                for attachment in source_attachments
                if isinstance(attachment, dict)
            }
            for attachment in capture_source_attachments(source_files):
                if str(attachment.get("id", "")) not in known_attachment_ids:
                    source_attachments.append(attachment)
                    known_attachment_ids.add(str(attachment.get("id", "")))

        updated = update_initial_context(
            state,
            course,
            ai_provider=selected_provider,
            source_input_text=direct_source,
            source_original_text=raw_source,
            source_reduction=reduction_metadata,
            source_images=source_images,
        )
        updated["source_attachments"] = source_attachments
        if progress_callback is not None:
            progress_callback("A guardar os dados e a assinalar as etapas para revisão…")
        return self._persist(updated)

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
        selections: list[dict[str, Any]] | None = None,
        edited_after: Any = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = self._persist(
            decide_ai_proposal(
                state,
                proposal_id,
                accept,
                selections,
                edited_after=edited_after,
            )
        )
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
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = update_manual_resource_settings(
            state,
            resource_types,
        )
        return self._persist(updated), "Seleção de recursos guardada sem executar a IA."

    @staticmethod
    def suggest_presentation_image_prompt(
        state: dict[str, Any] | None,
        slide: dict[str, Any],
        slide_number: int,
    ) -> str:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        return suggest_image_prompt(state, slide, slide_number)

    def generate_presentation_editor_image(
        self,
        state: dict[str, Any] | None,
        slide: dict[str, Any],
        slide_number: int,
        requested_prompt: str,
        *,
        generator: OpenAIImageGenerator | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Gera e guarda uma imagem adicional pedida explicitamente pelo docente."""

        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        clean_prompt = str(requested_prompt).strip()
        if not clean_prompt:
            raise ValueError("Escreva ou peça uma instrução antes de gerar a imagem.")
        maximum = configured_max_additional_editor_images()
        if manual_editor_image_count(state) >= maximum:
            raise ValueError(
                "Já foi atingido o limite de "
                f"{maximum} imagem"
                + ("" if maximum == 1 else "s")
                + " adicional"
                + ("" if maximum == 1 else "is")
                + " gerada"
                + ("" if maximum == 1 else "s")
                + " durante a edição."
            )

        working = deepcopy(state)
        requested_slide = deepcopy(slide)
        requested_slide["visual_prompt"] = clean_prompt
        final_prompt = build_image_prompt(working, requested_slide, slide_number)
        image_generator = generator or OpenAIImageGenerator()
        asset = image_generator.generate(
            prompt=final_prompt,
            slide_number=slide_number,
            alt_text=str(slide.get("alt_text", "")).strip()
            or f"Ilustração educativa associada ao slide {slide_number}.",
        )
        asset["generation_mode"] = "manual_editor"
        asset["requested_slide_number"] = int(slide_number)
        working.setdefault("generated_images", []).append(asset)
        working.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": STAGE_LABELS["resources"],
                "event": "Imagem adicional gerada por pedido explícito do docente.",
                "feedback": f"Slide {slide_number}; modelo {asset.get('model', '—')}.",
            }
        )
        return self._persist(working), deepcopy(asset)

    def add_presentation_uploaded_image(
        self,
        state: dict[str, Any] | None,
        filename: str,
        data: bytes,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Guarda uma imagem local no catálogo da sessão sem a enviar para IA."""

        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        asset = build_uploaded_image_asset(data, filename)
        working = deepcopy(state)
        working.setdefault("source_images", []).append(asset)
        working.setdefault("audit", []).append(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "stage": STAGE_LABELS["resources"],
                "event": "Imagem carregada pelo docente para a apresentação.",
                "feedback": str(asset.get("source_file", "Imagem local")),
            }
        )
        return self._persist(working), deepcopy(asset)

    def load_session(
        self,
        session_id: str | None,
        *,
        include_source_attachments: bool = False,
    ) -> dict[str, Any]:
        if not session_id:
            raise ValueError("Selecione uma sessão para retomar.")
        state = self.store.load(
            session_id,
            owner_id=self.owner_id,
            include_source_attachments=include_source_attachments,
        )
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
            "isced_f_code": str(course.get("isced_f_code", "")),
            "isced_f_name": str(course.get("isced_f_name", "")),
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

    @staticmethod
    def restored_source_file_names(state: dict[str, Any]) -> list[str]:
        """Devolve as fontes já incorporadas, pela ordem original."""

        return source_file_names(str(state.get("source_original_text", "")))

    def review_session(
        self,
        state: dict[str, Any] | None,
        decision: str,
        feedback: str = "",
        revision_stage: str | None = None,
        resource_types: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError(
                "Inicie ou retome primeiro uma sessão de autoria pedagógica."
            )
        if progress_callback is not None:
            progress_callback("A validar a decisão e os dados da etapa atual…")
        working_state = state
        if resource_types is not None and state.get("current_stage") == "resources":
            selected = validate_resource_types(resource_types)
            if selected != state.get("resource_types", []):
                raise ValueError(
                    "Guarde a seleção na etapa Geração de recursos educativos antes "
                    "de gerar conteúdo."
                )
        elif resource_types is not None:
            raise ValueError(
                "A seleção de recursos só pode ser alterada na etapa "
                "Geração de recursos educativos."
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
        stage_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not state:
            raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
        updated = apply_manual_edit(
            state,
            target_stage,
            artifact,
            reason,
            stage_context=stage_context,
        )
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
    ) -> tuple[bytes, str, dict[str, Any]]:
        if not state:
            raise ValueError("Inicie ou retome uma sessão antes de exportar.")
        formats = normalize_document_formats(document_formats)
        format_labels = {
            "word": "Word",
            "latex": "LaTeX",
        }
        updated = deepcopy(state)
        resources = updated.get("resources")
        if isinstance(resources, dict):
            updated["resources"] = attach_quality_report(updated, resources)
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
        package_data, package_filename = self._consume_temporary_download(
            package_path
        )
        return package_data, package_filename, self._persist(updated)

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
