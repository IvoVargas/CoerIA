"""Interface NiceGUI do CoerIA, orientada à validação humana por etapa."""

from __future__ import annotations

from copy import deepcopy
import json
import logging
from pathlib import Path
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app, events, run, ui
from starlette.middleware.base import BaseHTTPMiddleware

from prism.agents import AgentGenerationError, DEFAULT_MODEL
from prism.application_service import ApplicationService
from prism.auth import (
    CredentialConfigurationError,
    CredentialStore,
    Identity,
    LoginThrottle,
    authentication_disabled,
    configured_storage_secret,
    identity_from_session,
    safe_redirect_path,
)
from prism.branding import APP_FULL_NAME, APP_NAME, APP_TAGLINE, APP_VERSION
from prism.curriculum import TAXONOMY_CHOICES
from prism.exporter import (
    DOCUMENT_FORMAT_LATEX,
    DOCUMENT_FORMAT_WORD,
    latex_pdf_compilation_enabled,
)
from prism.image_generation import (
    ImageGenerationError,
    configured_max_additional_editor_images,
    configured_presentation_image_upload_bytes,
    manual_editor_image_count,
)
from prism.ingestion import (
    SUPPORTED_SOURCE_SUFFIXES,
    SourceIngestionError,
    configured_max_file_bytes,
    configured_max_total_upload_bytes,
)
from prism.cnaef import CNAEF_CATALOG, cnaef_options
from prism.isced import ISCED_F_CATALOG, isced_f_options
from prism.manual_editing import (
    FieldSpec,
    TableSpec,
    assistance_scope_options,
    apply_editor_field_value,
    apply_presentation_image_choice,
    available_presentation_images,
    editor_field_value,
    editor_reference_options,
    editor_reference_value,
    editor_taxonomy_level_options,
    editor_taxonomy_verb_options,
    editor_layout,
    move_table_row,
    new_table_row,
    presentation_image_label,
    proposal_review_changes,
    value_at_path,
)
from prism.models import (
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
    SEMESTER_OPTIONS,
    SUPPORTED_RESOURCE_TYPES,
)
from prism.persistence import SQLiteSessionStore
from prism.presentation import (
    active_stage_artifact,
    audit_rows,
    current_history_value,
    history_choices,
    render_current_artifact,
    render_history_artifact,
    render_resource_detail_sections,
    render_stage_artifact,
)
from prism.providers import AI_PROVIDER_CHOICES, configured_ai_provider
from prism.session_backup import configured_session_backup_max_bytes
from prism.workflow import (
    STAGE_LABELS,
    STAGE_ORDER,
    ai_review_is_current,
    is_manual_first,
    revision_targets_for_state,
)
from prism.validation_targets import (
    STAGE_ROOT_TARGET,
    resolve_validation_target,
)


SESSION_STORE = SQLiteSessionStore()
SERVICE = ApplicationService(SESSION_STORE)
LOGIN_THROTTLE = LoginThrottle()
RESOURCE_TYPES = list(SUPPORTED_RESOURCE_TYPES)
RESOURCE_TAB_CONFIG = (
    (RESOURCE_PRESENTATION, "presentation", "Apresentação", "slideshow", "presentation_outline"),
    (RESOURCE_WORKSHEET, "worksheet", "Ficha de aula", "description", "lesson_worksheet"),
    (RESOURCE_TEST, "test", "Teste", "quiz", "test"),
    (RESOURCE_PRACTICAL, "practical", "Atividade prática", "construction", "practical_activity"),
)
LATEX_PDF_ENABLED = latex_pdf_compilation_enabled()
EXPORT_DOCUMENT_FORMAT_CHOICES = (
    {
        "word": "Word (.docx)",
        "latex": "LaTeX (.tex + .pdf)",
        "both": "Word e LaTeX/PDF",
    }
    if LATEX_PDF_ENABLED
    else {
        "word": "Word (.docx)",
        "latex": "LaTeX (.tex)",
        "both": "Word e LaTeX",
    }
)
_history_choices = history_choices  # compatibilidade para consulta programática

USER_ERRORS = (
    ValueError,
    SourceIngestionError,
    AgentGenerationError,
    ImageGenerationError,
)
LOGGER = logging.getLogger(__name__)
UNRESTRICTED_PAGE_ROUTES = {"/favicon.ico", "/login"}
ERROR_NOTIFICATION_TIMEOUT_SECONDS = 12
INITIAL_DATA_STAGE = "initial_data"
INITIAL_DATA_LABEL = "Dados iniciais"
DISPLAY_STAGE_COUNT = len(STAGE_ORDER) + 1
STAGE_STATUS_CSS_CLASSES = {
    "empty": "stage-status-empty",
    "pending": "stage-status-pending",
    "draft": "stage-status-draft",
    "checked": "stage-status-checked",
    "approved": "stage-status-approved",
    "needs_review": "stage-status-needs-review",
    "stale": "stage-status-stale",
    "awaiting_review": "stage-status-awaiting-review",
    "generating": "stage-status-generating",
}


def _replace_error_notification(current: Any | None, message: str) -> Any:
    """Mostra um único erro descartável, removendo a notificação anterior."""

    if current is not None:
        for method_name in ("dismiss", "delete"):
            try:
                getattr(current, method_name)()
            except Exception:  # A notificação pode já ter sido fechada pelo utilizador.
                LOGGER.debug(
                    "Não foi possível executar %s na notificação anterior.",
                    method_name,
                    exc_info=True,
                )
    return ui.notification(
        message,
        type="negative",
        multi_line=True,
        position="top",
        close_button="Fechar",
        timeout=ERROR_NOTIFICATION_TIMEOUT_SECONDS,
    )


def _format_elapsed_duration(elapsed_seconds: float) -> str:
    total_seconds = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"Tempo decorrido: {minutes} min {seconds:02d} s"
    return f"Tempo decorrido: {seconds} s"


def _busy_phase_message(phase: str, phase_elapsed_seconds: float) -> str:
    elapsed = max(0, int(phase_elapsed_seconds))
    is_generation = phase.startswith("A gerar e validar")
    is_resource_generation = phase.startswith("A gerar recurso")
    is_resource_retry = phase.startswith("A corrigir recurso")
    if is_resource_generation or is_resource_retry:
        if elapsed < 20:
            return phase
        if elapsed < 60:
            return "A aguardar a resposta do fornecedor de IA para este recurso…"
        return "A geração deste recurso continua ativa no fornecedor de IA…"
    if elapsed < 8 or not is_generation:
        return phase
    if elapsed < 30:
        return "A aguardar a resposta do fornecedor de IA…"
    if "Geração de recursos educativos" in phase:
        return (
            "O fornecedor continua a gerar os recursos educativos; "
            "esta é normalmente a etapa mais demorada…"
        )
    return "O fornecedor continua a gerar a proposta; a operação está ativa…"


def _stage_status_css_class(status: str | None) -> str:
    """Converte estados persistidos numa classe visual controlada."""

    return STAGE_STATUS_CSS_CLASSES.get(
        str(status or "pending"),
        STAGE_STATUS_CSS_CLASSES["pending"],
    )


@app.add_middleware
class AuthMiddleware(BaseHTTPMiddleware):
    """Restringe páginas privadas, permitindo apenas o login e recursos internos."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            authentication_disabled()
            or app.storage.user.get("authenticated")
            or path in UNRESTRICTED_PAGE_ROUTES
            or path.startswith("/_nicegui")
        ):
            return await call_next(request)
        return RedirectResponse(f"/login?redirect_to={path}")


APP_CSS = """
:root {
  --agir-ink: #14282d;
  --agir-muted: #60767a;
  --agir-primary: #0d766e;
  --agir-secondary: #1f5966;
  --agir-accent: #e8a23a;
  --agir-bg: #f3f7f6;
  --agir-surface: #ffffff;
  --agir-border: #dce8e6;
  --agir-success: #1c7c54;
}

body { background: var(--agir-bg); color: var(--agir-ink); }
.q-layout, .q-page-container { background: var(--agir-bg); }
.agir-header {
  background: rgba(255, 255, 255, .96) !important;
  color: var(--agir-ink) !important;
  border-bottom: 1px solid var(--agir-border);
  backdrop-filter: blur(16px);
  flex-wrap: nowrap !important;
  gap: 6px !important;
}
.agir-drawer { background: #0f3036 !important; color: #eef8f6; }
.agir-drawer .q-btn { color: inherit; }
.agir-main { width: 100%; max-width: 1480px; margin: 0 auto; padding: 28px 32px 72px; }
.brand-mark {
  width: 42px; height: 42px; border-radius: 13px;
  display: grid; place-items: center; color: white; font-weight: 800;
  background: linear-gradient(135deg, var(--agir-primary), var(--agir-secondary));
  box-shadow: 0 8px 20px rgba(13, 118, 110, .24);
}
.eyebrow { color: var(--agir-primary); font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.hero-title { font-size: clamp(2rem, 4vw, 3.6rem); line-height: 1.04; font-weight: 800; letter-spacing: -.04em; max-width: 920px; }
.hero-copy { color: var(--agir-muted); font-size: 1.05rem; line-height: 1.7; max-width: 850px; }
.surface {
  background: var(--agir-surface); border: 1px solid var(--agir-border);
  border-radius: 20px; box-shadow: 0 12px 34px rgba(31, 71, 75, .07);
}
.soft-surface { background: #edf5f3; border: 1px solid #d8e9e5; border-radius: 16px; }
.section-title { font-size: 1.2rem; font-weight: 750; letter-spacing: -.015em; }
.muted { color: var(--agir-muted); }
.full-control, .full-control .q-field { width: 100%; }
.primary-action { border-radius: 12px !important; min-height: 44px; font-weight: 700; }
.secondary-action { border-radius: 12px !important; min-height: 42px; font-weight: 650; }
.stage-track {
  display: grid;
  grid-template-columns: repeat(var(--stage-count), minmax(126px, 1fr));
  gap: 8px;
  width: 100%; overflow-x: auto; padding: 4px 2px 12px;
}
.stage-item { min-width: 126px; border-radius: 14px; padding: 12px; border: 1px solid var(--agir-border); background: white; color: inherit; text-align: left; transition: transform .15s ease, box-shadow .15s ease; }
.stage-item.stage-status-empty { background: #ffffff; border-color: #c6d7d4; }
.stage-item.stage-status-pending { background: #eef2f8; border-color: #afbed3; }
.stage-item.stage-status-draft { background: #dceef8; border-color: #7fb6d3; }
.stage-item.stage-status-checked { background: #e8e3f4; border-color: #ad9acb; }
.stage-item.stage-status-approved { background: #d9efe4; border-color: #82c2a3; }
.stage-item.stage-status-needs-review,
.stage-item.stage-status-stale { background: #ffedc7; border-color: #d59f33; }
.stage-item.stage-status-awaiting-review { background: #d9eeeb; border-color: #74bdb6; }
.stage-item.stage-status-generating { background: #eadcf3; border-color: #b387cb; }
.stage-item.current { color: white; background: linear-gradient(135deg, var(--agir-primary), var(--agir-secondary)); border-color: transparent; box-shadow: 0 8px 20px rgba(13, 118, 110, .2); }
.stage-item.selectable { cursor: pointer; font: inherit; }
.stage-item.selectable:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(31, 71, 75, .11); }
.stage-item.viewing { outline: 3px solid var(--agir-accent); outline-offset: 2px; }
.stage-number { font-size: .72rem; font-weight: 800; opacity: .72; }
.stage-label { font-size: .78rem; line-height: 1.25; font-weight: 700; margin-top: 5px; }
.stage-state { font-size: .67rem; line-height: 1.2; margin-top: 6px; opacity: .78; }
.stage-toolbar {
  position: sticky; top: 68px; z-index: 25; padding: 10px 12px;
  border-radius: 16px; box-shadow: 0 10px 28px rgba(31, 71, 75, .13);
  background: rgba(255, 255, 255, .97); backdrop-filter: blur(14px);
}
.stage-toolbar-main { min-width: 0; }
.stage-toolbar-context { min-width: 170px; flex: 1 1 220px; }
.stage-toolbar-controls { flex: 0 1 auto; justify-content: flex-end; }
.stage-toolbar-actions {
  width: 100%; justify-content: flex-end; padding-top: 8px; margin-top: 2px;
  border-top: 1px solid var(--agir-border);
}
.stage-toolbar .q-btn { min-height: 38px; }
.stage-toolbar .stage-toolbar-help { min-width: 38px; width: 38px; padding: 0; }
.stage-toolbar .toolbar-stage-title {
  font-size: .8rem; line-height: 1.25; font-weight: 750; color: var(--agir-secondary);
}
.stage-toolbar-ai-label { white-space: nowrap; }
.toolbar-help-item { padding: 12px 14px; border-radius: 12px; }
.validation-result-link {
  width: 100%; min-height: 42px; justify-content: flex-start; text-align: left;
  border: 1px solid var(--agir-border); border-radius: 12px; background: #ffffff;
  padding: 9px 12px; box-shadow: 0 2px 7px rgba(31, 71, 75, .05);
}
.validation-result-link .q-btn__content {
  width: 100%; justify-content: flex-start; text-align: left; white-space: normal;
  line-height: 1.35;
}
.validation-result-link:hover { background: #f8fbfa; box-shadow: 0 4px 11px rgba(31, 71, 75, .09); }
.validation-results-list { width: 100%; gap: 8px; }
.validation-result-link.validation-issue { border-color: #e7aaa5; color: #8e2f2a; }
.validation-result-link.validation-suggestion { border-color: #9fc9c1; color: #245f5a; }
.validation-result-link.validation-pass { border-color: #8fc7a1; color: #176b38; }
.validation-focus-pulse { animation: validation-focus-pulse 1.8s ease-out; }
@keyframes validation-focus-pulse {
  0%, 35% {
    outline: 3px solid rgba(13, 118, 110, .55); outline-offset: 4px;
    box-shadow: 0 0 0 8px rgba(13, 118, 110, .14); border-radius: 10px;
  }
  100% {
    outline: 0 solid rgba(13, 118, 110, 0); outline-offset: 10px;
    box-shadow: 0 0 0 14px rgba(13, 118, 110, 0); border-radius: 10px;
  }
}
.artifact-card { min-width: 0; padding: 26px 30px; overflow-x: auto; }
.artifact-markdown.artifact-heading { width: auto; min-width: 0; flex: 1 1 420px; }
.artifact-heading h1 { margin: 0; }
.artifact-markdown { color: var(--agir-ink); line-height: 1.65; width: 100%; }
.artifact-markdown h1 { font-size: 1.65rem; margin: 0 0 .35rem; letter-spacing: -.025em; }
.artifact-markdown h2 { font-size: 1.08rem; margin-top: 1.8rem; color: var(--agir-secondary); }
.artifact-markdown table { min-width: 720px; width: 100%; border-collapse: separate; border-spacing: 0; font-size: .88rem; }
.artifact-markdown th { background: #eaf3f1; color: #244a50; text-align: left; }
.artifact-markdown th, .artifact-markdown td { border: 1px solid #d9e6e3; padding: 10px 12px; vertical-align: top; }
.manual-table-scroll { width: 100%; overflow-x: auto; }
.manual-table { min-width: 720px; width: 100%; border-collapse: collapse; }
.manual-table th { background: #eaf3f1; color: #244a50; font-size: .78rem; text-align: left; padding: 9px; border: 1px solid #d9e6e3; }
.manual-table td { min-width: 110px; padding: 4px; vertical-align: top; border: 1px solid #d9e6e3; background: white; }
.manual-table td.manual-row-action { min-width: 54px; width: 54px; text-align: center; }
.manual-table td.manual-row-actions { min-width: 126px; width: 126px; text-align: center; }
.manual-row-buttons { flex-wrap: nowrap; justify-content: center; gap: 0; }
.manual-table .q-field { min-width: 100px; }
.manual-table .manual-cell-long { min-width: 210px; }
.manual-table .manual-cell-number { min-width: 72px; }
.manual-table .q-field__control { min-height: 40px; }
.manual-table .q-field__native { line-height: 1.35; padding-top: 7px; padding-bottom: 7px; }
.manual-table td.ai-proposal-changed-cell { background: #eef9f6; }
.manual-table tr.ai-proposal-new-row td { background: #eef9f6; }
.manual-table tr.ai-proposal-remove-row td { background: #fff3f0; }
.decision-card { padding: 22px; }
.teacher-control-card { padding: 16px 18px; gap: 8px; }
.teacher-control-card .secondary-action { min-height: 38px; }
.resource-tabs { border-bottom: 1px solid var(--agir-border); }
.resource-tabs .q-tab { min-height: 48px; }
.resource-tab-panels { background: transparent !important; }
.resource-tab-panels .q-tab-panel { padding-top: 18px; }
.presentation-slides { gap: 10px; }
.presentation-slide {
  border: 1px solid var(--agir-border) !important;
  border-radius: 16px !important;
  background: #fbfdfc !important;
  overflow: hidden;
}
.presentation-slide .q-item { min-height: 58px; }
.presentation-slide .q-item__label { color: var(--agir-ink); font-weight: 750; }
.presentation-slide-grid {
  display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(220px, .6fr);
  gap: 12px; width: 100%;
}
.presentation-visual-card { padding: 16px; }
.presentation-image-preview {
  width: 100%; max-width: 360px; height: 190px;
  object-fit: contain; background: #f4f7fa; border-radius: 12px;
  border: 1px solid var(--agir-border);
}
.presentation-image-gallery {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px; width: 100%; max-height: 62vh; overflow-y: auto; padding: 2px;
}
.presentation-image-option { padding: 12px; min-width: 0; }
.presentation-image-option .q-img { height: 155px; background: #f4f7fa; border-radius: 10px; }
.presentation-view-table { min-width: 980px !important; }
.presentation-view-content { min-width: 220px; white-space: normal; }
.presentation-view-visual-cell { min-width: 150px; }
.presentation-mode-thumbnail {
  width: 132px; height: 82px; object-fit: contain; background: #f4f7fa;
  border: 1px solid var(--agir-border); border-radius: 9px; margin-bottom: 6px;
}
.consultation-card { padding: 20px 22px; }
.info-chip { background: var(--agir-primary) !important; color: #ffffff !important; font-weight: 700; }
.info-chip *, .info-chip .q-icon { color: #ffffff !important; }
.home-hero { padding: 34px; background: linear-gradient(145deg, #eef8f5, #ffffff); }
.home-feature { min-width: 0; padding: 22px; }
.final-hero { padding: 28px; color: white; background: linear-gradient(130deg, #0d766e, #184f60); border-radius: 22px; }
.complete-hero { padding: 34px; text-align: center; background: linear-gradient(145deg, #e8f6ef, #f7fbfa); }
.session-entry { width: 100%; border: 1px solid rgba(255,255,255,.12); border-radius: 14px; background: rgba(255,255,255,.06); }
.session-entry:hover { background: rgba(255,255,255,.11); }
.agir-drawer .session-entry,
.agir-drawer .session-entry * { color: #eef8f6 !important; }
.upload-list { min-height: 40px; }
.q-stepper { box-shadow: none !important; border: 0 !important; }
.q-stepper__header { border: 1px solid var(--agir-border); border-radius: 16px; background: #f8fbfa; }
.q-tab-panels { background: transparent !important; }
.q-table__container { border-radius: 15px; border: 1px solid var(--agir-border); box-shadow: none !important; }
.q-table th { background: #eaf3f1; color: #244a50; font-weight: 750; }

@media (max-width: 1050px) {
  .agir-main { padding: 22px 18px 64px; }
  .stage-toolbar { top: 64px; }
  .stage-toolbar-controls,
  .stage-toolbar-actions { justify-content: flex-start; flex-basis: 100%; }
}
@media (max-width: 640px) {
  .hero-title { font-size: 2.15rem; }
  .artifact-card { padding: 20px 16px; }
  .q-stepper__title { display: none; }
  .brand-mark { width: 38px; height: 38px; border-radius: 12px; }
  .header-brand-copy { margin-left: 2px !important; }
  .header-tagline { display: none; }
  .presentation-slide-grid { grid-template-columns: 1fr; }
  .stage-toolbar { top: 58px; padding: 9px; }
  .stage-toolbar-context { order: -1; flex-basis: 100%; }
  .stage-toolbar-controls,
  .stage-toolbar-actions { gap: 6px; }
  .stage-toolbar .q-btn:not(.stage-toolbar-help) { flex: 1 1 auto; }
}
"""


def _session_label(item: dict[str, str]) -> str:
    stage = STAGE_LABELS.get(item.get("current_stage", ""), "Sessão")
    return f"{item.get('unit_name', 'Sessão')} · {item.get('ai_provider', 'OpenAI')} · {stage}"


def _document_formats_for_export_choice(choice: str) -> tuple[str, ...]:
    if choice == "latex":
        return (DOCUMENT_FORMAT_LATEX,)
    if choice == "both":
        return (DOCUMENT_FORMAT_WORD, DOCUMENT_FORMAT_LATEX)
    return (DOCUMENT_FORMAT_WORD,)


def _export_choice_for_document_formats(value: Any) -> str:
    formats = {str(item) for item in (value or [])}
    if formats == {DOCUMENT_FORMAT_LATEX}:
        return "latex"
    if formats == {DOCUMENT_FORMAT_WORD, DOCUMENT_FORMAT_LATEX}:
        return "both"
    return "word"


class AGIRSoloInterface:
    """Interface de uma única ligação de utilizador."""

    def __init__(
        self,
        service: ApplicationService | None = None,
        identity: Identity | None = None,
    ) -> None:
        self.service = service or SERVICE
        self.identity = identity or Identity("LOCAL", "Utilizador local", "admin")
        self.state: dict[str, Any] | None = None
        self.viewed_stage: str | None = None
        self.manual_edit_stage: str | None = None
        self.manual_edit_artifact: Any = None
        self.manual_edit_stage_context: dict[str, Any] = {}
        self.uploaded_files: dict[str, bytes] = {}
        self.removed_source_files: set[str] = set()
        self.fields: dict[str, Any] = {}
        self.initial_hours_group: Any | None = None
        self.editing_initial_session = False
        self.initial_edit_baseline: dict[str, Any] | None = None
        self.export_document_format = "word"
        self.error_notification: Any | None = None
        self.busy_started_at: float | None = None
        self.busy_phase_started_at: float | None = None
        self.busy_phase_text = ""
        self.busy_updates: SimpleQueue[str] | None = None
        self._build()

    def _show_error(self, error: BaseException | str) -> None:
        self.error_notification = _replace_error_notification(
            self.error_notification,
            str(error),
        )

    def _build(self) -> None:
        ui.page_title(f"{APP_NAME} — {APP_TAGLINE}")
        ui.colors(primary="#0d766e", secondary="#1f5966", accent="#e8a23a")
        ui.add_css(APP_CSS)

        self._build_logout_dialog()
        self._build_busy_dialog()
        self._build_session_restore_dialog()

        with ui.header(elevated=False).classes("agir-header h-16 items-center px-3 md:px-6"):
            ui.button(icon="menu", on_click=lambda: self.drawer.toggle()).props(
                "flat round aria-label='Abrir navegação'"
            )
            ui.html('<div class="brand-mark">CI</div>')
            with ui.column().classes("header-brand-copy gap-0 ml-2"):
                ui.label(APP_NAME).classes("font-bold text-lg leading-tight")
                ui.label("Autoria pedagógica com IA").classes("header-tagline text-xs muted")
            ui.space()
            self.header_context = ui.label("Início").classes(
                "hidden md:block text-sm font-semibold muted"
            )
            ui.label(self.identity.display_name).classes(
                "hidden lg:block text-sm font-semibold muted"
            )
            ui.button(
                icon="logout",
                on_click=self.logout_dialog.open,
            ).props("flat round aria-label='Terminar sessão'")

        with ui.left_drawer(value=True, bordered=False).classes("agir-drawer p-4") as self.drawer:
            with ui.column().classes("w-full gap-5"):
                with ui.column().classes("gap-1 px-1 pt-2"):
                    ui.label("ESPAÇO DE TRABALHO").classes(
                        "text-xs tracking-widest opacity-60 font-bold"
                    )
                    ui.label("Sessões pedagógicas").classes("text-xl font-bold")
                ui.button(
                    "Página inicial",
                    icon="home",
                    on_click=self.show_home,
                ).props("flat color=white no-caps align=left").classes("w-full")
                ui.button(
                    "Iniciar nova sessão",
                    icon="add_circle",
                    on_click=self.show_new_session,
                ).props("unelevated color=white text-color=primary no-caps").classes(
                    "w-full primary-action"
                )
                ui.button(
                    "Restaurar cópia de segurança",
                    icon="upload_file",
                    on_click=self.open_session_restore_dialog,
                ).props("outline color=white no-caps align=left").classes(
                    "w-full"
                ).mark("open-session-restore")
                ui.separator().classes("opacity-20")
                with ui.row().classes("w-full items-center"):
                    ui.label("Sessões guardadas").classes("font-semibold")
                    ui.space()
                    ui.button(icon="refresh", on_click=self.refresh_sessions).props(
                        "flat round dense aria-label='Atualizar sessões'"
                    )
                self.session_list = ui.column().classes("w-full gap-2")
                self.refresh_sessions()
                ui.space()
                with ui.column().classes("gap-1 opacity-70 text-xs px-1"):
                    ui.label("Dados guardados de forma persistente")
                    ui.label(f"CoerIA v{APP_VERSION} · SQLite")

        with ui.column().classes("agir-main"):
            self.home_view = ui.column().classes("w-full gap-6")
            self.initial_view = ui.column().classes("w-full gap-6")
            self.workspace_view = ui.column().classes("w-full gap-5")

        with self.home_view:
            self._build_home_view()
        with self.initial_view:
            self._build_initial_view()
        self.initial_view.set_visibility(False)
        self.workspace_view.set_visibility(False)

    def _build_home_view(self) -> None:
        with ui.card().classes("surface home-hero w-full mt-4"):
            with ui.column().classes("gap-4 max-w-4xl"):
                ui.label("AUTORIA PEDAGÓGICA ORIENTADA").classes("eyebrow")
                ui.label(
                    "Construa uma unidade curricular coerente, do primeiro resultado aos recursos finais."
                ).classes("hero-title")
                ui.label(
                    "O CoerIA apoia o alinhamento entre resultados de aprendizagem, "
                    "conteúdos, atividades, avaliação e recursos, mantendo cada "
                    "decisão sob o controlo do docente."
                ).classes("hero-copy")
                with ui.row().classes("w-full gap-3 mt-2"):
                    start_session_button = ui.button(
                        "Iniciar nova sessão",
                        icon="play_arrow",
                        on_click=self.show_new_session,
                    ).props("unelevated no-caps size=lg icon-right").classes(
                        "primary-action px-6"
                    )
                    start_session_button.mark("start-new-session")

        with ui.grid(columns=3).classes("w-full gap-4 max-md:grid-cols-1"):
            for icon, title, description in (
                (
                    "account_tree",
                    "Percurso estruturado",
                    "Avance livremente pelas etapas com base na Taxonomia SOLO ou Bloom.",
                ),
                (
                    "edit_note",
                    "Controlo do docente",
                    "Preencha e edite todos os campos manualmente; a assistência por IA é opcional.",
                ),
                (
                    "inventory_2",
                    "Resultados utilizáveis",
                    "Exporte o programa e os recursos educativos produzidos no percurso.",
                ),
            ):
                with ui.card().classes("surface home-feature w-full"):
                    ui.icon(icon, color="primary", size="2rem")
                    ui.label(title).classes("section-title")
                    ui.label(description).classes("muted")

        ui.label(
            "Para retomar um trabalho, escolha uma sessão guardada no menu lateral."
        ).classes("text-sm muted")

    def _build_logout_dialog(self) -> None:
        with ui.dialog() as self.logout_dialog, ui.card().classes("p-5 w-96 max-w-full surface"):
            ui.icon("logout", size="2.2rem", color="primary")
            ui.label("Terminar sessão?").classes("section-title")
            ui.label(
                "As sessões já guardadas não serão perdidas. O CoerIA continuará disponível."
            ).classes("muted")
            with ui.row().classes("w-full justify-end mt-3"):
                ui.button("Cancelar", on_click=self.logout_dialog.close).props("flat no-caps")
                ui.button("Terminar sessão", on_click=self._logout).props(
                    "unelevated no-caps"
                )

    def _logout(self) -> None:
        if authentication_disabled():
            ui.navigate.to("/")
            return
        app.storage.user.clear()
        ui.navigate.to("/login")

    def _build_busy_dialog(self) -> None:
        with ui.dialog().props("persistent") as self.busy_dialog:
            with ui.card().classes(
                "items-center p-8 gap-4 surface w-96 max-w-full"
            ):
                ui.spinner("dots", size="3.2rem", color="primary")
                self.busy_label = ui.label("A preparar a proposta…").classes(
                    "font-semibold text-center"
                )
                self.busy_detail = ui.label("Processamento em curso…").classes(
                    "text-sm muted text-center"
                )
                self.busy_elapsed = ui.label("Tempo decorrido: 0 s").classes(
                    "text-xs muted text-center"
                )
        self.busy_timer = ui.timer(
            1.0,
            self._update_busy_progress,
            active=False,
        )

    def _build_initial_view(self) -> None:
        with ui.column().classes("gap-2 pt-4"):
            self.initial_eyebrow = ui.label("NOVA SESSÃO PEDAGÓGICA").classes("eyebrow")
            self.initial_title = ui.label("Configure o ponto de partida").classes(
                "text-3xl font-extrabold tracking-tight"
            )
            self.initial_copy = ui.label(
                "Indique o contexto, as fontes e a caracterização da unidade "
                "curricular antes de criar a sessão."
            ).classes("muted")

        self.initial_stage_track = ui.column().classes("w-full")

        with ui.card().classes(
            "stage-toolbar surface w-full"
        ) as self.initial_stage_toolbar:
            self.initial_stage_toolbar.mark("stage-toolbar", "initial-stage-toolbar")
            with ui.row().classes(
                "stage-toolbar-main w-full items-center gap-2 flex-wrap"
            ):
                ui.button("Etapa anterior", icon="arrow_back").props(
                    "outline no-caps disable"
                ).classes("secondary-action")
                with ui.column().classes("stage-toolbar-context gap-0 px-1"):
                    ui.label(f"ETAPA 01 DE {DISPLAY_STAGE_COUNT:02d}").classes(
                        "eyebrow"
                    )
                    ui.label("Dados iniciais").classes("toolbar-stage-title")
                ui.button(
                    "Etapa seguinte",
                    icon="arrow_forward",
                    on_click=self._handle_initial_toolbar_next,
                ).props("unelevated no-caps icon-right").classes("primary-action")
                with ui.row().classes(
                    "stage-toolbar-controls items-center gap-2 flex-wrap"
                ):
                    ui.button(
                        "Validar dados",
                        icon="fact_check",
                        on_click=self.handle_validate_initial,
                    ).props("outline no-caps").classes("secondary-action").mark(
                        "validate-initial-data"
                    )
                    self._render_toolbar_help_button("initial")

                with ui.row().classes(
                    "stage-toolbar-actions items-center gap-2 flex-wrap"
                ):
                    ui.label("ASSISTÊNCIA COM IA").classes(
                        "eyebrow stage-toolbar-ai-label"
                    )
                    ui.button(
                        "Gerar proposta inicial por IA",
                        icon="auto_awesome",
                        on_click=self.handle_generate_initial,
                    ).props("outline no-caps").classes("secondary-action").mark(
                        "generate-initial-with-ai"
                    )

        with ui.card().classes("surface w-full p-5 md:p-6") as provider_card:
            provider_card.mark("new-session-provider")
            ui.label("Fornecedor de IA").classes("text-sm font-semibold")
            self.fields["ai_provider"] = ui.toggle(
                list(AI_PROVIDER_CHOICES),
                value=configured_ai_provider(),
            ).props("spread no-caps").classes("full-control max-w-xl")
            ui.label(
                "A escolha é exclusiva, fica associada à sessão e só é usada "
                "quando solicitar assistência por IA."
            ).classes("text-xs muted")
            self.assistance_status = ui.column().classes(
                "soft-surface w-full p-4 mt-3"
            )
            self.assistance_status.mark("initial-validation-results")
            self.assistance_status.set_visibility(False)

        with ui.card().classes("surface w-full p-5 md:p-7") as form_card:
            form_card.mark("new-session-form")
            self._build_context_step()
            ui.separator().classes("my-5")
            self._build_sources_step()
            ui.separator().classes("my-5")
            self._build_characterization_step()
            with ui.row().classes("w-full justify-between items-center gap-3 mt-6"):
                self.cancel_initial_edit_button = ui.button(
                    "Cancelar e voltar à sessão",
                    icon="arrow_back",
                    on_click=self.cancel_initial_session_edit,
                ).props("outline no-caps").classes("secondary-action")
                self.cancel_initial_edit_button.mark("cancel-initial-session-edit")
                self.cancel_initial_edit_button.set_visibility(False)
                ui.space()
                self.create_session_button = ui.button(
                    "Iniciar desenho curricular alinhado",
                    icon="play_arrow",
                    on_click=self.handle_start_session,
                ).props("unelevated no-caps size=lg icon-right").classes(
                    "primary-action px-6"
                )
                self.create_session_button.mark("create-pedagogical-session")

    def _build_context_step(self) -> None:
        ui.label("Identificação e opções pedagógicas").classes("section-title mb-3")
        with ui.grid(columns=2).classes("w-full gap-4 max-md:grid-cols-1"):
            self.fields["unit_name"] = ui.input(
                "Nome da unidade curricular ou ação de formação",
                placeholder="Ex.: Introdução às Pescas",
            ).classes("full-control")
        ui.label("Taxonomia dos resultados de aprendizagem").classes(
            "text-sm font-semibold mt-4"
        )
        self.fields["taxonomy_type"] = ui.toggle(
            list(TAXONOMY_CHOICES),
            value="SOLO",
        ).props("spread no-caps").classes("full-control max-w-xl")
        self.fields["general_aims"] = ui.textarea(
            "Objetivos gerais (opcional)",
            placeholder=(
                "Indique, em termos amplos, a finalidade da unidade curricular. "
                "Não formule aqui os resultados de aprendizagem."
            ),
        ).props("outlined autogrow").classes("full-control mt-4")
        self.fields["general_aims"].mark("initial-general-aims")
        ui.label(
            "Este enquadramento orienta a formulação posterior dos resultados, mas "
            "não participa diretamente nas ligações do alinhamento."
        ).classes("text-xs muted")

    def _build_sources_step(self) -> None:
        ui.label("Texto de base e fontes de referência").classes("section-title")
        ui.label(
            "Pode combinar texto direto com documentos. Os ficheiros são "
            "processados quando iniciar o desenho curricular ou guardar alterações iniciais."
        ).classes("muted mb-3")
        self.fields["source_text"] = ui.textarea(
            "Informação de referência para a unidade curricular",
            placeholder=(
                "Introduza uma descrição da unidade curricular, temas preliminares, "
                "orientações ou um programa existente."
            ),
        ).props("outlined autogrow input-style='min-height: 190px'").classes("full-control")
        ui.label(
            "Os conteúdos programáticos formais serão definidos posteriormente, "
            "em função dos resultados de aprendizagem."
        ).classes("text-xs muted")
        self.existing_sources_notice = ui.label(
            "As fontes documentais já incorporadas serão preservadas. Pode adicionar "
            "novos ficheiros abaixo."
        ).classes("text-xs text-primary font-semibold mt-2")
        self.existing_sources_notice.set_visibility(False)
        accepted = ",".join(sorted(SUPPORTED_SOURCE_SUFFIXES))
        maximum_file_bytes = configured_max_file_bytes()
        maximum_total_bytes = configured_max_total_upload_bytes()
        self.uploader = ui.upload(
            label="Adicionar ficheiros de apoio",
            multiple=True,
            auto_upload=True,
            max_file_size=maximum_file_bytes,
            max_total_size=maximum_total_bytes,
            on_upload=self.handle_upload,
            on_rejected=lambda: ui.notify(
                "Um ficheiro excede o limite permitido.",
                type="warning",
            ),
        ).props(f"accept={accepted} flat bordered").classes("w-full mt-4")
        self.upload_list = ui.row().classes("upload-list w-full gap-2 mt-2")
        self.render_upload_list()
        ui.label(
            "Formatos aceites: "
            + ", ".join(sorted(SUPPORTED_SOURCE_SUFFIXES))
            + f" · máximo {maximum_file_bytes // (1024 * 1024)} MB por ficheiro"
        ).classes("text-xs muted")

    def _build_characterization_step(self) -> None:
        ui.label("Caracterização da unidade curricular").classes("section-title mb-3")
        with ui.grid(columns=4).classes("w-full gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1"):
            self.fields["program_name"] = ui.input(
                "Curso ou programa em que se integra",
                placeholder="Ex.: Licenciatura em Biologia",
            ).classes("full-control")
            self.fields["program_type"] = ui.select(
                ["CTeSP/CET", "Licenciatura", "Mestrado", "Outra"],
                label="Tipo de formação",
                with_input=True,
                new_value_mode="add-unique",
                clearable=True,
            ).classes("full-control")
            self.fields["academic_year"] = ui.input(
                "Ano curricular", placeholder="Ex.: 1.º ano"
            ).classes("full-control")
            self.fields["semester"] = ui.select(
                list(SEMESTER_OPTIONS),
                label="Semestre",
                value=SEMESTER_OPTIONS[0],
            ).classes("full-control")
            def update_cnaef_name(event: Any) -> None:
                code = str(event.value or "")
                name_control = self.fields.get("cnaef_name")
                if name_control is not None:
                    name_control.set_value(
                        CNAEF_CATALOG.get(code, "")
                    )

            self.fields["cnaef_code"] = ui.select(
                cnaef_options(),
                label="Código CNAEF",
                with_input=True,
                clearable=True,
                on_change=update_cnaef_name,
            ).props(
                "options-dense",
                remove="hide-selected fill-input",
            ).classes("full-control")
            self.fields["cnaef_code"].add_slot(
                "selected-item",
                """
                <span>{{ String(props.opt.label).split(' — ')[0] }}</span>
                """,
            )
            self.fields["cnaef_name"] = ui.input(
                "Área CNAEF"
            ).props("readonly").classes("full-control")

            def update_isced_name(event: Any) -> None:
                code = str(event.value or "")
                name_control = self.fields.get("isced_f_name")
                if name_control is not None:
                    name_control.set_value(
                        ISCED_F_CATALOG.get(code, "")
                    )

            self.fields["isced_f_code"] = ui.select(
                isced_f_options(),
                label="Código ISCED-F",
                with_input=True,
                clearable=True,
                on_change=update_isced_name,
            ).props(
                "options-dense",
                remove="hide-selected fill-input",
            ).classes("full-control")
            self.fields["isced_f_code"].add_slot(
                "selected-item",
                """
                <span>{{ String(props.opt.label).split(' — ')[0] }}</span>
                """,
            )
            self.fields["isced_f_name"] = ui.input(
                "Área ISCED-F"
            ).props("readonly").classes("full-control")
            self.fields["ects_credits"] = ui.number(
                "ECTS", value=0, min=0, precision=1
            ).classes("full-control")
            with ui.element("div").classes(
                "col-span-2 grid grid-cols-2 gap-4 max-sm:grid-cols-1"
            ) as self.initial_hours_group:
                self.initial_hours_group.mark("initial-hours-group")
                self.fields["contact_hours"] = ui.number(
                    "Horas de contacto", value=0, min=0, precision=1
                ).classes("full-control")
                self.fields["autonomous_hours"] = ui.number(
                    "Trabalho autónomo", value=0, min=0, precision=1
                ).classes("full-control")
        self.fields["bibliography"] = ui.textarea(
            "Bibliografia fornecida ou validada pelo docente",
            placeholder=(
                "Uma referência por linha. O CoerIA não inventa referências "
                "bibliográficas para o programa da UC."
            ),
        ).props("outlined autogrow").classes("full-control mt-3")

    async def handle_upload(self, event: events.UploadEventArguments) -> None:
        self.uploaded_files[event.file.name] = await event.file.read()
        self.render_upload_list()
        ui.notify(f"{event.file.name} adicionado.", type="positive")

    def render_upload_list(self) -> None:
        self.upload_list.clear()
        with self.upload_list:
            existing_files = (
                self.service.restored_source_file_names(self.state)
                if self.editing_initial_session and self.state
                else []
            )
            if not existing_files and not self.uploaded_files:
                ui.label("Nenhum ficheiro adicionado.").classes("text-sm muted")
                return
            for filename in existing_files:
                removed = filename in self.removed_source_files
                prefix, separator, remainder = filename.partition("_")
                display_filename = (
                    remainder if separator and len(prefix) == 2 and prefix.isdigit() else filename
                )
                with ui.chip(icon="undo" if removed else "description").classes(
                    "info-chip" if not removed else "bg-grey-6 text-white"
                ):
                    ui.label(
                        f"{display_filename} — será removido"
                        if removed
                        else f"Incorporado: {display_filename}"
                    )
                    source_action = ui.button(
                        icon="undo" if removed else "close",
                        on_click=lambda _e, name=filename, is_removed=removed: (
                            self.restore_existing_source(name)
                            if is_removed
                            else self.remove_existing_source(name)
                        ),
                    ).props(
                        "flat round dense size=sm "
                        + (
                            "aria-label='Manter ficheiro incorporado'"
                            if removed
                            else "aria-label='Remover ficheiro incorporado'"
                        )
                    )
                    source_action.mark("toggle-existing-source")
            for filename in self.uploaded_files:
                with ui.chip(icon="description").classes("info-chip"):
                    ui.label(filename)
                    ui.button(
                        icon="close",
                        on_click=lambda _e, name=filename: self.remove_upload(name),
                    ).props("flat round dense size=sm aria-label='Remover ficheiro'")

    def remove_upload(self, filename: str) -> None:
        self.uploaded_files.pop(filename, None)
        self.render_upload_list()

    def remove_existing_source(self, filename: str) -> None:
        self.removed_source_files.add(filename)
        self.render_upload_list()

    def restore_existing_source(self, filename: str) -> None:
        self.removed_source_files.discard(filename)
        self.render_upload_list()

    def _form_data(self) -> dict[str, Any]:
        data = {name: element.value for name, element in self.fields.items()}
        data["audience"] = str(data.get("program_type", "") or "Ensino superior")
        for key in ("ects_credits", "contact_hours", "autonomous_hours"):
            data[key] = float(data.get(key, 0) or 0)
        data["duration_hours"] = (
            data["contact_hours"] + data["autonomous_hours"]
        )
        data["resource_types"] = [RESOURCE_PRESENTATION]
        data["ai_image_generation_enabled"] = True
        return data

    def _set_form_data(self, data: dict[str, Any]) -> None:
        for name, element in self.fields.items():
            if name in data:
                value = data[name]
                if name == "semester" and value not in SEMESTER_OPTIONS:
                    value = SEMESTER_OPTIONS[0]
                if name == "cnaef_code" and str(value or "") not in CNAEF_CATALOG:
                    value = None
                if name == "cnaef_name":
                    value = CNAEF_CATALOG.get(
                        str(data.get("cnaef_code", "") or ""),
                        "",
                    )
                if name == "isced_f_code" and str(value or "") not in ISCED_F_CATALOG:
                    value = None
                if name == "isced_f_name":
                    value = ISCED_F_CATALOG.get(
                        str(data.get("isced_f_code", "") or ""),
                        "",
                    )
                element.set_value(value)

    async def _scroll_and_highlight(
        self,
        selector: str,
        *,
        activate_selector: str = "",
    ) -> None:
        script = f"""
        (() => new Promise(resolve => {{
          const deadline = Date.now() + 1800;
          const activateSelector = {json.dumps(activate_selector)};
          const activate = activateSelector
            ? document.querySelector(activateSelector)
            : null;
          if (activate && !activate.classList.contains('q-tab--active')) {{
            activate.click();
          }}
          const locate = () => {{
            const root = document.querySelector({json.dumps(selector)});
            if (!root) {{
              if (Date.now() < deadline) {{
                window.requestAnimationFrame(locate);
                return;
              }}
              resolve(false);
              return;
            }}
            root.scrollIntoView({{behavior: 'smooth', block: 'center'}});
            root.classList.remove('validation-focus-pulse');
            void root.offsetWidth;
            root.classList.add('validation-focus-pulse');
            window.setTimeout(
              () => root.classList.remove('validation-focus-pulse'),
              1900,
            );
            resolve(true);
          }};
          locate();
        }}))()
        """
        await ui.run_javascript(script, timeout=3.0)

    async def _arm_scroll_and_highlight(
        self,
        selector: str,
        *,
        activate_selector: str = "",
    ) -> None:
        """Prepara o realce antes de uma mudança de etapa substituir o DOM."""

        script = f"""
        (() => {{
          const deadline = Date.now() + 5000;
          const selector = {json.dumps(selector)};
          const activateSelector = {json.dumps(activate_selector)};
          const locate = () => {{
            const activate = activateSelector
              ? document.querySelector(activateSelector)
              : null;
            if (activate && !activate.classList.contains('q-tab--active')) {{
              activate.click();
            }}
            const target = document.querySelector(selector);
            if (!target) {{
              if (Date.now() < deadline) window.requestAnimationFrame(locate);
              return;
            }}
            target.scrollIntoView({{behavior: 'smooth', block: 'center'}});
            target.classList.remove('validation-focus-pulse');
            void target.offsetWidth;
            target.classList.add('validation-focus-pulse');
            window.setTimeout(
              () => target.classList.remove('validation-focus-pulse'),
              1900,
            );
          }};
          window.requestAnimationFrame(locate);
          return true;
        }})()
        """
        await ui.run_javascript(script, timeout=1.0)

    async def _focus_initial_result(self, target: str) -> None:
        if target == "duration_hours" and self.initial_hours_group is not None:
            await self._scroll_and_highlight(f"#c{self.initial_hours_group.id}")
            return
        field_name = target
        element = self.fields.get(field_name)
        if element is None:
            return
        await self._scroll_and_highlight(f"#c{element.id}")

    @staticmethod
    def _render_validation_result_button(
        message: str,
        kind: str,
        marker: str,
        on_click: Any,
    ) -> None:
        icons = {
            "issue": "error_outline",
            "suggestion": "lightbulb",
            "pass": "check_circle",
        }
        ui.button(
            message,
            icon=icons.get(kind, "info_outline"),
            on_click=on_click,
        ).props("flat no-caps align=left").classes(
            f"validation-result-link validation-{kind}"
        ).mark(marker)

    def _render_initial_validation(self, result: dict[str, Any]) -> None:
        self.assistance_status.clear()
        with self.assistance_status:
            ui.label("VALIDAÇÃO DO PREENCHIMENTO").classes("eyebrow")
            ui.label(
                "Os campos obrigatórios estão prontos para iniciar a sessão."
                if result["valid"]
                else "Existem campos obrigatórios a corrigir."
            ).classes("font-semibold")
            results = result.get("results", [])
            if results:
                ui.label(
                    "Selecione uma observação para localizar o campo correspondente."
                ).classes("text-xs muted")
            if results:
                with ui.column().classes("validation-results-list"):
                    for index, item in enumerate(results):
                        kind = str(item.get("kind", "suggestion"))
                        self._render_validation_result_button(
                            str(item.get("message", "")),
                            kind,
                            f"initial-validation-result-{index}",
                            lambda target=str(item.get("target", "")): (
                                self._focus_initial_result(target)
                            ),
                        )
        self.assistance_status.set_visibility(True)

    def _render_initial_assistance_message(self, title: str, message: str) -> None:
        self.assistance_status.clear()
        with self.assistance_status:
            ui.label(title.upper()).classes("eyebrow")
            ui.label(message).classes("text-sm")
        self.assistance_status.set_visibility(True)

    async def handle_validate_initial(self) -> None:
        result = self.service.validate_initial_form(self._form_data())
        self._render_initial_validation(result)
        await self._scroll_and_highlight(f"#c{self.assistance_status.id}")

    async def handle_generate_initial(self) -> None:
        self._show_busy("A IA está a completar os campos vazios…")
        try:
            proposal = await run.io_bound(
                self.service.propose_initial_form,
                self._form_data(),
            )
            self._set_form_data(proposal)
            self._render_initial_assistance_message(
                "Proposta inicial gerada",
                str(proposal.get("explanation", ""))
                + " Revise os campos antes de iniciar a sessão.",
            )
            ui.notify("Proposta inicial preenchida.", type="positive")
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    async def handle_start_session(self) -> None:
        await self._save_initial_session()

    async def _save_initial_session(self, target_stage: str | None = None) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        self._show_busy(
            (
                "A guardar as alterações aos dados iniciais…"
                if self.editing_initial_session
                else "A criar a sessão de autoria manual…"
            ),
            progress_updates,
            "A preparar localmente os dados e as fontes…",
        )
        try:
            with TemporaryDirectory(prefix="coeria_fontes_") as temporary_directory:
                source_paths: list[str] = []
                for index, (filename, content) in enumerate(self.uploaded_files.items()):
                    safe_name = Path(filename).name
                    path = Path(temporary_directory) / f"{index:02d}_{safe_name}"
                    path.write_bytes(content)
                    source_paths.append(str(path))
                if self.editing_initial_session:
                    self.state = await run.io_bound(
                        self.service.update_session_initial_data,
                        self.state,
                        self._form_data(),
                        source_paths,
                        sorted(self.removed_source_files),
                        progress_updates.put,
                    )
                else:
                    self.state = await run.io_bound(
                        self.service.start_session,
                        self._form_data(),
                        source_paths,
                        progress_updates.put,
                    )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            editing_existing = self.editing_initial_session
            self.uploaded_files.clear()
            self.removed_source_files.clear()
            self.uploader.reset()
            self.render_upload_list()
            self.initial_edit_baseline = None
            if editing_existing and target_stage:
                await self._leave_initial_editor_for_stage(
                    target_stage,
                    notice=(
                        "Dados iniciais guardados. As etapas afetadas ficaram "
                        "assinaladas para revisão."
                    ),
                )
            else:
                self.editing_initial_session = False
                self.show_workspace(
                    "Dados iniciais atualizados. O conteúdo existente foi preservado e as "
                    "etapas afetadas ficaram assinaladas para revisão, quando aplicável."
                    if editing_existing
                    else "Sessão iniciada sem executar a IA. Pode editar ou abrir qualquer etapa."
                )
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    def _show_busy(
        self,
        message: str,
        progress_updates: SimpleQueue[str] | None = None,
        detail: str = "Processamento em curso…",
    ) -> None:
        started_at = monotonic()
        self.busy_started_at = started_at
        self.busy_phase_started_at = started_at
        self.busy_phase_text = detail
        self.busy_updates = progress_updates
        self.busy_label.set_text(message)
        self.busy_detail.set_text(detail)
        self.busy_elapsed.set_text("Tempo decorrido: 0 s")
        self.busy_timer.active = True
        self.busy_dialog.open()

    def _update_busy_progress(self) -> None:
        if self.busy_started_at is None:
            return
        now = monotonic()
        latest_update: str | None = None
        if self.busy_updates is not None:
            while True:
                try:
                    latest_update = self.busy_updates.get_nowait()
                except Empty:
                    break
        if latest_update is not None:
            self.busy_phase_text = latest_update
            self.busy_phase_started_at = now
        phase_started_at = self.busy_phase_started_at or self.busy_started_at
        self.busy_detail.set_text(
            _busy_phase_message(
                self.busy_phase_text,
                now - phase_started_at,
            )
        )
        self.busy_elapsed.set_text(
            _format_elapsed_duration(now - self.busy_started_at)
        )

    def _hide_busy(self) -> None:
        self._update_busy_progress()
        self.busy_timer.active = False
        self.busy_started_at = None
        self.busy_phase_started_at = None
        self.busy_phase_text = ""
        self.busy_updates = None
        self.busy_dialog.close()

    def show_home(self) -> None:
        self._set_initial_view_mode(False)
        self.initial_edit_baseline = None
        self.state = None
        self.viewed_stage = None
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.header_context.set_text("Início")
        self.initial_view.set_visibility(False)
        self.workspace_view.set_visibility(False)
        self.home_view.set_visibility(True)
        self.drawer.hide()

    def show_new_session(self) -> None:
        self.state = None
        self._set_initial_view_mode(False)
        self.initial_edit_baseline = None
        self.viewed_stage = None
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.export_document_format = "word"
        self._set_form_data(
            {
                "unit_name": "",
                "ai_provider": configured_ai_provider(),
                "taxonomy_type": "SOLO",
                "source_text": "",
                "general_aims": "",
                "program_name": "",
                "program_type": None,
                "academic_year": "",
                "semester": SEMESTER_OPTIONS[0],
                "cnaef_code": "",
                "cnaef_name": "",
                "isced_f_code": "",
                "isced_f_name": "",
                "ects_credits": 0,
                "contact_hours": 0,
                "autonomous_hours": 0,
                "bibliography": "",
            }
        )
        self.uploaded_files.clear()
        self.removed_source_files.clear()
        self.uploader.reset()
        self.render_upload_list()
        self.assistance_status.set_visibility(False)
        self.header_context.set_text("Nova sessão")
        self.home_view.set_visibility(False)
        self.workspace_view.set_visibility(False)
        self.initial_view.set_visibility(True)
        self.drawer.hide()

    async def _handle_initial_toolbar_next(self) -> None:
        if self.editing_initial_session:
            await self._request_initial_stage_navigation(STAGE_ORDER[0])
            return
        await self.handle_start_session()

    def _set_initial_view_mode(self, editing: bool) -> None:
        self.editing_initial_session = editing
        if not hasattr(self, "create_session_button"):
            return
        self.initial_eyebrow.set_text("01 · DADOS INICIAIS")
        self.initial_title.set_text(
            "Reveja o ponto de partida" if editing else "Configure o ponto de partida"
        )
        self.initial_copy.set_text(
            (
                "Altere a identificação, as fontes ou a caracterização. O trabalho já "
                "produzido será preservado e assinalado para revisão."
            )
            if editing
            else (
                "Indique o contexto, as fontes e a caracterização da unidade curricular "
                "antes de criar a sessão."
            )
        )
        self.create_session_button.set_text(
            "Guardar alterações iniciais"
            if editing
            else "Iniciar desenho curricular alinhado"
        )
        self.initial_stage_toolbar.set_visibility(True)
        self.cancel_initial_edit_button.set_visibility(editing)
        self.existing_sources_notice.set_visibility(editing)
        self._render_initial_view_stage_track()

    def _render_initial_data_track_item(
        self,
        *,
        current: bool,
        selectable: bool,
        status: str,
        status_label: str,
    ) -> None:
        status_class = _stage_status_css_class(status)
        item = ui.element("button" if selectable else "div").classes(
            f"stage-item {status_class}"
            + (" current" if current else "")
            + (" selectable" if selectable else "")
        )
        item.mark(
            f"manual-stage-{INITIAL_DATA_STAGE}",
            "edit-initial-session-data",
            status_class,
        )
        if selectable:
            item.props("type=button")
            item.on("click", self.show_initial_session_editor)
        with item:
            ui.label("01").classes("stage-number")
            ui.label(INITIAL_DATA_LABEL).classes("stage-label")
            ui.label(status_label).classes("stage-state")

    def _render_initial_view_stage_track(self) -> None:
        if not hasattr(self, "initial_stage_track"):
            return
        self.initial_stage_track.clear()
        state = self.state or {}
        statuses = state.get("stage_statuses", {})
        status_labels = {
            "draft": "Rascunho",
            "empty": "Por preencher",
            "needs_review": "Rever após alterações anteriores",
            "checked": "Verificação executada",
            "approved": "Concluído",
            "pending": "Por verificar",
            "stale": "Desatualizado",
            "awaiting_review": "Em validação",
            "generating": "A gerar",
        }
        with self.initial_stage_track:
            with ui.element("div").classes("stage-track").style(
                f"--stage-count: {DISPLAY_STAGE_COUNT}"
            ):
                self._render_initial_data_track_item(
                    current=True,
                    selectable=False,
                    status="draft",
                    status_label=(
                        "Ponto atual · Em edição"
                        if self.editing_initial_session
                        else "Ponto atual · Por preencher"
                    ),
                )
                for index, stage in enumerate(STAGE_ORDER, start=2):
                    stored_status = statuses.get(stage, "pending")
                    status_class = _stage_status_css_class(stored_status)
                    selectable = bool(
                        self.editing_initial_session
                        and state
                        and state.get("status") != "completed"
                    )
                    if selectable and not is_manual_first(state):
                        current_stage = state.get("current_stage")
                        selectable = stage == current_stage or stage in set(
                            revision_targets_for_state(state)
                        )
                    item = ui.element("button" if selectable else "div").classes(
                        f"stage-item {status_class}"
                        + (" selectable" if selectable else "")
                    )
                    item.mark(f"manual-stage-{stage}", status_class)
                    if selectable:
                        item.props("type=button")
                        item.on(
                            "click",
                            lambda _event, selected_stage=stage: (
                                self._request_initial_stage_navigation(selected_stage)
                            ),
                        )
                    with item:
                        ui.label(f"{index:02d}").classes("stage-number")
                        ui.label(STAGE_LABELS[stage]).classes("stage-label")
                        ui.label(
                            status_labels.get(stored_status, str(stored_status))
                        ).classes("stage-state")

    def show_initial_session_editor(self) -> None:
        if not self.state:
            return
        if self.state.get("status") == "completed":
            self._show_error(
                ValueError(
                    "A sessão concluída está em modo de consulta. Reabra-a "
                    "explicitamente antes de editar os dados iniciais."
                )
            )
            return
        self._set_initial_view_mode(True)
        self._set_form_data(self.service.restored_initial_fields(self.state))
        self.uploaded_files.clear()
        self.removed_source_files.clear()
        self.uploader.reset()
        self.render_upload_list()
        self.initial_edit_baseline = self._initial_edit_signature()
        self.assistance_status.set_visibility(False)
        self.header_context.set_text(
            f"{self.state.get('course', {}).get('unit_name', 'Sessão')} · Dados iniciais"
        )
        self.home_view.set_visibility(False)
        self.workspace_view.set_visibility(False)
        self.initial_view.set_visibility(True)
        self.drawer.hide()

    def cancel_initial_session_edit(self) -> None:
        if not self.state:
            self.show_home()
            return
        self.uploaded_files.clear()
        self.removed_source_files.clear()
        self.uploader.reset()
        self.render_upload_list()
        self.initial_edit_baseline = None
        self._set_initial_view_mode(False)
        self.show_workspace("Alterações aos dados iniciais canceladas.")

    def _initial_edit_signature(self) -> dict[str, Any]:
        """Representa os dados editáveis para detetar alterações por guardar."""

        return {
            "form": self._form_data(),
            "uploaded_files": sorted(self.uploaded_files),
            "removed_source_files": sorted(self.removed_source_files),
        }

    def _has_unsaved_initial_changes(self) -> bool:
        return bool(
            self.editing_initial_session
            and self.initial_edit_baseline is not None
            and self._initial_edit_signature() != self.initial_edit_baseline
        )

    async def _request_initial_stage_navigation(self, target_stage: str) -> None:
        if not self.state or target_stage not in STAGE_ORDER:
            return
        if self._has_unsaved_initial_changes():
            self._open_initial_navigation_dialog(target_stage)
            return
        await self._leave_initial_editor_for_stage(target_stage)

    def _open_initial_navigation_dialog(self, target_stage: str) -> None:
        with ui.dialog().props("persistent") as dialog, ui.card().classes(
            "w-full max-w-2xl p-6 gap-4"
        ):
            ui.label("ALTERAÇÕES POR GUARDAR").classes("eyebrow")
            ui.label("Guardar antes de mudar de etapa?").classes("section-title")
            ui.label(
                "Existem alterações nos dados iniciais. Para abrir "
                f"«{STAGE_LABELS[target_stage]}», "
                "guarde-as ou descarte-as explicitamente."
            ).classes("text-sm")

            async def discard_and_continue() -> None:
                dialog.close()
                await self._leave_initial_editor_for_stage(
                    target_stage,
                    notice="Alterações aos dados iniciais descartadas.",
                )

            async def save_and_continue() -> None:
                dialog.close()
                await self._save_initial_session(target_stage=target_stage)

            with ui.row().classes("w-full justify-end gap-2 flex-wrap"):
                ui.button("Continuar a editar", on_click=dialog.close).props(
                    "flat no-caps"
                )
                ui.button(
                    "Descartar alterações",
                    icon="delete_outline",
                    on_click=discard_and_continue,
                ).props("outline no-caps color=negative").mark(
                    "discard-initial-changes"
                )
                ui.button(
                    "Guardar e continuar",
                    icon="save",
                    on_click=save_and_continue,
                ).props("unelevated no-caps").classes("primary-action").mark(
                    "save-initial-and-continue"
                )
        dialog.open()

    async def _leave_initial_editor_for_stage(
        self,
        target_stage: str,
        *,
        notice: str = "",
    ) -> None:
        if not self.state or target_stage not in STAGE_ORDER:
            return
        self.uploaded_files.clear()
        self.removed_source_files.clear()
        self.uploader.reset()
        self.initial_edit_baseline = None
        self.editing_initial_session = False
        if is_manual_first(self.state):
            await self._navigate_manual_stage(target_stage, notice=notice)
            return

        self.viewed_stage = (
            None if target_stage == self.state.get("current_stage") else target_stage
        )
        message = f"Etapa aberta: {STAGE_LABELS[target_stage]}."
        if self.viewed_stage:
            message = (
                "Etapa aberta apenas para consulta. A sessão e os passos seguintes "
                "permanecem inalterados."
            )
        self.show_workspace(" ".join(part for part in (notice, message) if part))

    def refresh_sessions(self) -> None:
        self.session_list.clear()
        sessions = self.service.list_sessions()
        with self.session_list:
            if not sessions:
                ui.label("Ainda não existem sessões.").classes("text-sm opacity-60")
                return
            for item in sessions:
                session_id = item["session_id"]
                unit_name = item.get("unit_name", "Sessão sem título")

                async def load_selected(_event=None, selected_id=session_id) -> None:
                    await self.handle_load_session(selected_id)

                def delete_selected(
                    _event=None,
                    selected_id=session_id,
                    selected_name=unit_name,
                ) -> None:
                    self.open_delete_session_dialog(selected_id, selected_name)

                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    with ui.button(on_click=load_selected).props(
                        "flat no-caps align=left"
                    ).classes("session-entry p-2").style(
                        "flex: 1 1 auto; width: auto; min-width: 0"
                    ):
                        with ui.column().classes("items-start gap-0 text-left"):
                            ui.label(unit_name).classes("font-semibold text-sm")
                            ui.label(
                                f"{item.get('ai_provider', 'OpenAI')} · "
                                f"{STAGE_LABELS.get(item.get('current_stage', ''), 'Sessão')}"
                            ).classes("text-xs opacity-65")
                    ui.button(
                        icon="download",
                        on_click=lambda _event=None, selected_id=session_id: (
                            self.handle_backup_session(selected_id)
                        ),
                    ).props(
                        "flat round dense aria-label='Descarregar cópia de segurança'"
                    ).tooltip("Descarregar cópia de segurança").mark(
                        "backup-session"
                    )
                    ui.button(
                        icon="delete_outline",
                        on_click=delete_selected,
                    ).props(
                        "flat round dense color=negative "
                        "aria-label='Eliminar sessão'"
                    ).tooltip("Eliminar sessão")

    def _build_session_restore_dialog(self) -> None:
        maximum_backup_bytes = configured_session_backup_max_bytes()
        maximum_backup_mb = maximum_backup_bytes // (1024 * 1024)
        with ui.dialog() as self.session_restore_dialog, ui.card().classes(
            "p-6 w-full max-w-xl gap-4 surface"
        ):
            ui.label("CÓPIA DE SEGURANÇA").classes("eyebrow")
            ui.label("Restaurar uma sessão").classes("section-title")
            ui.label(
                "Selecione um ficheiro ZIP criado pelo CoerIA. O restauro cria uma "
                "nova sessão na sua conta e não substitui nenhuma sessão existente."
            ).classes("text-sm")
            ui.label(
                "A cópia contém um JSON legível, os anexos preservados, imagens, "
                "versões e o histórico completo da sessão. Não contém chaves de API. "
                "Guarde-a num local protegido."
            ).classes("text-sm muted")
            self.session_restore_uploader = ui.upload(
                label="Selecionar cópia de segurança",
                auto_upload=True,
                max_file_size=maximum_backup_bytes,
                on_upload=self.handle_restore_backup_upload,
                on_rejected=lambda: ui.notify(
                    f"A cópia excede o limite de {maximum_backup_mb} MB.",
                    type="warning",
                ),
            ).props("accept=.zip flat bordered").classes("w-full").mark(
                "session-restore-upload"
            )
            with ui.row().classes("w-full justify-end"):
                ui.button(
                    "Cancelar",
                    on_click=self.session_restore_dialog.close,
                ).props("flat no-caps")

    def open_session_restore_dialog(self) -> None:
        self.session_restore_uploader.reset()
        self.session_restore_dialog.open()

    async def handle_backup_session(self, session_id: str) -> None:
        self._show_busy(
            "A preparar a cópia de segurança…",
            detail=(
                "A preparar o JSON legível, os anexos, as versões e a "
                "rastreabilidade da sessão…"
            ),
        )
        try:
            backup_data, backup_filename = await run.io_bound(
                self.service.backup_session,
                session_id,
            )
            ui.download(
                backup_data,
                filename=backup_filename,
                media_type="application/zip",
            )
            ui.notify("Cópia de segurança preparada.", type="positive")
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    async def handle_restore_backup_upload(
        self,
        event: events.UploadEventArguments,
    ) -> None:
        self._show_busy(
            "A restaurar a sessão…",
            detail="A validar a integridade e a compatibilidade da cópia…",
        )
        try:
            backup_data = await event.file.read()
            self.state = await run.io_bound(
                self.service.restore_session_backup,
                backup_data,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.export_document_format = _export_choice_for_document_formats(
                self.state.get("last_export_document_formats")
            )
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.uploaded_files.clear()
            self.removed_source_files.clear()
            self.uploader.reset()
            self.render_upload_list()
            self.session_restore_dialog.close()
            self.show_workspace(
                "Sessão restaurada como uma nova sessão. A cópia original e as "
                "restantes sessões não foram alteradas."
            )
            self.refresh_sessions()
            self.drawer.hide()
            ui.notify("Sessão restaurada com sucesso.", type="positive")
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self.session_restore_uploader.reset()
            self._hide_busy()

    def open_delete_session_dialog(
        self,
        session_id: str,
        unit_name: str,
    ) -> None:
        async def confirm_delete() -> None:
            dialog.close()
            await self.handle_delete_session(session_id)

        with ui.dialog() as dialog, ui.card().classes(
            "p-5 w-96 max-w-full surface"
        ):
            ui.icon("delete_forever", size="2.2rem", color="negative")
            ui.label("Eliminar sessão?").classes("section-title")
            ui.label(unit_name).classes("font-semibold")
            ui.label(
                "Esta operação é definitiva e elimina também o histórico e "
                "o rasto de auditoria desta sessão."
            ).classes("muted")
            with ui.row().classes("w-full justify-end mt-3"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Eliminar definitivamente",
                    icon="delete_forever",
                    on_click=confirm_delete,
                ).props("unelevated no-caps color=negative")
        dialog.open()

    async def handle_delete_session(self, session_id: str) -> None:
        try:
            await run.io_bound(self.service.delete_session, session_id)
            is_current = bool(
                self.state and self.state.get("session_id") == session_id
            )
            if is_current:
                self.show_home()
            self.refresh_sessions()
            ui.notify("Sessão eliminada definitivamente.", type="positive")
        except USER_ERRORS as error:
            self._show_error(error)

    async def handle_load_session(self, session_id: str) -> None:
        self._show_busy("A retomar a sessão guardada…")
        try:
            self.state = await run.io_bound(self.service.load_session, session_id)
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.export_document_format = _export_choice_for_document_formats(
                self.state.get("last_export_document_formats")
            )
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.uploaded_files.clear()
            self.removed_source_files.clear()
            self.uploader.reset()
            self.render_upload_list()
            self.show_workspace(
                "Sessão retomada. As fontes incorporadas permanecem no estado guardado."
            )
            self.drawer.hide()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    def show_workspace(self, message: str = "") -> None:
        if not self.state:
            return
        self._set_initial_view_mode(False)
        self.initial_edit_baseline = None
        self.home_view.set_visibility(False)
        self.initial_view.set_visibility(False)
        self.workspace_view.set_visibility(True)
        course = self.state.get("course", {})
        self.header_context.set_text(
            f"{course.get('unit_name', 'Sessão')} · {self.state.get('ai_provider', 'OpenAI')}"
        )
        self._render_workspace(message)
        if message:
            ui.notify(message, type="positive", multi_line=True)

    def _render_workspace(self, message: str = "") -> None:
        if not self.state:
            return
        state = self.state
        self.workspace_view.clear()
        with self.workspace_view:
            with ui.row().classes("w-full items-start gap-3"):
                with ui.column().classes("gap-1"):
                    ui.label("SESSÃO PEDAGÓGICA").classes("eyebrow")
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label(
                            state.get("course", {}).get("unit_name", "Sessão")
                        ).classes("text-3xl font-extrabold tracking-tight")
                        ui.chip(state.get("ai_provider", "OpenAI"), icon="smart_toy").classes("info-chip")
                        ui.chip(
                            state.get("course", {}).get("taxonomy_type", "SOLO"),
                            icon="account_tree",
                        ).classes("info-chip")

            self._render_stage_track(state)

            viewed_stage = None if is_manual_first(state) else (
                self.viewed_stage
                if self.viewed_stage in revision_targets_for_state(state)
                else None
            )
            if viewed_stage:
                self._render_stage_preview(state, viewed_stage)
            elif state.get("status") == "completed":
                self._render_completed_view(state)
            elif state.get("current_stage") == "final_validation":
                self._render_final_validation_view(state)
            else:
                self._render_authoring_view(state)

            self._render_history_and_audit(state)

    def _render_stage_track(self, state: dict[str, Any]) -> None:
        if is_manual_first(state):
            self._render_manual_stage_track(state)
            return
        current_index = STAGE_ORDER.index(state["current_stage"])
        viewable_stages = set(revision_targets_for_state(state))
        stored_statuses = state.get("stage_statuses", {})
        status_labels = {
            "approved": "Aprovado · selecionar para consultar",
            "awaiting_review": "Em validação",
            "generating": "A gerar",
            "stale": "Desatualizado · requer nova validação",
            "pending": "Pendente",
        }
        with ui.element("div").classes("stage-track").style(
            f"--stage-count: {DISPLAY_STAGE_COUNT}"
        ):
            completed = state.get("status") == "completed"
            self._render_initial_data_track_item(
                current=False,
                selectable=not completed,
                status="approved",
                status_label=(
                    "Sessão concluída · modo de consulta"
                    if completed
                    else "Concluído · selecionar para editar"
                ),
            )
            for index, stage in enumerate(STAGE_ORDER):
                stored_status = stored_statuses.get(stage)
                if not stored_status:
                    stored_status = (
                        "approved"
                        if index < current_index or state.get("status") == "completed"
                        else "awaiting_review"
                        if index == current_index
                        else "pending"
                    )
                current = stage == state["current_stage"]
                status_class = _stage_status_css_class(stored_status)
                returns_to_current = (
                    stage == state["current_stage"] and self.viewed_stage is not None
                )
                selectable = returns_to_current or (
                    stage in viewable_stages and stage != state["current_stage"]
                )
                viewing = stage == self.viewed_stage
                item = ui.element("button" if selectable else "div").classes(
                    f"stage-item {status_class}"
                    + (" current" if current else "")
                    + (" selectable" if selectable else "")
                    + (" viewing" if viewing else "")
                )
                item_markers = [status_class]
                if returns_to_current:
                    item_markers.append("return-current-stage")
                item.mark(*item_markers)
                if selectable:
                    item.props("type=button")
                    item.on(
                        "click",
                        lambda _event,
                        selected_stage=stage,
                        return_action=returns_to_current: (
                            self._return_to_current_stage()
                            if return_action
                            else self._view_stage(selected_stage)
                        ),
                    )
                with item:
                    ui.label(f"{index + 2:02d}").classes("stage-number")
                    ui.label(STAGE_LABELS[stage]).classes("stage-label")
                    base_status_label = status_labels.get(stored_status, stored_status)
                    stage_status_label = (
                        f"Ponto atual · {base_status_label} · selecionar para voltar"
                        if returns_to_current
                        else f"Ponto atual · {base_status_label}"
                        if current
                        else base_status_label
                    )
                    ui.label(stage_status_label).classes("stage-state")

    def _render_manual_stage_track(self, state: dict[str, Any]) -> None:
        status_labels = {
            "draft": "Rascunho",
            "empty": "Por preencher",
            "needs_review": "Rever após alterações anteriores",
            "checked": "Verificação executada",
            "approved": "Concluído",
            "pending": "Por verificar",
        }
        stored_statuses = state.get("stage_statuses", {})
        completed = state.get("status") == "completed"
        with ui.element("div").classes("stage-track").style(
            f"--stage-count: {DISPLAY_STAGE_COUNT}"
        ):
            self._render_initial_data_track_item(
                current=False,
                selectable=not completed,
                status="approved",
                status_label=(
                    "Sessão concluída · modo de consulta"
                    if completed
                    else "Concluído · selecionar para editar"
                ),
            )
            for index, stage in enumerate(STAGE_ORDER):
                stored_status = stored_statuses.get(stage, "empty")
                current = stage == state.get("current_stage")
                status_class = _stage_status_css_class(stored_status)
                selectable = not current and not completed
                item = ui.element("button" if selectable else "div").classes(
                    f"stage-item {status_class}"
                    + (" current" if current else "")
                    + (" selectable" if selectable else "")
                )
                item.mark(f"manual-stage-{stage}", status_class)
                if selectable:
                    item.props("type=button")
                    item.on(
                        "click",
                        lambda _event, selected_stage=stage: self._navigate_manual_stage(
                            selected_stage
                        ),
                    )
                with item:
                    ui.label(f"{index + 2:02d}").classes("stage-number")
                    ui.label(STAGE_LABELS[stage]).classes("stage-label")
                    base_status_label = status_labels.get(stored_status, stored_status)
                    ui.label(
                        f"Sessão concluída · {base_status_label}"
                        if completed
                        else f"Ponto atual · {base_status_label}"
                        if current
                        else base_status_label
                    ).classes("stage-state")

    async def _navigate_manual_stage(
        self,
        target_stage: str,
        *,
        notice: str = "",
    ) -> None:
        try:
            self.state, message = await run.io_bound(
                self.service.navigate_session,
                self.state,
                target_stage,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.show_workspace(" ".join(part for part in (notice, message) if part))
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)

    def _view_stage(self, target_stage: str) -> None:
        if not self.state or target_stage not in revision_targets_for_state(self.state):
            return
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.viewed_stage = target_stage
        self._render_workspace(
            "Etapa aberta apenas para consulta. A sessão e os passos seguintes "
            "permanecem inalterados."
        )

    def _return_to_current_stage(self) -> None:
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.viewed_stage = None
        self._render_workspace("Regressou ao ponto atual da sessão.")

    def _start_manual_edit(self, stage: str) -> None:
        try:
            if not self.state:
                raise ValueError("Inicie ou retome primeiro uma sessão pedagógica.")
            editor_layout(stage)
            self.manual_edit_artifact = active_stage_artifact(self.state, stage)
            self.manual_edit_stage_context = (
                {
                    "learning_outcome_assumptions": list(
                        self.state.get("learning_outcome_assumptions", [])
                    )
                }
                if stage == "learning_outcomes"
                else {}
            )
        except USER_ERRORS as error:
            self._show_error(error)
            return
        self.manual_edit_stage = stage
        self._render_workspace(
            "Modo de edição ativado na própria tabela. As alterações ainda não "
            "foram guardadas."
        )

    def _cancel_manual_edit(self) -> None:
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.manual_edit_stage_context = {}
        self._render_workspace("Edição manual cancelada; a sessão não foi alterada.")

    def _open_revision_dialog(self, target_stage: str) -> None:
        try:
            impact = self.service.revision_impact(self.state, target_stage)
        except USER_ERRORS as error:
            self._show_error(error)
            return

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl p-6 gap-4"):
            ui.label("REABRIR ETAPA").classes("eyebrow")
            ui.label(impact["target_label"]).classes("section-title")
            ui.label(
                f"Será criada a versão {impact['next_version']} desta etapa. "
                "O estado atualmente aprovado será preservado no histórico."
            ).classes("text-sm")
            if impact["was_completed"]:
                ui.label(
                    "A sessão deixará temporariamente o estado Concluído até uma "
                    "nova validação final."
                ).classes("soft-surface p-3 text-sm font-medium")
            affected_labels = impact["affected_labels"]
            if affected_labels:
                ui.label("Etapas que ficarão desatualizadas:").classes("font-semibold")
                with ui.column().classes("gap-1"):
                    for label in affected_labels:
                        ui.label(f"• {label}").classes("text-sm muted")
            else:
                ui.label(
                    "Nenhuma etapa posterior já gerada será afetada."
                ).classes("text-sm muted")
            feedback = ui.textarea(
                "Alteração a efetuar",
                placeholder=(
                    "Descreva de forma concreta o que pretende editar ou reformular."
                ),
            ).props("outlined autogrow").classes("w-full")

            async def confirm_revision() -> None:
                clean_feedback = str(feedback.value or "").strip()
                if not clean_feedback:
                    ui.notify(
                        "Descreva a alteração antes de confirmar.",
                        type="warning",
                    )
                    return
                dialog.close()
                await self.handle_reopen_stage(target_stage, clean_feedback)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=dialog.close).props(
                    "flat no-caps"
                ).classes("secondary-action")
                ui.button(
                    "Confirmar e criar nova versão",
                    icon="edit_note",
                    on_click=confirm_revision,
                ).props("unelevated no-caps").classes("primary-action")
        dialog.open()

    def _render_presentation_resource_view(
        self,
        state: dict[str, Any],
        artifact: dict[str, Any],
    ) -> None:
        """Mostra os slides com a miniatura integrada na coluna visual."""

        slides = artifact.get("presentation_outline", [])
        ui.label(f"{len(slides)} slides").classes("font-semibold mb-3")
        headers = (
            "Slide",
            "Título",
            "Resultado",
            "Conteúdo",
            "Modo visual",
            "Elemento visual",
            "Texto alternativo",
        )
        with ui.element("div").classes(
            "artifact-markdown presentation-view-table-wrap overflow-x-auto"
        ):
            with ui.element("table").classes("presentation-view-table"):
                with ui.element("thead"):
                    with ui.element("tr"):
                        for header in headers:
                            with ui.element("th"):
                                ui.label(header)
                with ui.element("tbody"):
                    for index, slide in enumerate(slides, start=1):
                        identifier = str(slide.get("visual_asset_id", "")).strip()
                        asset = (
                            self._presentation_image_asset(state, identifier)
                            if identifier
                            else None
                        )
                        mode = str(slide.get("visual_mode", "diagrama")).strip()
                        with ui.element("tr").classes(
                            f"validation-target-slide-{index}"
                        ):
                            with ui.element("td"):
                                ui.label(str(index))
                            with ui.element("td"):
                                ui.label(str(slide.get("title", "")))
                            with ui.element("td"):
                                ui.label(str(slide.get("outcome_id", "") or "—"))
                            with ui.element("td"):
                                ui.label(
                                    " · ".join(
                                        str(item)
                                        for item in slide.get("bullets", [])
                                        if str(item).strip()
                                    )
                                ).classes("presentation-view-content")
                            with ui.element("td").classes(
                                "presentation-view-visual-cell"
                            ).mark(f"presentation-view-visual-{index}"):
                                if asset is not None:
                                    thumbnail = self._render_presentation_image_thumbnail(
                                        asset, compact=True
                                    )
                                    thumbnail.mark(
                                        f"presentation-view-thumbnail-{index}"
                                    )
                                    ui.label(
                                        "Imagem gerada por IA"
                                        if asset.get("origin_type") == "ai_generated"
                                        else "Imagem carregada pelo docente"
                                        if asset.get("origin_type") == "user_uploaded"
                                        else "Imagem documental"
                                    ).classes("text-xs font-semibold")
                                else:
                                    ui.icon("account_tree", size="1.6rem").classes(
                                        "muted"
                                    )
                                    ui.label(
                                        "Imagem por gerar"
                                        if mode == "ia"
                                        else "Diagrama editável"
                                    ).classes("text-xs font-semibold")
                            with ui.element("td"):
                                ui.label(str(slide.get("visual_title", "")))
                            with ui.element("td"):
                                ui.label(str(slide.get("alt_text", "")))

    @staticmethod
    def _selected_resource_tab_config(
        state: dict[str, Any],
        artifact: dict[str, Any],
    ) -> list[tuple[str, str, str, str, str]]:
        selected = set(
            artifact.get("selected_types") or state.get("resource_types", [])
        )
        return [
            config for config in RESOURCE_TAB_CONFIG if config[0] in selected
        ]

    def _render_resource_detail_tabs(
        self,
        state: dict[str, Any],
        artifact: dict[str, Any],
    ) -> None:
        sections = render_resource_detail_sections(artifact)
        if not sections:
            ui.label(
                "Ainda não existem recursos selecionados para visualizar."
            ).classes("text-sm muted mt-4")
            return

        ui.label("CONTEÚDO DOS RECURSOS").classes("eyebrow mt-4")
        with ui.tabs().props("no-caps align=left").classes(
            "resource-tabs w-full"
        ) as tabs:
            tab_by_id = {
                section["id"]: ui.tab(
                    section["id"],
                    label=section["label"],
                    icon=section["icon"],
                ).classes(
                    f"validation-resource-tab-{section['id']}"
                ).mark(f"resource-view-tab-{section['id']}")
                for section in sections
            }
        first_tab = tab_by_id[sections[0]["id"]]
        with ui.tab_panels(tabs, value=first_tab).classes(
            "resource-tab-panels w-full"
        ):
            for section in sections:
                with ui.tab_panel(tab_by_id[section["id"]]).classes(
                    f"px-0 validation-resource-panel-{section['id']}"
                ):
                    if section["id"] == "presentation":
                        self._render_presentation_resource_view(state, artifact)
                    else:
                        ui.markdown(
                            section["content"], extras=["tables"]
                        ).classes("artifact-markdown overflow-x-auto")

    @staticmethod
    def _presentation_image_asset(
        state: dict[str, Any], identifier: str
    ) -> dict[str, Any] | None:
        for collection in ("source_images", "generated_images"):
            for asset in state.get(collection, []):
                if (
                    isinstance(asset, dict)
                    and str(asset.get("id", "")).strip() == identifier
                ):
                    return asset
        return None

    def _presentation_editor_state(
        self,
        image_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Combina imagens da proposta em revisão com alterações já persistidas."""

        if image_state is None:
            return self.state or {}
        merged = deepcopy(image_state)
        current = self.state or {}
        for collection in ("source_images", "generated_images"):
            assets = [
                deepcopy(item)
                for item in merged.get(collection, [])
                if isinstance(item, dict)
            ]
            known_ids = {str(item.get("id", "")) for item in assets}
            assets.extend(
                deepcopy(item)
                for item in current.get(collection, [])
                if isinstance(item, dict)
                and str(item.get("id", "")) not in known_ids
            )
            merged[collection] = assets
        return merged

    @staticmethod
    def _render_presentation_image_thumbnail(
        asset: dict[str, Any], *, gallery: bool = False, compact: bool = False
    ) -> Any:
        encoded = str(
            asset.get("thumbnail_base64") or asset.get("data_base64", "")
        ).strip()
        if not encoded:
            placeholder = ui.element("div").classes(
                (
                    "presentation-mode-thumbnail"
                    if compact
                    else "presentation-image-preview"
                )
                + " flex items-center justify-center"
            )
            with placeholder:
                ui.icon("broken_image", size="2rem").classes("muted")
            return placeholder
        media_type = str(
            asset.get("thumbnail_media_type") or asset.get("media_type", "image/png")
        ).strip()
        image = ui.image(f"data:{media_type};base64,{encoded}")
        if compact:
            image.classes("presentation-mode-thumbnail").props("fit=contain")
        elif gallery:
            image.classes("w-full").props("fit=contain")
        else:
            image.classes("presentation-image-preview").props("fit=contain")
        return image

    def _open_presentation_image_dialog(
        self,
        slide: dict[str, Any],
        refresh_editor: Any,
        slide_number: int,
        image_state: dict[str, Any] | None = None,
    ) -> None:
        state = self._presentation_editor_state(image_state)
        assets = available_presentation_images(state)
        current_identifier = str(slide.get("visual_asset_id", "")).strip()
        maximum_additional = configured_max_additional_editor_images()
        maximum_upload_bytes = configured_presentation_image_upload_bytes()
        generated_during_edit = manual_editor_image_count(state)
        remaining_generations = max(0, maximum_additional - generated_during_edit)

        with ui.dialog() as dialog, ui.card().classes(
            "surface p-5 gap-4"
        ).style("width: min(1120px, 96vw); max-width: 96vw;"):
            with ui.row().classes("w-full items-start gap-3"):
                with ui.column().classes("gap-1"):
                    ui.label("SELECIONAR IMAGEM").classes("eyebrow")
                    ui.label("Imagem associada ao slide").classes("section-title")
                    ui.label(
                        "Escolha uma imagem disponível, gere uma nova proposta visual "
                        "ou carregue uma imagem do seu computador."
                    ).classes("text-sm muted")
                ui.space()
                ui.button(icon="close", on_click=dialog.close).props(
                    "flat round aria-label='Fechar seleção de imagem'"
                )

            with ui.tabs().props("no-caps align=left").classes("w-full") as image_tabs:
                available_tab = ui.tab(
                    "available", label="Imagens disponíveis", icon="photo_library"
                ).mark("presentation-image-tab-available")
                generate_tab = ui.tab(
                    "generate", label="Gerar com IA", icon="auto_awesome"
                ).mark("presentation-image-tab-generate")
                upload_tab = ui.tab(
                    "upload", label="Carregar do computador", icon="upload"
                ).mark("presentation-image-tab-upload")

            with ui.tab_panels(image_tabs, value=available_tab).classes("w-full"):
                with ui.tab_panel(available_tab).classes("px-0"):
                    if assets:
                        with ui.element("div").classes("presentation-image-gallery"):
                            for asset in assets:
                                identifier = str(asset.get("id", "")).strip()

                                def choose_image(
                                    selected_asset: dict[str, Any] = asset,
                                ) -> None:
                                    apply_presentation_image_choice(slide, selected_asset)
                                    dialog.close()
                                    refresh_editor()

                                with ui.card().classes(
                                    "presentation-image-option soft-surface gap-2"
                                ):
                                    self._render_presentation_image_thumbnail(
                                        asset, gallery=True
                                    )
                                    ui.label(presentation_image_label(asset)).classes(
                                        "text-sm font-semibold"
                                    )
                                    if asset.get("origin_type") == "ai_generated":
                                        ui.label("Imagem gerada por IA").classes(
                                            "text-xs muted"
                                        )
                                    elif asset.get("origin_type") == "user_uploaded":
                                        ui.label("Imagem carregada pelo docente").classes(
                                            "text-xs muted"
                                        )
                                    else:
                                        ui.label("Imagem extraída de documento").classes(
                                            "text-xs muted"
                                        )
                                    button = ui.button(
                                        "Selecionada"
                                        if identifier == current_identifier
                                        else "Selecionar",
                                        icon="check_circle"
                                        if identifier == current_identifier
                                        else "add_photo_alternate",
                                        on_click=choose_image,
                                    ).props("unelevated no-caps").classes("w-full").mark(
                                        f"select-slide-image-{identifier}"
                                    )
                                    if identifier == current_identifier:
                                        button.props("color=positive")
                    else:
                        with ui.column().classes(
                            "soft-surface w-full items-center text-center p-8 gap-2"
                        ):
                            ui.icon("image_not_supported", size="2.4rem").classes(
                                "muted"
                            )
                            ui.label("Não existem imagens disponíveis.").classes(
                                "font-semibold"
                            )
                            ui.label(
                                "Use os outros separadores para gerar ou carregar uma imagem."
                            ).classes("text-sm muted")

                with ui.tab_panel(generate_tab).classes("px-0"):
                    with ui.column().classes("w-full gap-3"):
                        ui.label(
                            f"Pode gerar mais {remaining_generations} de "
                            f"{maximum_additional} imagens adicionais nesta sessão."
                        ).classes("text-sm font-semibold")
                        ui.label(
                            "A sugestão usa o fornecedor textual escolhido. A geração "
                            "da imagem usa a OpenAI Image API e pode ter custo."
                        ).classes("text-sm muted")
                        prompt_input = ui.textarea(
                            "Instrução para gerar a imagem",
                            value=str(slide.get("visual_prompt", "")).strip(),
                            placeholder=(
                                "Descreva a composição visual pretendida ou peça uma "
                                "sugestão baseada neste slide."
                            ),
                        ).props("outlined autogrow").classes("w-full").mark(
                            f"slide-image-prompt-{slide_number}"
                        )

                        async def suggest_prompt() -> None:
                            self._show_busy("A IA está a sugerir uma instrução visual…")
                            try:
                                suggestion = await run.io_bound(
                                    self.service.suggest_presentation_image_prompt,
                                    self.state,
                                    deepcopy(slide),
                                    slide_number,
                                )
                                prompt_input.set_value(suggestion)
                                ui.notify(
                                    "Sugestão recebida. Pode editá-la antes de gerar.",
                                    type="positive",
                                )
                            except USER_ERRORS as error:
                                self._show_error(error)
                            finally:
                                self._hide_busy()

                        async def generate_image() -> None:
                            self._show_busy("A gerar uma imagem para este slide…")
                            try:
                                updated_state, asset = await run.io_bound(
                                    self.service.generate_presentation_editor_image,
                                    self.state,
                                    deepcopy(slide),
                                    slide_number,
                                    str(prompt_input.value or ""),
                                )
                                self.state = updated_state
                                apply_presentation_image_choice(slide, asset)
                                dialog.close()
                                refresh_editor()
                                self.refresh_sessions()
                                ui.notify(
                                    "Imagem gerada e associada ao slide.",
                                    type="positive",
                                )
                            except USER_ERRORS as error:
                                self._show_error(error)
                            finally:
                                self._hide_busy()

                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            suggest_button = ui.button(
                                "Sugerir instrução com IA",
                                icon="lightbulb",
                                on_click=suggest_prompt,
                            ).props("outline no-caps").mark(
                                f"suggest-slide-image-prompt-{slide_number}"
                            )
                            generate_button = ui.button(
                                "Gerar e associar imagem",
                                icon="auto_awesome",
                                on_click=generate_image,
                            ).props("unelevated no-caps").mark(
                                f"generate-slide-image-{slide_number}"
                            )
                            if remaining_generations == 0:
                                suggest_button.disable()
                                generate_button.disable()

                with ui.tab_panel(upload_tab).classes("px-0"):
                    with ui.column().classes("w-full gap-3"):
                        ui.label(
                            "A imagem é processada localmente, normalizada e guardada "
                            "na sessão. Não é enviada ao LLM."
                        ).classes("text-sm muted")

                        async def upload_image(event: events.UploadEventArguments) -> None:
                            self._show_busy("A validar e guardar a imagem…")
                            try:
                                image_data = await event.file.read()
                                updated_state, asset = await run.io_bound(
                                    self.service.add_presentation_uploaded_image,
                                    self.state,
                                    event.file.name,
                                    image_data,
                                )
                                self.state = updated_state
                                apply_presentation_image_choice(slide, asset)
                                dialog.close()
                                refresh_editor()
                                self.refresh_sessions()
                                ui.notify(
                                    "Imagem carregada e associada ao slide.",
                                    type="positive",
                                )
                            except USER_ERRORS as error:
                                self._show_error(error)
                            finally:
                                self._hide_busy()

                        ui.upload(
                            label="Selecionar imagem do computador",
                            auto_upload=True,
                            max_file_size=maximum_upload_bytes,
                            on_upload=upload_image,
                            on_rejected=lambda: ui.notify(
                                "A imagem excede o limite permitido ou não é suportada.",
                                type="warning",
                            ),
                        ).props(
                            "accept=.png,.jpg,.jpeg,.webp flat bordered"
                        ).classes("w-full").mark(
                            f"upload-slide-image-{slide_number}"
                        )
                        ui.label(
                            "Formatos aceites: PNG, JPEG e WebP · máximo "
                            f"{maximum_upload_bytes // (1024 * 1024)} MB"
                        ).classes("text-xs muted")

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
        dialog.open()

    def _render_presentation_visual_editor(
        self,
        slide: dict[str, Any],
        refresh_editor: Any,
        slide_number: int,
        image_state: dict[str, Any] | None = None,
    ) -> None:
        state = self._presentation_editor_state(image_state)
        identifier = str(slide.get("visual_asset_id", "")).strip()
        asset = self._presentation_image_asset(state, identifier) if identifier else None
        mode = str(slide.get("visual_mode", "diagrama")).strip() or "diagrama"

        with ui.card().classes("presentation-visual-card soft-surface w-full gap-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Elemento visual").classes("font-semibold")
                ui.space()
                if asset is not None:
                    label = (
                        "Imagem gerada por IA"
                        if asset.get("origin_type") == "ai_generated"
                        else "Imagem carregada pelo docente"
                        if asset.get("origin_type") == "user_uploaded"
                        else "Imagem documental"
                    )
                    ui.badge(label, color="primary")
                elif mode == "ia":
                    ui.badge("Imagem por gerar", color="warning")
                else:
                    ui.badge("Diagrama editável", color="secondary")

            if asset is not None:
                self._render_presentation_image_thumbnail(asset)
                ui.label(presentation_image_label(asset)).classes(
                    "text-xs muted"
                )
            elif mode == "ia":
                ui.label(
                    "A imagem ainda não foi gerada. A instrução abaixo será usada "
                    "numa nova geração da etapa com IA."
                ).classes("text-sm muted")
            else:
                ui.label(
                    "O PowerPoint criará este elemento com formas e texto editáveis."
                ).classes("text-sm muted")

            with ui.row().classes("w-full gap-2 flex-wrap"):
                ui.button(
                    "Escolher imagem",
                    icon="photo_library",
                    on_click=lambda: self._open_presentation_image_dialog(
                        slide, refresh_editor, slide_number, image_state
                    ),
                ).props("outline no-caps").classes("secondary-action").mark(
                    f"choose-slide-image-{slide_number}"
                )
                if asset is not None or mode == "ia":

                    def use_diagram() -> None:
                        apply_presentation_image_choice(slide, None)
                        refresh_editor()

                    ui.button(
                        "Usar diagrama editável",
                        icon="account_tree",
                        on_click=use_diagram,
                    ).props("flat no-caps").classes("secondary-action")

            self._render_manual_field(
                slide,
                FieldSpec("visual_title", "Título do elemento visual"),
            )
            if mode == "ia" and asset is None:
                self._render_manual_field(
                    slide,
                    FieldSpec("visual_prompt", "Instrução para gerar a imagem", "long"),
                )
            elif asset is None:
                self._render_manual_field(
                    slide,
                    FieldSpec(
                        "visual_items",
                        "Elementos do diagrama — 2 a 4, um por linha",
                        "lines",
                    ),
                )
                ui.label(
                    "Obrigatório para o diagrama: introduza entre 2 e 4 elementos não vazios."
                ).classes("text-xs muted")
            self._render_manual_field(
                slide,
                FieldSpec("alt_text", "Descrição acessível da imagem ou diagrama", "long"),
            )

    def _render_presentation_editor(
        self,
        artifact: dict[str, Any],
        table: TableSpec,
        image_state: dict[str, Any] | None = None,
    ) -> None:
        slides = value_at_path(artifact, table.path)
        if not isinstance(slides, list):
            raise ValueError("A apresentação não possui slides editáveis.")
        expanded_slide = {"index": 0}

        @ui.refreshable
        def render_slides() -> None:
            if not slides:
                ui.label(
                    "A apresentação está vazia. Adicione o primeiro slide."
                ).classes("text-sm muted")
                return
            with ui.column().classes("presentation-slides w-full"):
                for index, slide in enumerate(slides):
                    title = str(slide.get("title", "")).strip() or "Sem título"
                    expansion = ui.expansion(
                        f"Slide {index + 1} — {title}",
                        icon="slideshow",
                        value=index == expanded_slide["index"],
                    ).props('group="presentation-slides"').classes(
                        "presentation-slide w-full"
                    ).mark(f"presentation-slide-{index + 1}")

                    def remember_expanded_slide(
                        event: Any, slide_index: int = index
                    ) -> None:
                        if event.value:
                            expanded_slide["index"] = slide_index

                    expansion.on_value_change(remember_expanded_slide)

                    def refresh_current_slide(slide_index: int = index) -> None:
                        expanded_slide["index"] = slide_index
                        render_slides.refresh()

                    with expansion:
                        with ui.row().classes("w-full justify-end"):

                            def remove_slide(slide_index: int = index) -> None:
                                slides.pop(slide_index)
                                expanded_slide["index"] = min(
                                    slide_index, max(len(slides) - 1, 0)
                                )
                                render_slides.refresh()

                            ui.button(
                                "Remover slide",
                                icon="delete",
                                on_click=remove_slide,
                            ).props("flat no-caps color=negative")
                        with ui.element("div").classes("presentation-slide-grid"):
                            self._render_manual_field(
                                slide, FieldSpec("title", "Título do slide")
                            )
                            self._render_manual_field(
                                slide, FieldSpec("outcome_id", "Resultado de aprendizagem")
                            )
                        self._render_manual_field(
                            slide,
                            FieldSpec("bullets", "Conteúdo — um ponto por linha", "lines"),
                        )
                        self._render_presentation_visual_editor(
                            slide,
                            refresh_current_slide,
                            index + 1,
                            image_state,
                        )

        def add_slide() -> None:
            row = new_table_row(table, self.state, slides)
            slides.append(row)
            expanded_slide["index"] = len(slides) - 1
            render_slides.refresh()

        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("w-full items-center gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label("Slides da apresentação").classes("text-lg font-bold")
                    ui.label(
                        "Abra um slide de cada vez. Os dados técnicos da imagem são "
                        "preenchidos automaticamente."
                    ).classes("text-sm muted")
                ui.space()
                ui.button("Adicionar slide", icon="add", on_click=add_slide).props(
                    "outline no-caps"
                ).classes("secondary-action")
            render_slides()

    def _render_resource_editor_tabs(
        self,
        state: dict[str, Any],
        artifact: dict[str, Any],
        layout: Any,
    ) -> None:
        resource_configs = self._selected_resource_tab_config(state, artifact)
        if not resource_configs:
            ui.label(
                "Selecione primeiro pelo menos um recurso em «Recursos a preparar»."
            ).classes("text-sm muted")
            return

        with ui.tabs().props("no-caps align=left").classes(
            "resource-tabs w-full"
        ) as tabs:
            tab_by_id = {
                tab_id: ui.tab(
                    tab_id,
                    label=label,
                    icon=icon,
                ).mark(f"resource-edit-tab-{tab_id}")
                for _, tab_id, label, icon, _ in resource_configs
            }
        first_tab = tab_by_id[resource_configs[0][1]]
        with ui.tab_panels(tabs, value=first_tab).classes(
            "resource-tab-panels w-full"
        ):
            for _, tab_id, _, _, root_path in resource_configs:
                with ui.tab_panel(tab_by_id[tab_id]).classes("px-0"):
                    with ui.column().classes("w-full gap-4"):
                        for scalar in layout.fields:
                            if scalar.path[0] != root_path:
                                continue
                            parent = value_at_path(artifact, scalar.path[:-1])
                            self._render_manual_field(
                                parent,
                                FieldSpec(
                                    scalar.path[-1],
                                    scalar.label,
                                    scalar.kind,
                                ),
                            )
                        for table in layout.tables:
                            if table.path[0] == root_path:
                                if tab_id == "presentation":
                                    self._render_presentation_editor(
                                        artifact,
                                        table,
                                        state,
                                    )
                                else:
                                    self._render_manual_table(artifact, table)
    def _render_stage_preview(self, state: dict[str, Any], stage: str) -> None:
        """Mostra uma etapa anterior sem a tornar corrente nem a invalidar."""

        editing = (
            self.manual_edit_stage == stage and self.manual_edit_artifact is not None
        )
        with ui.column().classes("w-full gap-4"):
            if editing:
                self._render_stage_toolbar(
                    state,
                    stage,
                    editing=True,
                    proposal=None,
                )
                with ui.card().classes("surface artifact-card w-full").mark(
                    "artifact-content"
                ):
                    self._render_inline_manual_editor(stage)
                return

            # Em consulta, os controlos ficam imediatamente sob o percurso de etapas
            # e o conteúdo ocupa toda a largura disponível. Isto é especialmente
            # importante nas etapas tabulares, evitando comprimir colunas numa grelha
            # lateral de decisão.
            with ui.card().classes("surface consultation-card w-full"):
                ui.label("MODO DE CONSULTA").classes("eyebrow")
                ui.label("Etapa anterior").classes("section-title")
                ui.label(
                    "Abrir esta etapa não altera a sessão. Só será criada uma "
                    "nova versão se escolher Editar ou Reformular e confirmar "
                    "a alteração."
                ).classes("text-sm muted")
                with ui.row().classes("w-full gap-2 flex-wrap mt-3"):
                    ui.button(
                        "Editar esta tabela",
                        icon="edit",
                        on_click=lambda: self._start_manual_edit(stage),
                    ).props("unelevated no-caps").classes("primary-action").style(
                        "min-width: 210px; flex: 1 1 210px;"
                    )
                    ui.button(
                        "Reformular esta etapa",
                        icon="edit_note",
                        on_click=lambda: self._open_revision_dialog(stage),
                    ).props("outline no-caps").classes("secondary-action").style(
                        "min-width: 210px; flex: 1 1 210px;"
                    )
                    ui.button(
                        "Voltar ao ponto atual",
                        icon="arrow_back",
                        on_click=self._return_to_current_stage,
                    ).props("outline no-caps").classes("secondary-action").style(
                        "min-width: 210px; flex: 1 1 210px;"
                    )

            with ui.card().classes(
                f"surface artifact-card stage-artifact-focus "
                f"stage-artifact-{stage} w-full"
            ).mark(
                "artifact-content"
            ):
                ui.markdown(
                    render_stage_artifact(state, stage),
                    extras=["tables"],
                ).classes("artifact-markdown")
                if stage == "resources":
                    self._render_resource_detail_tabs(
                        state,
                        active_stage_artifact(state, stage),
                    )

    def _render_manual_field(
        self,
        target: dict[str, Any],
        field: FieldSpec,
        *,
        compact: bool = False,
        refresh_after_change: Any = None,
    ) -> Any:
        value = editor_field_value(target, field)

        def update_value(event: Any) -> None:
            try:
                apply_editor_field_value(target, field, event.value)
                if field.key == "taxonomy_level" and "action_verb" in target:
                    allowed_verbs = editor_taxonomy_verb_options(
                        self.state or {},
                        target,
                        FieldSpec("action_verb", "Verbo", "taxonomy_verb"),
                    ) or {}
                    if target.get("action_verb") not in allowed_verbs:
                        target["action_verb"] = ""
                if refresh_after_change is not None:
                    refresh_after_change()
            except (TypeError, ValueError):
                ui.notify(
                    f"O valor de «{field.label}» não é válido.",
                    type="warning",
                )

        label = None if compact else field.label
        selection_options = editor_reference_options(self.state or {}, field)
        if selection_options is None:
            selection_options = editor_taxonomy_level_options(
                self.state or {}, field
            )
        if selection_options is None:
            selection_options = editor_taxonomy_verb_options(
                self.state or {}, target, field
            )
        if selection_options is not None:
            multiple = field.kind in {"csv", "content_ids", "linked_outcomes"}
            is_compact_reference = field.key in {
                "outcome_id",
                "outcome_ids",
                "component_ids",
            }
            selection_value = editor_reference_value(target, field)
            allowed_values = set(selection_options)
            if multiple:
                selection_value = [
                    item for item in (selection_value or []) if item in allowed_values
                ]
            elif selection_value not in allowed_values:
                selection_value = None
            control = ui.select(
                options=(
                    selection_options
                    if is_compact_reference or not multiple
                    else list(selection_options)
                ),
                label=label,
                value=selection_value,
                multiple=multiple,
                on_change=update_value,
            ).props("options-dense" + (" use-chips" if multiple else ""))
            if is_compact_reference:
                control.mark("learning-outcome-reference")
                control.add_slot(
                    "selected-item",
                    """
                    <q-chip dense>
                        {{ String(props.opt.label).split(' — ')[0] }}
                    </q-chip>
                    """,
                )
            if not selection_options:
                control.props("disable")
        elif field.kind == "integer":
            control = ui.number(label, value=value, precision=0)
        elif field.kind in {"long", "lines"}:
            control = ui.textarea(label, value=value).props("outlined autogrow")
        else:
            control = ui.input(label, value=value).props("outlined")
        if field.kind in {
            "content_id",
            "learning_outcome_id",
            "teaching_activity_id",
            "assessment_task_id",
        }:
            control.props("readonly").mark(
                {
                    "content_id": "content-id",
                    "learning_outcome_id": "learning-outcome-id",
                }.get(field.kind, "structured-activity-id")
            )
        if compact:
            control.props(
                f"dense hide-bottom-space aria-label='{field.label}'"
            ).classes(
                "w-full manual-cell-number"
                if field.kind == "integer"
                else "w-full manual-cell-long"
                if field.kind in {"long", "lines"}
                else "w-full"
            )
        else:
            control.classes("w-full")
        if selection_options is None:
            control.on_value_change(update_value)
        return control

    def _render_manual_table(
        self,
        artifact: Any,
        table: TableSpec,
    ) -> None:
        rows = value_at_path(artifact, table.path)
        if not isinstance(rows, list):
            raise ValueError(f"A tabela «{table.title}» não possui linhas editáveis.")

        @ui.refreshable
        def render_rows() -> None:
            if not rows:
                ui.label("A tabela está vazia. Adicione pelo menos uma linha.").classes(
                    "text-sm muted"
                )
                return
            with ui.element("div").classes("manual-table-scroll"):
                with ui.element("table").classes("manual-table"):
                    with ui.element("thead"):
                        with ui.element("tr"):
                            for field in table.fields:
                                with ui.element("th"):
                                    ui.label(field.label)
                            with ui.element("th"):
                                ui.label("Ações" if table.reorderable else "Remover")
                    with ui.element("tbody"):
                        for index, row in enumerate(rows):
                            with ui.element("tr"):
                                for field in table.fields:
                                    with ui.element("td"):
                                        self._render_manual_field(
                                            row,
                                            field,
                                            compact=True,
                                            refresh_after_change=(
                                                render_rows.refresh
                                                if field.key == "taxonomy_level"
                                                and "action_verb" in row
                                                else None
                                            ),
                                        )

                                def remove_row(row_index: int = index) -> None:
                                    rows.pop(row_index)
                                    render_rows.refresh()

                                def move_row(
                                    offset: int,
                                    row_index: int = index,
                                ) -> None:
                                    if move_table_row(rows, row_index, offset):
                                        render_rows.refresh()

                                action_class = (
                                    "manual-row-actions"
                                    if table.reorderable
                                    else "manual-row-action"
                                )
                                with ui.element("td").classes(action_class):
                                    if table.reorderable:
                                        with ui.row().classes("manual-row-buttons"):
                                            move_up = ui.button(
                                                icon="arrow_upward",
                                                on_click=lambda row_index=index: move_row(
                                                    -1, row_index
                                                ),
                                            ).props(
                                                "flat round dense "
                                                "aria-label='Mover linha para cima'"
                                            ).mark(f"move-row-up-{index + 1}")
                                            move_up.tooltip("Mover para cima")
                                            if index == 0:
                                                move_up.props("disable")
                                            move_down = ui.button(
                                                icon="arrow_downward",
                                                on_click=lambda row_index=index: move_row(
                                                    1, row_index
                                                ),
                                            ).props(
                                                "flat round dense "
                                                "aria-label='Mover linha para baixo'"
                                            ).mark(f"move-row-down-{index + 1}")
                                            move_down.tooltip("Mover para baixo")
                                            if index == len(rows) - 1:
                                                move_down.props("disable")
                                            ui.button(
                                                icon="delete",
                                                on_click=remove_row,
                                            ).props(
                                                "flat round dense color=negative "
                                                "aria-label='Remover linha'"
                                            ).tooltip("Remover linha")
                                    else:
                                        ui.button(
                                            icon="delete",
                                            on_click=remove_row,
                                        ).props(
                                            "flat round color=negative "
                                            "aria-label='Remover linha'"
                                        )

        def add_row() -> None:
            row = new_table_row(table, self.state, rows)
            if "order" in row:
                row["order"] = len(rows) + 1
            rows.append(row)
            render_rows.refresh()

        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("w-full items-center"):
                ui.label(table.title).classes("text-lg font-bold")
                ui.space()
                ui.button("Adicionar linha", icon="add", on_click=add_row).props(
                    "outline no-caps"
                ).classes("secondary-action")
            render_rows()

    def _render_inline_manual_editor(self, stage: str) -> None:
        artifact = self.manual_edit_artifact
        if artifact is None:
            raise ValueError("Não existe uma edição manual ativa.")
        layout = editor_layout(stage)
        ui.label(
            "EDIÇÃO DOS RECURSOS"
            if stage == "resources"
            else "EDIÇÃO NA TABELA ATUAL"
        ).classes("eyebrow")
        ui.label(STAGE_LABELS[stage]).classes("section-title mb-2")
        ui.label(
            "Edite os campos abaixo ou adicione e remova linhas. Enquanto não "
            "guardar, a versão ativa e os passos seguintes permanecem intactos."
        ).classes("text-sm muted mb-4")
        if stage == "resources":
            self._render_resource_editor_tabs(
                self.state or {}, artifact, layout
            )
            return
        with ui.column().classes("w-full gap-4"):
            if stage == "learning_outcomes":
                self._render_manual_field(
                    self.manual_edit_stage_context,
                    FieldSpec(
                        "learning_outcome_assumptions",
                        "Pressupostos para a formulação — opcional, um por linha",
                        "lines",
                    ),
                ).mark("learning-outcome-assumptions")
                ui.label(
                    "Use este campo apenas para condições consideradas na formulação, "
                    "como conhecimentos prévios ou restrições do contexto. Pode "
                    "deixá-lo vazio."
                ).classes("text-xs muted")
            for scalar in layout.fields:
                parent = (
                    value_at_path(artifact, scalar.path[:-1])
                    if scalar.path[:-1]
                    else artifact
                )
                self._render_manual_field(
                    parent,
                    FieldSpec(scalar.path[-1], scalar.label, scalar.kind),
                )
            for table in layout.tables:
                self._render_manual_table(artifact, table)

    @staticmethod
    def _pending_ai_proposal(
        state: dict[str, Any],
        stage: str,
    ) -> dict[str, Any] | None:
        pending = [
            item
            for item in state.get("ai_proposals", [])
            if item.get("stage") == stage and item.get("status") == "pending"
        ]
        return pending[-1] if pending else None

    def _close_decided_ai_proposal_review(self, proposal_id: str) -> bool:
        """Fecha uma revisão antiga quando a decisão já está no estado."""

        if not self.state:
            return False
        matching_proposals = [
            item
            for item in self.state.get("ai_proposals", [])
            if str(item.get("id", "")) == proposal_id
        ]
        if any(item.get("status") == "pending" for item in matching_proposals):
            return False
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self.show_workspace(
            "A decisão sobre esta proposta já estava guardada. "
            "A interface foi atualizada."
        )
        self.refresh_sessions()
        return True

    @staticmethod
    def _proposal_decision_toggle(
        decisions: dict[str, str],
        change_key: str,
    ) -> Any:
        decisions.setdefault(change_key, "Aceitar")

        def update_decision(event: Any) -> None:
            decisions[change_key] = str(event.value or "Rejeitar")

        return ui.toggle(
            ["Aceitar", "Rejeitar"],
            value=decisions[change_key],
            on_change=update_decision,
        ).props("dense no-caps").mark(f"ai-decision-{change_key}")

    def _render_ai_proposal_review(
        self,
        state: dict[str, Any],
        stage: str,
        proposal: dict[str, Any],
    ) -> None:
        """Mostra as sugestões da IA junto das células atuais, sem as aplicar."""

        if stage == "resources" and not proposal.get("scope_path"):
            self._render_complete_resource_ai_proposal_review(state, proposal)
            return

        artifact = state[stage]
        changes = proposal_review_changes(
            stage,
            artifact,
            list(proposal.get("scope_path", [])),
            proposal.get("after"),
        )
        layout = editor_layout(stage)
        decisions: dict[str, str] = {}
        drafts: dict[str, dict[str, Any]] = {}
        value_changes = {
            tuple(change["path"]): change
            for change in changes
            if change["kind"] == "value"
        }
        row_changes = {
            tuple(change["path"]): change
            for change in changes
            if change["kind"] in {"add_row", "remove_row"}
        }

        with ui.column().classes("w-full gap-4").mark("inline-ai-proposal"):
            ui.label("REVISÃO DA PROPOSTA DA IA").classes("eyebrow")
            ui.label(str(proposal.get("scope_label", "Âmbito selecionado"))).classes(
                "section-title"
            )
            ui.label(
                "As sugestões aparecem sob os valores atuais. Pode editá-las e "
                "aceitar ou rejeitar cada alteração antes de criar uma única versão."
            ).classes("text-sm muted")

            if not changes:
                ui.label(
                    "A proposta não contém alterações pedagógicas editáveis. "
                    "Os identificadores técnicos não são submetidos a revisão por IA."
                ).classes("soft-surface p-3 text-sm")

            for scalar in layout.fields:
                path = tuple(scalar.path)
                parent = (
                    value_at_path(artifact, scalar.path[:-1])
                    if scalar.path[:-1]
                    else artifact
                )
                field = FieldSpec(scalar.path[-1], scalar.label, scalar.kind)
                change = value_changes.get(path)
                with ui.card().classes("soft-surface w-full p-3"):
                    ui.label(scalar.label).classes("font-semibold")
                    ui.label("Atual").classes("text-xs muted")
                    ui.label(editor_field_value(parent, field) or "—").classes(
                        "text-sm whitespace-pre-wrap"
                    )
                    if change is not None:
                        ui.label("Sugestão da IA").classes(
                            "text-xs font-semibold mt-2"
                        )
                        holder = deepcopy(change.get("row_after") or {})
                        holder[field.key] = deepcopy(change.get("after"))
                        drafts[str(change["key"])] = holder
                        suggestion_control = self._render_manual_field(
                            holder,
                            FieldSpec(field.key, "Sugestão da IA", field.kind),
                        )
                        suggestion_control.mark(f"ai-change-{change['key']}")
                        self._proposal_decision_toggle(
                            decisions, str(change["key"])
                        )

            for table in layout.tables:
                rows = value_at_path(artifact, table.path)
                if not isinstance(rows, list):
                    continue
                table_row_changes = {
                    int(path[-1]): change
                    for path, change in row_changes.items()
                    if tuple(path[:-1]) == tuple(table.path)
                }
                has_row_decisions = bool(table_row_changes)
                with ui.column().classes("w-full gap-2"):
                    ui.label(table.title).classes("text-lg font-bold")
                    with ui.element("div").classes("manual-table-scroll"):
                        with ui.element("table").classes("manual-table"):
                            with ui.element("thead"):
                                with ui.element("tr"):
                                    for field in table.fields:
                                        with ui.element("th"):
                                            ui.label(field.label)
                                    if has_row_decisions:
                                        with ui.element("th"):
                                            ui.label("Decisão da linha")
                            with ui.element("tbody"):
                                for index, row in enumerate(rows):
                                    removal = table_row_changes.get(index)
                                    if removal is not None and removal["kind"] != "remove_row":
                                        removal = None
                                    with ui.element("tr").classes(
                                        "ai-proposal-remove-row" if removal else ""
                                    ):
                                        for field in table.fields:
                                            path = (*table.path, index, field.key)
                                            change = value_changes.get(path)
                                            with ui.element("td").classes(
                                                "ai-proposal-changed-cell"
                                                if change is not None
                                                else ""
                                            ):
                                                if change is not None:
                                                    ui.label("Atual").classes(
                                                        "text-xs muted"
                                                    )
                                                ui.label(
                                                    editor_field_value(row, field) or "—"
                                                ).classes("text-sm whitespace-pre-wrap")
                                                if change is not None:
                                                    ui.label("Sugestão da IA").classes(
                                                        "text-xs font-semibold mt-2"
                                                    )
                                                    holder = deepcopy(
                                                        change.get("row_after") or row
                                                    )
                                                    holder[field.key] = deepcopy(
                                                        change.get("after")
                                                    )
                                                    drafts[str(change["key"])] = holder
                                                    suggestion_control = self._render_manual_field(
                                                        holder,
                                                        field,
                                                        compact=True,
                                                    )
                                                    suggestion_control.mark(
                                                        f"ai-change-{change['key']}"
                                                    )
                                                    self._proposal_decision_toggle(
                                                        decisions,
                                                        str(change["key"]),
                                                    )
                                        if has_row_decisions:
                                            with ui.element("td").classes(
                                                "manual-row-action"
                                            ):
                                                if removal is not None:
                                                    ui.label(
                                                        "A IA propõe remover esta linha."
                                                    ).classes("text-xs font-semibold")
                                                    self._proposal_decision_toggle(
                                                        decisions,
                                                        str(removal["key"]),
                                                    )

                                additions = [
                                    change
                                    for change in table_row_changes.values()
                                    if change["kind"] == "add_row"
                                ]
                                for addition in additions:
                                    holder = deepcopy(addition.get("after") or {})
                                    drafts[str(addition["key"])] = holder
                                    with ui.element("tr").classes(
                                        "ai-proposal-new-row"
                                    ):
                                        for field in table.fields:
                                            with ui.element("td"):
                                                ui.label("Nova linha sugerida").classes(
                                                    "text-xs font-semibold"
                                                )
                                                if field.key == "id":
                                                    ui.label(
                                                        editor_field_value(holder, field)
                                                        or "A atribuir"
                                                    ).classes("text-sm")
                                                else:
                                                    self._render_manual_field(
                                                        holder,
                                                        field,
                                                        compact=True,
                                                    )
                                        if has_row_decisions:
                                            with ui.element("td").classes(
                                                "manual-row-action"
                                            ):
                                                self._proposal_decision_toggle(
                                                    decisions,
                                                    str(addition["key"]),
                                                )

            async def apply_selected_changes() -> None:
                selections: list[dict[str, Any]] = []
                for change in changes:
                    key = str(change["key"])
                    accepted = decisions.get(key, "Aceitar") == "Aceitar"
                    selection: dict[str, Any] = {"key": key, "accept": accepted}
                    if accepted and change["kind"] == "value":
                        holder = drafts.get(key, {})
                        selection["value"] = deepcopy(
                            holder.get(
                                str(change.get("field_key", "")),
                                change.get("after"),
                            )
                        )
                    elif accepted and change["kind"] == "add_row":
                        selection["value"] = deepcopy(
                            drafts.get(key, change.get("after"))
                        )
                    selections.append(selection)
                await self._handle_ai_proposal(
                    str(proposal["id"]),
                    True,
                    selections,
                )

            with ui.row().classes("w-full gap-2 flex-wrap mt-2"):
                apply_button = ui.button(
                    "Aplicar alterações aceites",
                    icon="check",
                    on_click=apply_selected_changes,
                ).props("unelevated no-caps").classes("primary-action")
                if not changes:
                    apply_button.disable()
                ui.button(
                    "Rejeitar todas as alterações",
                    icon="close",
                    on_click=lambda: self._handle_ai_proposal(
                        str(proposal["id"]), False
                    ),
                ).props("outline no-caps").classes("secondary-action")

    def _render_complete_resource_ai_proposal_review(
        self,
        state: dict[str, Any],
        proposal: dict[str, Any],
    ) -> None:
        """Revê uma proposta completa de recursos na mesma UI da edição manual."""

        proposed_artifact = deepcopy(proposal.get("after"))
        if not isinstance(proposed_artifact, dict):
            ui.label(
                "A proposta recebida não possui uma estrutura de recursos editável."
            ).classes("soft-surface p-3 text-sm")
            return
        proposed_artifact["selected_types"] = list(
            state.get("resource_types", [])
        )
        preview_state = deepcopy(state)
        preview_images = [
            deepcopy(item)
            for item in preview_state.get("generated_images", [])
            if isinstance(item, dict)
        ]
        known_ids = {str(item.get("id", "")) for item in preview_images}
        preview_images.extend(
            deepcopy(item)
            for item in proposal.get("generated_images", [])
            if isinstance(item, dict) and str(item.get("id", "")) not in known_ids
        )
        preview_state["generated_images"] = preview_images

        with ui.column().classes("w-full gap-4").mark(
            "resource-ai-proposal-review"
        ):
            ui.label("REVISÃO DA PROPOSTA DA IA").classes("eyebrow")
            ui.label("Recursos educativos propostos").classes("section-title")
            ui.label(
                "A proposta usa a mesma organização da edição manual. Reveja e edite "
                "os recursos selecionados antes de aplicar; os restantes não são "
                "apresentados nem guardados."
            ).classes("text-sm muted")
            self._render_resource_editor_tabs(
                preview_state,
                proposed_artifact,
                editor_layout("resources"),
            )

            with ui.row().classes("w-full gap-2 flex-wrap mt-2"):
                ui.button(
                    "Aplicar proposta editada",
                    icon="check",
                    on_click=lambda: self._handle_ai_proposal(
                        str(proposal["id"]),
                        True,
                        edited_after=proposed_artifact,
                    ),
                ).props("unelevated no-caps").classes("primary-action").mark(
                    "apply-edited-resource-proposal"
                )
                ui.button(
                    "Rejeitar toda a proposta",
                    icon="close",
                    on_click=lambda: self._handle_ai_proposal(
                        str(proposal["id"]), False
                    ),
                ).props("outline no-caps").classes("secondary-action")

    async def _create_complete_stage_with_ai(self, stage: str) -> None:
        if stage == "resources":
            self._open_resource_generation_confirmation()
            return
        await self._handle_ai_assistance(
            stage,
            [],
            "Toda a etapa",
            "Crie uma versão completa desta etapa com base no contexto da "
            "unidade curricular, no rascunho atual e nos artefactos anteriores.",
        )

    def _render_toolbar_help_button(self, context: str) -> None:
        ui.button(
            "?",
            on_click=lambda: self._open_toolbar_help_dialog(context),
        ).props(
            "outline round dense aria-label='Ajuda sobre os botões desta barra'"
        ).classes("stage-toolbar-help secondary-action font-bold").mark(
            "stage-toolbar-help", f"stage-toolbar-help-{context}"
        )

    def _open_toolbar_help_dialog(self, context: str) -> None:
        help_content: dict[str, tuple[str, list[tuple[str, str, str]], str]] = {
            "initial": (
                "Dados iniciais",
                [
                    (
                        "arrow_forward",
                        "Etapa seguinte",
                        "Cria a sessão ou, durante uma revisão, abre a formulação dos "
                        "resultados. Se existirem alterações por guardar, pede uma decisão.",
                    ),
                    (
                        "fact_check",
                        "Validar dados",
                        "Verifica localmente os campos obrigatórios e apresenta sugestões. "
                        "Cada observação pode ser selecionada para localizar o campo. "
                        "Não usa IA nem tem custo de API.",
                    ),
                    (
                        "auto_awesome",
                        "Gerar proposta inicial por IA",
                        "Pede ao fornecedor selecionado uma proposta para completar os dados "
                        "iniciais. O docente deve rever os campos antes de avançar.",
                    ),
                    (
                        "play_arrow",
                        "Iniciar desenho curricular alinhado",
                        "Guarda o formulário no fim da página e inicia o percurso sem gerar "
                        "automaticamente as etapas seguintes.",
                    ),
                ],
                "O fornecedor só recebe conteúdo quando é acionada a proposta por IA.",
            ),
            "authoring": (
                "Autoria da etapa",
                [
                    (
                        "arrow_back",
                        "Etapa anterior / Etapa seguinte",
                        "Navega sem executar IA e sem exigir que o conteúdo esteja completo.",
                    ),
                    (
                        "edit",
                        "Editar campos e tabelas",
                        "Abre a edição manual do artefacto. Esta ação não pertence à "
                        "assistência com IA e não tem custo de API.",
                    ),
                    (
                        "auto_fix_high",
                        "Criar etapa completa com IA",
                        "Pede uma proposta para todo o artefacto. Nada é aplicado sem revisão "
                        "e aceitação explícitas.",
                    ),
                    (
                        "auto_awesome",
                        "Pedir propostas à IA",
                        "Abre um diálogo para escolher uma etapa, tabela, linha ou campo e "
                        "escrever uma instrução localizada.",
                    ),
                    (
                        "fact_check",
                        "Verificar esta etapa com IA",
                        "Obtém um parecer facultativo, sem alterar o conteúdo nem bloquear a "
                        "navegação. Cada observação localiza e realça o conteúdo relacionado.",
                    ),
                ],
                "As propostas de IA só se tornam versões depois da decisão do docente.",
            ),
            "editing": (
                "Edição manual",
                [
                    (
                        "close",
                        "Cancelar edição",
                        "Descarta as alterações ainda não guardadas e mantém a versão ativa.",
                    ),
                    (
                        "save",
                        "Guardar rascunho",
                        "Guarda uma nova versão manual. Não executa IA; etapas posteriores "
                        "podem ficar assinaladas para revisão.",
                    ),
                ],
                "A navegação fica desativada enquanto a edição manual está aberta.",
            ),
            "final": (
                "Validação final",
                [
                    (
                        "arrow_back",
                        "Etapa anterior",
                        "Regressa aos recursos educativos para consulta ou alteração.",
                    ),
                    (
                        "verified",
                        "Verificação global obrigatória",
                        "Aplica controlos determinísticos à estrutura, cobertura e coerência "
                        "antes de permitir concluir e exportar.",
                    ),
                ],
                "A etapa seguinte só fica disponível através da conclusão da validação.",
            ),
        }
        title, items, note = help_content.get(context, help_content["authoring"])
        with ui.dialog() as dialog, ui.card().classes(
            "w-full max-w-2xl p-6 gap-4"
        ).mark("toolbar-help-dialog"):
            ui.label("AJUDA DA BARRA DE FERRAMENTAS").classes("eyebrow")
            ui.label(title).classes("section-title")
            with ui.column().classes("w-full gap-2"):
                for icon, item_title, description in items:
                    with ui.row().classes(
                        "toolbar-help-item soft-surface w-full items-start gap-3"
                    ):
                        ui.icon(icon, color="primary", size="1.5rem")
                        with ui.column().classes("gap-0 flex-1"):
                            ui.label(item_title).classes("font-semibold")
                            ui.label(description).classes("text-sm muted")
            ui.label(note).classes("text-sm muted")
            with ui.row().classes("w-full justify-end"):
                ui.button("Fechar", on_click=dialog.close).props(
                    "unelevated no-caps"
                ).classes("primary-action").mark("close-toolbar-help")
        dialog.open()

    def _open_ai_assistance_dialog(
        self,
        stage: str,
        state: dict[str, Any],
    ) -> None:
        scopes = assistance_scope_options(stage, state[stage])
        scope_by_key = {str(index): item for index, item in enumerate(scopes)}
        with ui.dialog() as dialog, ui.card().classes(
            "w-full max-w-2xl p-6 gap-4"
        ).mark("ai-assistance-request"):
            ui.label("ASSISTÊNCIA COM IA").classes("eyebrow").mark(
                "ai-assistance-heading"
            )
            ui.label("Pedir uma proposta localizada").classes("section-title")
            ui.label(
                "Escolha exatamente a parte que pode ser proposta pela IA. O restante "
                "artefacto não será aplicado nem substituído."
            ).classes("text-sm muted")
            scope = ui.select(
                {key: item["label"] for key, item in scope_by_key.items()},
                label="Âmbito da assistência",
                value="0",
            ).props("outlined options-dense").classes("w-full")
            instruction = ui.textarea(
                "O que pretende que a IA proponha?",
                placeholder=(
                    "Ex.: clarificar o texto sem alterar o nível taxonómico; "
                    "propor duas linhas adicionais; rever a coerência desta tabela."
                ),
            ).props("outlined autogrow").classes("w-full")

            async def ask_for_proposal() -> None:
                selected = scope_by_key.get(str(scope.value or "0"), scopes[0])
                dialog.close()
                await self._handle_ai_assistance(
                    stage,
                    list(selected["path"]),
                    str(selected["label"]),
                    str(instruction.value or ""),
                )

            with ui.row().classes("w-full justify-end gap-2 flex-wrap"):
                ui.button("Cancelar", on_click=dialog.close).props(
                    "flat no-caps"
                ).mark("cancel-ai-assistance")
                ui.button(
                    "Pedir propostas à IA",
                    icon="auto_awesome",
                    on_click=ask_for_proposal,
                ).props("unelevated no-caps").classes("primary-action").mark(
                    "submit-ai-assistance-request"
                )
        dialog.open()

    def _open_manual_save_dialog(
        self,
        state: dict[str, Any],
        stage: str,
    ) -> None:
        impact = self.service.revision_impact(state, stage)
        with ui.dialog() as dialog, ui.card().classes(
            "w-full max-w-2xl p-6 gap-4"
        ).mark("stage-actions"):
            ui.label("EDIÇÃO MANUAL").classes("eyebrow")
            ui.label("Guardar rascunho").classes("section-title")
            ui.label(
                f"Será criada a versão {impact['next_version']} sem utilizar a IA. "
                "Os passos seguintes serão preservados e, quando aplicável, "
                "assinalados para revisão."
            ).classes("text-sm muted")
            reason = ui.textarea(
                "Nota da edição — opcional",
                placeholder="Explique resumidamente o motivo da alteração.",
            ).props("outlined autogrow").classes("w-full")

            async def save_manual_version() -> None:
                if self.manual_edit_artifact is None:
                    dialog.close()
                    ui.notify("A edição manual já não está ativa.", type="warning")
                    return
                dialog.close()
                await self.handle_manual_edit(
                    stage,
                    self.manual_edit_artifact,
                    str(reason.value or ""),
                )

            with ui.row().classes("w-full justify-end gap-2 flex-wrap"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Guardar rascunho"
                    if is_manual_first(state)
                    else "Guardar nova versão",
                    icon="save",
                    on_click=save_manual_version,
                ).props("unelevated no-caps").classes("primary-action").mark(
                    "confirm-manual-save"
                )
        dialog.open()

    def _render_stage_toolbar(
        self,
        state: dict[str, Any],
        stage: str,
        *,
        editing: bool,
        proposal: dict[str, Any] | None,
    ) -> None:
        current_index = STAGE_ORDER.index(stage)
        with ui.card().classes("stage-toolbar surface w-full").mark("stage-toolbar"):
            with ui.row().classes(
                "stage-toolbar-main w-full items-center gap-2 flex-wrap"
            ):
                previous_action = (
                    self.show_initial_session_editor
                    if current_index == 0
                    else lambda: self._navigate_manual_stage(
                        STAGE_ORDER[current_index - 1]
                    )
                )
                previous_button = ui.button(
                    "Etapa anterior",
                    icon="arrow_back",
                    on_click=previous_action,
                ).props("outline no-caps").classes("secondary-action")
                with ui.column().classes("stage-toolbar-context gap-0 px-1"):
                    ui.label(f"ETAPA {current_index + 2:02d} DE {DISPLAY_STAGE_COUNT:02d}").classes(
                        "eyebrow"
                    )
                    ui.label(STAGE_LABELS[stage]).classes("toolbar-stage-title")
                next_button = ui.button(
                    "Etapa seguinte",
                    icon="arrow_forward",
                    on_click=lambda: self._navigate_manual_stage(
                        STAGE_ORDER[current_index + 1]
                    ),
                ).props("unelevated no-caps icon-right").classes("primary-action")

                with ui.row().classes(
                    "stage-toolbar-controls items-center gap-2 flex-wrap"
                ):
                    if editing:
                        previous_button.disable()
                        next_button.disable()
                        ui.label("EDIÇÃO MANUAL").classes(
                            "eyebrow stage-toolbar-ai-label"
                        )
                        ui.button(
                            "Cancelar edição",
                            icon="close",
                            on_click=self._cancel_manual_edit,
                        ).props("outline no-caps").classes("secondary-action")
                        ui.button(
                            "Guardar rascunho"
                            if is_manual_first(state)
                            else "Guardar nova versão",
                            icon="save",
                            on_click=lambda: self._open_manual_save_dialog(
                                state, stage
                            ),
                        ).props("unelevated no-caps").classes("primary-action")
                        self._render_toolbar_help_button("editing")
                    else:
                        edit_button = ui.button(
                            "Editar campos e tabelas",
                            icon="edit",
                            on_click=lambda: self._start_manual_edit(stage),
                        ).props("outline no-caps").classes(
                            "secondary-action"
                        ).mark("edit-artifact-content")
                        self._render_toolbar_help_button("authoring")

            if editing:
                return

            with ui.row().classes(
                "stage-toolbar-actions items-center gap-2 flex-wrap"
            ):
                ui.label("ASSISTÊNCIA COM IA").classes(
                    "eyebrow stage-toolbar-ai-label"
                ).mark("ai-assistance-heading")
                create_button = ui.button(
                    "Criar etapa completa com IA",
                    icon="auto_fix_high",
                    on_click=lambda: self._create_complete_stage_with_ai(stage),
                ).props("outline no-caps").classes("secondary-action").mark(
                    "create-ai-version"
                )
                proposal_button = ui.button(
                    "Pedir propostas à IA",
                    icon="auto_awesome",
                    on_click=lambda: self._open_ai_assistance_dialog(stage, state),
                ).props("outline no-caps").classes("secondary-action").mark(
                    "open-ai-assistance"
                )
                verify_button = ui.button(
                    "Verificar esta etapa com IA",
                    icon="fact_check",
                    on_click=lambda: self._handle_ai_verification(stage),
                ).props("outline no-caps").classes("secondary-action").mark(
                    "verify-stage-with-ai"
                )
                if proposal is not None:
                    create_button.disable()
                    proposal_button.disable()
                    verify_button.disable()
                    edit_button.disable()

    def _render_authoring_view(self, state: dict[str, Any]) -> None:
        stage = state["current_stage"]
        proposal = self._pending_ai_proposal(state, stage)
        editing = (
            self.manual_edit_stage == stage and self.manual_edit_artifact is not None
        )
        with ui.column().classes("w-full gap-5"):
            if is_manual_first(state) or editing:
                self._render_stage_toolbar(
                    state,
                    stage,
                    editing=editing,
                    proposal=proposal,
                )
            if not editing and is_manual_first(state):
                self._render_manual_authoring_card(state, stage)
            elif not editing and not is_manual_first(state):
                self._render_decision_card(state)
            with ui.card().classes(
                f"surface artifact-card stage-artifact-focus "
                f"stage-artifact-{stage} w-full"
            ).mark(
                "artifact-content"
            ):
                if editing:
                    self._render_inline_manual_editor(stage)
                elif proposal:
                    self._render_ai_proposal_review(state, stage, proposal)
                else:
                    artifact_markdown = render_current_artifact(state)
                    artifact_title, separator, artifact_body = artifact_markdown.partition(
                        "\n\n"
                    )
                    with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                        ui.markdown(artifact_title).classes(
                            "artifact-markdown artifact-heading"
                        )
                    if separator and artifact_body:
                        ui.markdown(artifact_body, extras=["tables"]).classes(
                            "artifact-markdown"
                        )
                    if stage == "resources":
                        self._render_resource_detail_tabs(state, state[stage])

    @staticmethod
    def _structured_focus_plan(
        state: dict[str, Any],
        stage: str,
        target_key: str,
    ) -> tuple[str, str]:
        """Traduz um destino curricular num seletor exato, sem procurar texto."""

        root = f".stage-artifact-{stage}"
        heading = f"{root} .artifact-heading, {root} .artifact-markdown h1:first-of-type"
        if target_key == STAGE_ROOT_TARGET:
            return heading, ""
        artifact = active_stage_artifact(state, stage)

        def row_selector(index: int, *, table: int = 1, panel: str = "") -> str:
            container = (
                f".validation-resource-panel-{panel} " if panel else f"{root} "
            )
            return (
                f"{container}.artifact-markdown table:nth-of-type({table}) "
                f"tbody tr:nth-child({index + 1})"
            )

        def matching_index(items: list[Any], key: str) -> int | None:
            requested = target_key.casefold()
            return next(
                (
                    index
                    for index, item in enumerate(items)
                    if isinstance(item, dict)
                    and str(item.get(key, "")).strip().casefold() == requested
                ),
                None,
            )

        if stage == "curriculum_analysis" and isinstance(artifact, dict):
            special = {
                "__summary__": f"{root} .artifact-markdown",
            }
            if target_key in special:
                return special[target_key], ""
            index = matching_index(artifact.get("contents", []), "id")
            return (row_selector(index), "") if index is not None else (heading, "")
        if stage in {
            "learning_outcomes",
            "teaching_activities",
            "assessment_activities",
        } and isinstance(artifact, list):
            index = matching_index(artifact, "id")
            return (row_selector(index), "") if index is not None else (heading, "")
        if stage == "pedagogical_design" and isinstance(artifact, dict):
            if target_key.startswith("LESSON:"):
                index = int(target_key.partition(":")[2]) - 1
                return row_selector(index), ""
            return heading, ""
        if stage == "resources" and isinstance(artifact, dict):
            tab_by_target = {
                "RESOURCE:presentation": "presentation",
                "RESOURCE:worksheet": "worksheet",
                "RESOURCE:test": "test",
                "RESOURCE:practical": "practical",
            }
            if target_key in tab_by_target:
                tab = tab_by_target[target_key]
                return (
                    f".validation-resource-panel-{tab}",
                    f".validation-resource-tab-{tab}",
                )
            if target_key.startswith("SLIDE:"):
                number = int(target_key.partition(":")[2])
                return (
                    f".validation-resource-panel-presentation "
                    f".validation-target-slide-{number}",
                    ".validation-resource-tab-presentation",
                )
            if target_key.startswith("WORKSHEET:"):
                index = int(target_key.partition(":")[2]) - 1
                return (
                    row_selector(index, panel="worksheet"),
                    ".validation-resource-tab-worksheet",
                )
            if target_key.startswith("PRACTICAL_CRITERION:"):
                index = int(target_key.partition(":")[2]) - 1
                return (
                    row_selector(index, table=2, panel="practical"),
                    ".validation-resource-tab-practical",
                )
            if target_key.startswith("PRACTICAL:"):
                index = int(target_key.partition(":")[2]) - 1
                return (
                    row_selector(index, panel="practical"),
                    ".validation-resource-tab-practical",
                )
            questions = artifact.get("test", {}).get("questions", [])
            index = matching_index(questions, "id")
            if index is not None:
                return (
                    row_selector(index, panel="test"),
                    ".validation-resource-tab-test",
                )
        return heading, ""

    async def _focus_structured_target(
        self,
        stage: str,
        target_key: str,
    ) -> None:
        if not self.state:
            return
        selector, activate_selector = self._structured_focus_plan(
            self.state,
            stage,
            target_key,
        )
        await self._scroll_and_highlight(
            selector,
            activate_selector=activate_selector,
        )

    async def _focus_stage_finding(self, finding: dict[str, Any]) -> None:
        if not self.state:
            return
        stage = str(self.state.get("current_stage", ""))
        artifact = active_stage_artifact(self.state, stage)
        target_key = resolve_validation_target(stage, artifact, finding)
        await self._focus_structured_target(stage, target_key)

    async def _focus_final_validation_result(
        self,
        result: dict[str, Any],
    ) -> None:
        if not self.state:
            return
        target_stage = str(result.get("target_stage", ""))
        if target_stage not in STAGE_ORDER[:-1]:
            return
        target_key = str(result.get("target_key", STAGE_ROOT_TARGET))
        stage_changed = self.state.get("current_stage") != target_stage
        if stage_changed:
            selector, activate_selector = self._structured_focus_plan(
                self.state,
                target_stage,
                target_key,
            )
            await self._arm_scroll_and_highlight(
                selector,
                activate_selector=activate_selector,
            )
            await self._navigate_manual_stage(
                target_stage,
                notice="Controlo localizado na etapa correspondente.",
            )
        if (
            not stage_changed
            and self.state
            and self.state.get("current_stage") == target_stage
        ):
            await self._focus_structured_target(target_stage, target_key)

    def _render_manual_authoring_card(
        self,
        state: dict[str, Any],
        stage: str,
    ) -> None:
        proposal = self._pending_ai_proposal(state, stage)
        reviews = state.get("ai_reviews", {}).get(stage, [])
        if stage != "resources" and proposal is None and not reviews:
            return
        with ui.card().classes(
            "surface decision-card teacher-control-card w-full"
        ).mark(
            "teacher-control"
        ):
            if stage == "resources":
                ui.label("RECURSOS A PREPARAR").classes("eyebrow")
                ui.label(
                    "Escolha os recursos desta etapa. Guardar a seleção não executa a IA."
                ).classes("text-sm muted")
                if state.get("source_images"):
                    ui.label(
                        "As imagens extraídas dos documentos ficam disponíveis no "
                        "seletor de cada slide. Ao criar a apresentação, a IA analisa-as "
                        "e reutiliza as que forem adequadas antes de propor novas imagens."
                    ).classes("text-sm muted")
                selected_resources = set(state.get("resource_types", []))
                resource_checks = {
                    resource_type: ui.checkbox(
                        resource_type,
                        value=resource_type in selected_resources,
                    )
                    for resource_type in RESOURCE_TYPES
                }

                async def save_resource_settings() -> None:
                    selected = [
                        name
                        for name, checkbox in resource_checks.items()
                        if checkbox.value
                    ]
                    try:
                        self.state, message = await run.io_bound(
                            self.service.update_resource_settings,
                            self.state,
                            selected,
                        )
                        self.show_workspace(message)
                        self.refresh_sessions()
                    except USER_ERRORS as error:
                        self._show_error(error)

                ui.button(
                    "Guardar seleção de recursos",
                    icon="save",
                    on_click=save_resource_settings,
                ).props("outline no-caps").classes("secondary-action w-full")
                ui.separator().classes("my-2")

            if proposal is not None:
                ui.separator().classes("my-2")
                ui.label("PROPOSTA PENDENTE").classes("eyebrow")
                ui.label(str(proposal.get("scope_label", "Âmbito selecionado"))).classes(
                    "font-semibold"
                )
                ui.label(
                    "Reveja a sugestão diretamente nos campos e tabelas abaixo."
                ).classes("text-sm muted")

            if reviews:
                latest = reviews[-1]
                ui.separator().classes("my-2")
                if not ai_review_is_current(state, stage, latest):
                    ui.label(
                        "VERIFICAÇÃO FACULTATIVA DA IA DESATUALIZADA"
                    ).classes("eyebrow")
                    ui.label(
                        "Os artefactos foram alterados depois deste parecer. Peça uma "
                        "nova verificação para obter observações sobre a versão atual."
                    ).classes("text-sm muted")
                else:
                    ui.label("ÚLTIMA VERIFICAÇÃO FACULTATIVA DA IA").classes(
                        "eyebrow"
                    )
                    findings = latest.get("findings", [])
                    if not findings:
                        ui.label("A IA não assinalou problemas.").classes("text-sm")
                    else:
                        ui.label(
                            "Selecione uma observação para localizar o conteúdo relacionado."
                        ).classes("text-xs muted")
                    if findings:
                        with ui.column().classes("validation-results-list"):
                            for index, finding in enumerate(findings):
                                severity = (
                                    "Bloqueante"
                                    if finding.get("severity") == "blocking"
                                    else "Aviso"
                                )
                                kind = (
                                    "issue"
                                    if finding.get("severity") == "blocking"
                                    else "suggestion"
                                )
                                self._render_validation_result_button(
                                    f"{severity} — {finding.get('criterion', '')}: "
                                    f"{finding.get('message', '')}",
                                    kind,
                                    f"ai-review-finding-{index}",
                                    lambda selected=deepcopy(finding): (
                                        self._focus_stage_finding(selected)
                                    ),
                                )
                    ui.label(
                        "Este parecer não bloqueia a passagem à etapa seguinte."
                    ).classes("text-xs muted")


    def _open_resource_generation_confirmation(self) -> None:
        selected = list((self.state or {}).get("resource_types", []))
        selected_text = ", ".join(selected) or "nenhum recurso"
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl p-6 gap-4"):
            ui.label("GERAR RECURSOS COM IA").classes("eyebrow")
            ui.label("Confirmar geração dos recursos selecionados").classes(
                "section-title"
            )
            ui.label(
                "Esta ação contacta o fornecedor de IA e pode originar várias "
                "chamadas, uma por tipo de recurso. A apresentação também pode "
                "originar chamadas de geração de imagens."
            ).classes("text-sm")
            ui.label(f"Recursos: {selected_text}.").classes(
                "soft-surface p-3 text-sm font-medium"
            )
            ui.label(
                "O conteúdo gerado continuará pendente até rever e aceitar a proposta."
            ).classes("text-sm muted")

            async def confirm() -> None:
                dialog.close()
                await self._handle_ai_assistance(
                    "resources",
                    [],
                    "Toda a etapa",
                    "Crie uma versão completa desta etapa com base no contexto da "
                    "unidade curricular, no rascunho atual e nos artefactos anteriores.",
                )

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Confirmar geração",
                    icon="auto_fix_high",
                    on_click=confirm,
                ).props("unelevated no-caps").classes("primary-action").mark(
                    "confirm-resource-generation"
                )
        dialog.open()

    async def _handle_ai_assistance(
        self,
        stage: str,
        scope_path: list[str | int],
        scope_label: str,
        instruction: str,
    ) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        self._show_busy(
            f"A preparar uma proposta para {scope_label}…",
            progress_updates,
            "A aguardar o fornecedor de IA…",
        )
        try:
            self.state, message = await run.io_bound(
                self.service.request_assistance,
                self.state,
                stage,
                scope_path,
                scope_label,
                instruction,
            )
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    async def _handle_ai_proposal(
        self,
        proposal_id: str,
        accept: bool,
        selections: list[dict[str, Any]] | None = None,
        *,
        edited_after: Any = None,
    ) -> None:
        # O navegador pode conservar o cartão anterior durante uma reconexão ao
        # servidor. Nesse caso, a decisão persistida é soberana e basta redesenhar.
        if self._close_decided_ai_proposal_review(proposal_id):
            return
        try:
            self.state, message = await run.io_bound(
                self.service.decide_assistance,
                self.state,
                proposal_id,
                accept,
                selections,
                edited_after,
            )
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)

    async def _handle_ai_verification(self, stage: str) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        self._show_busy(
            f"A verificar «{STAGE_LABELS[stage]}» com IA…",
            progress_updates,
            "A aguardar o parecer facultativo da IA…",
        )
        try:
            self.state, message = await run.io_bound(
                self.service.verify_stage,
                self.state,
                stage,
            )
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    def _render_final_validation_view(self, state: dict[str, Any]) -> None:
        with ui.column().classes("w-full gap-5"):
            with ui.card().classes("stage-toolbar surface w-full").mark(
                "stage-toolbar", "final-stage-toolbar"
            ):
                with ui.row().classes(
                    "stage-toolbar-main w-full items-center gap-2 flex-wrap"
                ):
                    ui.button(
                        "Etapa anterior",
                        icon="arrow_back",
                        on_click=(
                            lambda: self._navigate_manual_stage("resources")
                            if is_manual_first(state)
                            else self._view_stage("resources")
                        ),
                    ).props("outline no-caps").classes("secondary-action")
                    with ui.column().classes("stage-toolbar-context gap-0 px-1"):
                        ui.label(
                            f"ETAPA {DISPLAY_STAGE_COUNT:02d} DE "
                            f"{DISPLAY_STAGE_COUNT:02d}"
                        ).classes("eyebrow")
                        ui.label(STAGE_LABELS["final_validation"]).classes(
                            "toolbar-stage-title"
                        )
                    ui.button("Etapa seguinte", icon="arrow_forward").props(
                        "unelevated no-caps icon-right disable"
                    ).classes("primary-action")
                    with ui.row().classes(
                        "stage-toolbar-controls items-center gap-2"
                    ):
                        self._render_toolbar_help_button("final")
                with ui.row().classes(
                    "stage-toolbar-actions items-center gap-2 flex-wrap"
                ):
                    ui.label("VERIFICAÇÃO GLOBAL OBRIGATÓRIA").classes(
                        "eyebrow stage-toolbar-ai-label"
                    )
            with ui.element("div").classes("final-hero w-full"):
                ui.label("VALIDAÇÃO FINAL").classes("text-xs tracking-widest font-bold opacity-75")
                ui.label("Confirme a estrutura e o alinhamento antes de concluir.").classes(
                    "text-3xl font-extrabold mt-2"
                )
                ui.label(
                    "Este ecrã é independente das etapas de autoria e apresenta os "
                    "controlos determinísticos que têm de passar antes da conclusão."
                ).classes("mt-2 opacity-85")
            self._render_decision_card(state, final=True)
            with ui.card().classes("surface artifact-card w-full").mark(
                "artifact-content"
            ):
                artifact = state.get("final_validation", {})
                rendered = render_current_artifact(state)
                introduction = rendered.partition("\n\n|")[0]
                ui.markdown(introduction).classes("artifact-markdown")
                ui.label("CONTROLOS DA ESTRUTURA E DO ALINHAMENTO").classes(
                    "eyebrow mt-3"
                )
                ui.label(
                    "Selecione um controlo para abrir a etapa onde pode consultar ou corrigir o conteúdo."
                ).classes("text-xs muted")
                with ui.column().classes("validation-results-list mt-2"):
                    for check in artifact.get("checks", []):
                        self._render_validation_result_button(
                            f"{check.get('label', '')}: {check.get('detail', '')}",
                            "pass" if check.get("passed") else "issue",
                            f"final-validation-check-{check.get('id', '')}",
                            lambda selected=deepcopy(check): (
                                self._focus_final_validation_result(selected)
                            ),
                        )
                resource_checks = artifact.get("resource_quality_checks", [])
                if resource_checks:
                    ui.label("QUALIDADE AUTOMÁTICA DOS RECURSOS").classes(
                        "eyebrow mt-5"
                    )
                    with ui.column().classes("validation-results-list mt-2"):
                        for check in resource_checks:
                            status = str(check.get("status", "warning"))
                            kind = (
                                "pass"
                                if status == "pass"
                                else "issue"
                                if status == "error"
                                else "suggestion"
                            )
                            self._render_validation_result_button(
                                f"{check.get('label', '')}: {check.get('detail', '')}",
                                kind,
                                f"resource-quality-check-{check.get('id', '')}",
                                lambda selected=deepcopy(check): (
                                    self._focus_final_validation_result(selected)
                                ),
                            )

    def _render_completed_view(self, state: dict[str, Any]) -> None:
        with ui.card().classes("surface complete-hero w-full items-center gap-3"):
            ui.icon("verified", size="4rem", color="positive")
            ui.label("Sessão pedagógica concluída").classes("text-3xl font-extrabold")
            ui.label(
                "A estrutura foi validada. Pode agora exportar os recursos e a rastreabilidade."
            ).classes("muted text-base")
            ui.label("Formato dos documentos editáveis").classes(
                "text-sm font-semibold mt-3"
            )
            format_control = ui.toggle(
                EXPORT_DOCUMENT_FORMAT_CHOICES,
                value=self.export_document_format,
            ).props("spread no-caps").classes("full-control max-w-2xl")
            format_control.on_value_change(
                lambda event: setattr(
                    self,
                    "export_document_format",
                    str(event.value or "word"),
                )
            )
            ui.label(
                "A escolha aplica-se ao programa da UC, ficha de aula, teste e "
                "atividade prática. A apresentação mantém o formato PowerPoint. "
                + (
                    "Nesta instalação, cada ficheiro LaTeX é também compilado para PDF."
                    if LATEX_PDF_ENABLED
                    else "A compilação automática para PDF não está ativa nesta instalação."
                )
            ).classes("muted text-xs max-w-2xl text-center")
            ui.button(
                "Exportar pacote de recursos",
                icon="download",
                on_click=self.handle_export,
            ).props("unelevated no-caps size=lg").classes("primary-action px-6 mt-2")
            if is_manual_first(state):
                ui.button(
                    "Reabrir explicitamente para edição",
                    icon="edit_note",
                    on_click=self._open_completed_reopen_dialog,
                ).props("outline no-caps").classes("secondary-action").mark(
                    "reopen-completed-session"
                )
        with ui.card().classes("surface artifact-card w-full"):
            ui.markdown(render_current_artifact(state), extras=["tables"]).classes(
                "artifact-markdown"
            )

    def _open_completed_reopen_dialog(self) -> None:
        if not self.state or self.state.get("status") != "completed":
            self._show_error(ValueError("A sessão já não está concluída."))
            return
        options = {stage: STAGE_LABELS[stage] for stage in STAGE_ORDER[:-1]}
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl p-6 gap-4"):
            ui.label("REABERTURA EXPLÍCITA").classes("eyebrow")
            ui.label("Voltar à autoria manual").classes("section-title")
            ui.label(
                "A barra permanece em modo de consulta para evitar cliques acidentais. "
                "Ao confirmar, a exportação ficará temporariamente indisponível até uma "
                "nova verificação global."
            ).classes("text-sm muted")
            stage_select = ui.select(
                options,
                value=STAGE_ORDER[0],
                label="Etapa a editar",
            ).props("outlined options-dense").classes("w-full")
            reason = ui.textarea(
                "Motivo da reabertura",
                placeholder="Descreva a alteração que pretende efetuar.",
            ).props("outlined autogrow").classes("w-full")

            async def confirm() -> None:
                clean_reason = str(reason.value or "").strip()
                if not clean_reason:
                    ui.notify("Indique o motivo da reabertura.", type="warning")
                    return
                dialog.close()
                await self.handle_reopen_stage(str(stage_select.value), clean_reason)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Confirmar reabertura",
                    icon="edit_note",
                    on_click=confirm,
                ).props("unelevated no-caps").classes("primary-action")
        dialog.open()

    def _render_decision_card(self, state: dict[str, Any], final: bool = False) -> None:
        manual = is_manual_first(state)
        with ui.card().classes("surface decision-card w-full").mark(
            "teacher-decision"
        ):
            ui.label(
                "VERIFICAÇÃO GLOBAL OBRIGATÓRIA"
                if manual and final
                else "DECISÃO DO DOCENTE"
            ).classes("eyebrow")
            ui.label(
                "Validação final" if final else "Rever a proposta"
            ).classes("section-title")
            ui.label(
                (
                    "Esta verificação é determinística e não chama um LLM. "
                    "A sessão só pode ser concluída quando todos os controlos passam."
                )
                if manual and final
                else "A IA não avança sem a sua decisão."
            ).classes("text-sm muted mb-2")

            decision = None
            feedback = None
            if final:
                ui.label(
                    (
                        "Pode selecionar qualquer etapa na barra superior, corrigi-la "
                        "manualmente e regressar aqui para repetir a verificação."
                        if manual
                        else "Para rever uma componente, selecione primeiro a respetiva "
                        "etapa na barra superior, consulte-a e escolha Reformular."
                    )
                ).classes("soft-surface p-3 text-sm")
            else:
                ui.button(
                    "Editar a tabela manualmente",
                    icon="edit",
                    on_click=lambda: self._start_manual_edit(
                        state["current_stage"]
                    ),
                ).props("outline no-caps").classes(
                    "secondary-action w-full mb-2"
                )
                decision = ui.toggle(
                    {"approve": "Aprovar", "revise": "Reformular"},
                    value="approve",
                ).props("spread no-caps").classes("full-control")

                with ui.column().classes("w-full gap-3") as revision_area:
                    feedback = ui.textarea(
                        "Feedback para a reformulação",
                        placeholder="Explique claramente a alteração necessária.",
                    ).props("outlined autogrow").classes("full-control")
                revision_area.set_visibility(False)
                decision.on_value_change(
                    lambda event: revision_area.set_visibility(
                        event.value == "revise"
                    )
                )

            if state["current_stage"] == "resources":
                ui.separator().classes("my-2")
                ui.label("Recursos confirmados").classes("font-semibold")
                with ui.row().classes("gap-1"):
                    for resource in state.get("resource_types", []):
                        ui.chip(resource).classes("info-chip")

            async def submit_decision() -> None:
                await self.handle_review(
                    "approve" if final else str(decision.value),
                    "" if final else str(feedback.value or ""),
                    state["current_stage"],
                    None,
                )

            ui.button(
                "Concluir validação" if final else "Registar decisão e continuar",
                icon="arrow_forward",
                on_click=submit_decision,
            ).props("unelevated no-caps icon-right").classes("primary-action w-full mt-3")

    async def handle_review(
        self,
        decision: str,
        feedback: str,
        revision_stage: str,
        resource_types: list[str] | None,
    ) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        if decision == "revise":
            target_label = STAGE_LABELS.get(revision_stage, "a etapa selecionada")
            action = f"A reformular «{target_label}»…"
        else:
            current_stage = str((self.state or {}).get("current_stage", ""))
            current_index = (
                STAGE_ORDER.index(current_stage)
                if current_stage in STAGE_ORDER
                else len(STAGE_ORDER) - 1
            )
            if current_index < len(STAGE_ORDER) - 1:
                next_label = STAGE_LABELS[STAGE_ORDER[current_index + 1]]
                action = f"A preparar «{next_label}»…"
            else:
                action = "A concluir a validação…"
        self._show_busy(
            action,
            progress_updates,
            "A operação foi iniciada…",
        )
        try:
            self.state, message = await run.io_bound(
                self.service.review_session,
                self.state,
                decision,
                feedback,
                revision_stage,
                resource_types,
                progress_updates.put,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.manual_edit_stage_context = {}
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    async def handle_reopen_stage(self, target_stage: str, feedback: str) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        manual = bool(self.state and is_manual_first(self.state))
        self._show_busy(
            (
                f"A reabrir «{STAGE_LABELS[target_stage]}» para edição…"
                if manual
                else f"A criar uma nova versão de «{STAGE_LABELS[target_stage]}»…"
            ),
            progress_updates,
            "A operação foi iniciada…",
        )
        try:
            self.state, message = await run.io_bound(
                self.service.reopen_session,
                self.state,
                target_stage,
                feedback,
                progress_updates.put,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()

    async def handle_manual_edit(
        self,
        target_stage: str,
        artifact: Any,
        reason: str,
    ) -> bool:
        self._show_busy("A validar e guardar a edição manual…")
        try:
            self.state, message = await run.io_bound(
                self.service.save_manual_edit,
                self.state,
                target_stage,
                artifact,
                reason,
                self.manual_edit_stage_context,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.manual_edit_stage_context = {}
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.show_workspace(message)
            self.refresh_sessions()
            return True
        except USER_ERRORS as error:
            self._show_error(error)
            return False
        finally:
            self._hide_busy()

    def _render_history_and_audit(self, state: dict[str, Any]) -> None:
        with ui.card().classes("surface w-full p-0"):
            with ui.expansion(
                "Versões e rastreabilidade",
                caption="Consultar histórico, restauros e decisões registadas",
                icon="history",
                value=False,
            ).props("dense").classes("w-full").mark("history-audit-expansion"):
                with ui.tabs().props("no-caps align=left").classes("w-full") as tabs:
                    history_tab = ui.tab("history", label="Versões", icon="history")
                    audit_tab = ui.tab("audit", label="Rastreabilidade", icon="route")
                with ui.tab_panels(tabs, value=history_tab).classes("w-full"):
                    with ui.tab_panel(history_tab).classes("px-0"):
                        choices = history_choices(state)
                        options = {value: label for label, value in choices}
                        selected = current_history_value(state)
                        restore_button = None
                        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                            history_select = ui.select(
                                options,
                                value=selected,
                                label="Etapa e versão",
                            ).classes("full-control flex-1 min-w-64").mark(
                                "history-version-select"
                            )
                            if is_manual_first(state) and choices:
                                restore_button = ui.button(
                                    "Restaurar versão selecionada",
                                    icon="restore",
                                    on_click=lambda: self._open_history_restore_dialog(
                                        str(history_select.value or "")
                                    ),
                                ).props("outline no-caps").classes(
                                    "secondary-action"
                                ).mark("restore-history-version")
                        if restore_button is not None:
                            ui.label(
                                "Selecione uma versão não ativa de uma etapa de autoria para "
                                "a voltar a tornar ativa."
                            ).classes("text-xs muted mt-3")
                        history_markdown = ui.markdown(
                            render_history_artifact(selected, state),
                            extras=["tables"],
                        ).classes("artifact-markdown mt-4 overflow-x-auto")

                        def update_history(event: Any) -> None:
                            history_markdown.set_content(
                                render_history_artifact(event.value, state)
                            )
                            if restore_button is None:
                                return
                            try:
                                impact = self.service.version_restore_impact(
                                    state, str(event.value or "")
                                )
                                enabled = not impact["is_active"]
                            except ValueError:
                                enabled = False
                            restore_button.set_enabled(enabled)

                        history_select.on_value_change(update_history)
                        if restore_button is not None:
                            try:
                                initial_impact = self.service.version_restore_impact(
                                    state, str(selected or "")
                                )
                                initial_enabled = not initial_impact["is_active"]
                            except ValueError:
                                initial_enabled = False
                            restore_button.set_enabled(initial_enabled)
                    with ui.tab_panel(audit_tab).classes("px-0"):
                        columns = [
                            {"name": "timestamp", "label": "Data", "field": "timestamp", "align": "left"},
                            {"name": "stage", "label": "Etapa", "field": "stage", "align": "left"},
                            {"name": "event", "label": "Evento", "field": "event", "align": "left"},
                            {"name": "feedback", "label": "Feedback", "field": "feedback", "align": "left"},
                        ]
                        ui.table(
                            columns=columns,
                            rows=audit_rows(state),
                            pagination={"rowsPerPage": 10},
                        ).props("flat bordered wrap-cells").classes("w-full")

    def _open_history_restore_dialog(self, selected_version: str) -> None:
        try:
            impact = self.service.version_restore_impact(
                self.state,
                selected_version,
            )
            if impact["is_active"]:
                raise ValueError("A versão selecionada já está ativa.")
        except USER_ERRORS as error:
            self._show_error(error)
            return

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl p-6 gap-4"):
            ui.label("RESTAURAR VERSÃO").classes("eyebrow")
            ui.label(
                f"{impact['stage_label']} — versão {impact['version_number']}"
            ).classes("section-title")
            ui.label(
                "A versão escolhida voltará a ser a versão ativa. Não será criada uma "
                "nova versão e a versão atualmente ativa continuará disponível no histórico."
            ).classes("text-sm")
            if impact["affected_labels"]:
                ui.label("Etapas posteriores que ficarão para revisão:").classes(
                    "font-semibold"
                )
                for label in impact["affected_labels"]:
                    ui.label(f"• {label}").classes("text-sm muted")
            if impact["was_completed"]:
                ui.label(
                    "A sessão deixará o estado Concluído e a exportação ficará "
                    "indisponível até uma nova verificação global."
                ).classes("soft-surface p-3 text-sm font-medium")
            async def confirm() -> None:
                dialog.close()
                await self._handle_restore_version(selected_version)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Confirmar restauro",
                    icon="restore",
                    on_click=confirm,
                ).props("unelevated no-caps").classes("primary-action")
        dialog.open()

    async def _handle_restore_version(
        self,
        selected_version: str,
    ) -> None:
        try:
            self.state, message = await run.io_bound(
                self.service.restore_session_version,
                self.state,
                selected_version,
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.manual_edit_stage_context = {}
            self.show_workspace(message)
            self.refresh_sessions()
        except USER_ERRORS as error:
            self._show_error(error)

    async def handle_export(self) -> None:
        self._show_busy("A preparar o pacote de recursos…")
        try:
            package_data, package_filename, self.state = await run.io_bound(
                self.service.export_session,
                self.state,
                _document_formats_for_export_choice(
                    self.export_document_format
                ),
            )
            ui.download(
                package_data,
                filename=package_filename,
                media_type="application/zip",
            )
            self._render_workspace(
                "Pacote exportado e evento registado na rastreabilidade."
            )
            ui.notify("Pacote de recursos preparado.", type="positive")
        except USER_ERRORS as error:
            self._show_error(error)
        finally:
            self._hide_busy()


def build_interface(
    service: ApplicationService | None = None,
    identity: Identity | None = None,
) -> AGIRSoloInterface:
    """Constrói a interface no contexto NiceGUI atual."""

    return AGIRSoloInterface(service, identity)


@ui.page("/login")
def login_page(redirect_to: str = "/") -> RedirectResponse | None:
    """Autentica um participante sem revelar se o identificador existe."""

    if authentication_disabled() or identity_from_session(app.storage.user):
        return RedirectResponse("/")

    destination = safe_redirect_path(redirect_to)
    ui.page_title(f"Acesso — {APP_NAME}")
    ui.colors(primary="#0d766e", secondary="#1f5966", accent="#e8a23a")
    ui.add_css(APP_CSS)
    login_error_notification: Any | None = None

    def show_login_error(message: str) -> None:
        nonlocal login_error_notification
        login_error_notification = _replace_error_notification(
            login_error_notification,
            message,
        )

    async def try_login() -> None:
        user_id = str(identifier.value or "")
        retry_after = LOGIN_THROTTLE.retry_after(user_id)
        if retry_after:
            ui.notify(
                f"Acesso temporariamente bloqueado. Aguarde {retry_after} segundos.",
                type="warning",
            )
            return
        try:
            credential_store = CredentialStore.from_environment()
            identity = await run.io_bound(
                credential_store.authenticate,
                user_id,
                str(access_code.value or ""),
            )
        except CredentialConfigurationError:
            LOGGER.exception("Configuração de autenticação inválida")
            show_login_error(
                "A autenticação está temporariamente indisponível. "
                "Contacte o responsável."
            )
            return

        if identity is None:
            lock_seconds = LOGIN_THROTTLE.record_failure(user_id)
            access_code.set_value("")
            message = "Identificador ou código de acesso inválido."
            if lock_seconds:
                message += f" Aguarde {lock_seconds} segundos antes de tentar novamente."
            show_login_error(message)
            return

        LOGIN_THROTTLE.clear(user_id)
        app.storage.user.clear()
        app.storage.user.update(identity.as_session())
        ui.navigate.to(destination)

    with ui.column().classes("absolute-center w-full max-w-md px-5"):
        with ui.card().classes("surface w-full p-7 gap-5"):
            ui.html('<div class="brand-mark">CI</div>')
            with ui.column().classes("gap-1"):
                ui.label(APP_NAME).classes("text-3xl font-bold")
                ui.label("Acesso ao espaço de autoria pedagógica").classes("muted")
            identifier = ui.input("Identificador").props(
                "autofocus autocomplete=username maxlength=80"
            ).classes("full-control")
            access_code = ui.input(
                "Código de acesso",
                password=True,
                password_toggle_button=True,
            ).props("autocomplete=current-password").classes("full-control")
            identifier.on("keydown.enter", lambda: access_code.run_method("focus"))
            access_code.on("keydown.enter", try_login)
            ui.button("Entrar", icon="login", on_click=try_login).props(
                "unelevated no-caps"
            ).classes("w-full primary-action")
            ui.label(
                "Utilize apenas o identificador e o código fornecidos para o estudo."
            ).classes("text-xs muted text-center")
    return None


@ui.page("/")
def main_page() -> RedirectResponse | None:
    if authentication_disabled():
        identity = Identity("LOCAL", "Utilizador local", "admin")
    else:
        identity = identity_from_session(app.storage.user)
        if identity is None:
            return RedirectResponse("/login")
    build_interface(
        ApplicationService(SESSION_STORE, owner_id=identity.user_id),
        identity,
    )
    return None


if __name__ == "__main__":
    ui.run(
        host="127.0.0.1",
        port=7860,
        title=f"{APP_NAME} — {APP_TAGLINE}",
        favicon="🎓",
        language="pt",
        show=False,
        reload=False,
        dark=False,
        storage_secret=configured_storage_secret(),
        session_middleware_kwargs={
            "https_only": not authentication_disabled(),
            "same_site": "lax",
            "max_age": 8 * 60 * 60,
        },
        show_welcome_message=False,
    )
