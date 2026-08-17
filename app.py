"""Interface NiceGUI do CoerIA, orientada à validação humana por etapa."""

from __future__ import annotations

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
from prism.ingestion import (
    DEFAULT_MAX_FILE_BYTES,
    SUPPORTED_SOURCE_SUFFIXES,
    SourceIngestionError,
)
from prism.manual_editing import (
    FieldSpec,
    TableSpec,
    apply_editor_field_value,
    editor_field_value,
    editor_reference_options,
    editor_reference_value,
    editor_taxonomy_level_options,
    editor_layout,
    new_table_row,
    value_at_path,
)
from prism.models import RESOURCE_PRESENTATION, SUPPORTED_RESOURCE_TYPES
from prism.persistence import SQLiteSessionStore
from prism.presentation import (
    active_stage_artifact,
    audit_rows,
    current_history_value,
    history_choices,
    render_current_artifact,
    render_history_artifact,
    render_stage_artifact,
)
from prism.providers import AI_PROVIDER_CHOICES, configured_ai_provider
from prism.workflow import STAGE_LABELS, STAGE_ORDER, revision_targets_for_state


SESSION_STORE = SQLiteSessionStore()
SERVICE = ApplicationService(SESSION_STORE)
LOGIN_THROTTLE = LoginThrottle()
RESOURCE_TYPES = list(SUPPORTED_RESOURCE_TYPES)
_history_choices = history_choices  # compatibilidade para consulta programática

USER_ERRORS = (ValueError, SourceIngestionError, AgentGenerationError)
LOGGER = logging.getLogger(__name__)
UNRESTRICTED_PAGE_ROUTES = {"/favicon.ico", "/login"}


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
    if elapsed < 8 or not (
        is_generation or is_resource_generation or is_resource_retry
    ):
        return phase
    if is_resource_generation or is_resource_retry:
        if elapsed < 30:
            return "A aguardar a resposta do fornecedor de IA para este recurso…"
        return "A geração deste recurso continua ativa no fornecedor de IA…"
    if elapsed < 30:
        return "A aguardar a resposta do fornecedor de IA…"
    if "Recursos educativos" in phase:
        return (
            "O fornecedor continua a gerar os recursos educativos; "
            "esta é normalmente a etapa mais demorada…"
        )
    return "O fornecedor continua a gerar a proposta; a operação está ativa…"


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
  --agir-primary-dark: #075a55;
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
  display: grid; grid-template-columns: repeat(9, minmax(126px, 1fr)); gap: 8px;
  width: 100%; overflow-x: auto; padding: 4px 2px 12px;
}
.stage-item { min-width: 126px; border-radius: 14px; padding: 12px; border: 1px solid var(--agir-border); background: white; color: inherit; text-align: left; }
.stage-item.done { background: #e8f5ef; border-color: #b9dfcd; }
.stage-item.current { color: white; background: linear-gradient(135deg, var(--agir-primary), var(--agir-secondary)); border-color: transparent; box-shadow: 0 8px 20px rgba(13, 118, 110, .2); }
.stage-item.stale { background: #fff6e5; border-color: #e8bd6a; color: #6f4c12; }
.stage-item.selectable { cursor: pointer; font: inherit; }
.stage-item.selectable:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(31, 71, 75, .11); }
.stage-item.viewing { outline: 3px solid var(--agir-accent); outline-offset: 2px; }
.stage-number { font-size: .72rem; font-weight: 800; opacity: .72; }
.stage-label { font-size: .78rem; line-height: 1.25; font-weight: 700; margin-top: 5px; }
.stage-state { font-size: .67rem; line-height: 1.2; margin-top: 6px; opacity: .78; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 350px; gap: 22px; align-items: start; }
.artifact-card { min-width: 0; padding: 26px 30px; overflow-x: auto; }
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
.manual-table .q-field { min-width: 100px; }
.manual-table .manual-cell-long { min-width: 210px; }
.manual-table .manual-cell-number { min-width: 72px; }
.manual-table .q-field__control { min-height: 40px; }
.manual-table .q-field__native { line-height: 1.35; padding-top: 7px; padding-bottom: 7px; }
.decision-card { padding: 22px; position: sticky; top: 84px; }
.info-chip { background: #edf5f3 !important; color: #24575d !important; font-weight: 650; }
.status-banner { border-left: 4px solid var(--agir-primary); }
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
  .workspace-grid { grid-template-columns: 1fr; }
  .decision-card { position: static; }
  .agir-main { padding: 22px 18px 64px; }
}
@media (max-width: 640px) {
  .hero-title { font-size: 2.15rem; }
  .artifact-card { padding: 20px 16px; }
  .q-stepper__title { display: none; }
  .brand-mark { width: 38px; height: 38px; border-radius: 12px; }
  .header-brand-copy { margin-left: 2px !important; }
  .header-tagline { display: none; }
}
"""


def _session_label(item: dict[str, str]) -> str:
    stage = STAGE_LABELS.get(item.get("current_stage", ""), "Sessão")
    return f"{item.get('unit_name', 'Sessão')} · {item.get('ai_provider', 'OpenAI')} · {stage}"


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
        self.uploaded_files: dict[str, bytes] = {}
        self.fields: dict[str, Any] = {}
        self.resource_inputs: dict[str, Any] = {}
        self.busy_started_at: float | None = None
        self.busy_phase_started_at: float | None = None
        self.busy_phase_text = ""
        self.busy_updates: SimpleQueue[str] | None = None
        self._build()

    def _build(self) -> None:
        ui.page_title(f"{APP_NAME} — {APP_TAGLINE}")
        ui.colors(primary="#0d766e", secondary="#1f5966", accent="#e8a23a")
        ui.add_css(APP_CSS)
        self.dark_mode = ui.dark_mode()

        self._build_logout_dialog()
        self._build_busy_dialog()

        with ui.header(elevated=False).classes("agir-header h-16 items-center px-3 md:px-6"):
            ui.button(icon="menu", on_click=lambda: self.drawer.toggle()).props(
                "flat round aria-label='Abrir navegação'"
            )
            ui.html('<div class="brand-mark">CI</div>')
            with ui.column().classes("header-brand-copy gap-0 ml-2"):
                ui.label(APP_NAME).classes("font-bold text-lg leading-tight")
                ui.label("Autoria pedagógica com IA").classes("header-tagline text-xs muted")
            ui.space()
            self.header_context = ui.label("Nova sessão").classes(
                "hidden md:block text-sm font-semibold muted"
            )
            ui.label(self.identity.display_name).classes(
                "hidden lg:block text-sm font-semibold muted"
            )
            ui.button(
                icon="dark_mode",
                on_click=self.dark_mode.toggle,
            ).props("flat round aria-label='Alternar tema'")
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
                    "Criar nova sessão",
                    icon="add_circle",
                    on_click=self.show_new_session,
                ).props("unelevated color=white text-color=primary no-caps").classes(
                    "w-full primary-action"
                )
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
            self.initial_view = ui.column().classes("w-full gap-6")
            self.workspace_view = ui.column().classes("w-full gap-5")

        with self.initial_view:
            self._build_initial_view()
        self.workspace_view.set_visibility(False)

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
        with ui.column().classes("gap-3 pt-4"):
            ui.label("DESENHO CURRICULAR ORIENTADO").classes("eyebrow")
            ui.label("Da ideia aos recursos, com cada decisão sob o seu controlo.").classes(
                "hero-title"
            )
            ui.label(
                "Estruture conteúdos, resultados de aprendizagem, avaliação, "
                "atividades e recursos numa sequência alinhada pela Taxonomia SOLO ou Bloom."
            ).classes("hero-copy")

        with ui.card().classes("surface w-full p-2 md:p-5"):
            with ui.stepper().props("flat animated alternative-labels").classes(
                "w-full"
            ) as self.form_stepper:
                with ui.step("contexto", "Contexto", icon="school"):
                    self._build_context_step()
                    with ui.stepper_navigation():
                        ui.button(
                            "Continuar para os conteúdos",
                            icon="arrow_forward",
                            on_click=self.form_stepper.next,
                        ).props("unelevated no-caps icon-right").classes("primary-action")

                with ui.step("conteudos", "Conteúdos", icon="description"):
                    self._build_sources_step()
                    with ui.stepper_navigation():
                        ui.button("Voltar", on_click=self.form_stepper.previous).props("flat no-caps")
                        ui.button(
                            "Continuar para a caracterização",
                            icon="arrow_forward",
                            on_click=self.form_stepper.next,
                        ).props("unelevated no-caps icon-right").classes("primary-action")

                with ui.step("caracterizacao", "Caracterização", icon="tune"):
                    self._build_characterization_step()
                    with ui.stepper_navigation():
                        ui.button("Voltar", on_click=self.form_stepper.previous).props("flat no-caps")

        with ui.card().classes("surface w-full p-5 md:p-6"):
            with ui.row().classes("w-full items-start gap-4"):
                ui.icon("auto_awesome", color="primary", size="2rem")
                with ui.column().classes("gap-1 flex-1"):
                    ui.label("Preenchimento manual orientado").classes("section-title")
                    ui.label(
                        "Valide os dados localmente ou solicite à IA uma proposta apenas para os campos vazios."
                    ).classes("muted")
            with ui.row().classes("w-full gap-3 mt-3"):
                ui.button(
                    "Validar e sugerir melhorias",
                    icon="fact_check",
                    on_click=self.handle_validate_initial,
                ).props("outline no-caps").classes("secondary-action")
                ui.button(
                    "Gerar proposta inicial por IA",
                    icon="auto_awesome",
                    on_click=self.handle_generate_initial,
                ).props("unelevated no-caps").classes("secondary-action")
            self.assistance_status = ui.markdown().classes(
                "soft-surface status-banner w-full p-4 mt-3"
            )
            self.assistance_status.set_visibility(False)

        with ui.row().classes("w-full justify-end"):
            ui.button(
                "Iniciar sessão pedagógica",
                icon="play_arrow",
                on_click=self.handle_start_session,
            ).props("unelevated no-caps size=lg icon-right").classes("primary-action px-6")

    def _build_context_step(self) -> None:
        ui.label("Identificação e opções pedagógicas").classes("section-title mb-3")
        with ui.grid(columns=2).classes("w-full gap-4 max-md:grid-cols-1"):
            self.fields["unit_name"] = ui.input(
                "Unidade curricular / ação de formação",
                placeholder="Ex.: Introdução às Pescas",
            ).classes("full-control")
            self.fields["audience"] = ui.input(
                "Público-alvo",
                value="Ensino superior",
            ).classes("full-control")
            self.fields["duration_hours"] = ui.number(
                "Duração prevista",
                value=12,
                min=1,
                precision=0,
                suffix=" horas",
            ).classes("full-control")
            self.fields["ai_provider"] = ui.toggle(
                list(AI_PROVIDER_CHOICES),
                value=configured_ai_provider(),
            ).props("spread no-caps").classes("full-control")
        ui.label("Fornecedor de IA").classes("text-xs font-semibold muted mt-1")
        ui.label(
            "A escolha é exclusiva e fica associada à sessão."
        ).classes("text-xs muted")
        ui.label("Taxonomia dos resultados de aprendizagem").classes(
            "text-sm font-semibold mt-4"
        )
        self.fields["taxonomy_type"] = ui.toggle(
            list(TAXONOMY_CHOICES),
            value="SOLO",
        ).props("spread no-caps").classes("full-control max-w-xl")

    def _build_sources_step(self) -> None:
        ui.label("Conteúdos programáticos e fontes").classes("section-title")
        ui.label(
            "Pode combinar texto direto com documentos. Os ficheiros são processados apenas quando iniciar a sessão."
        ).classes("muted mb-3")
        self.fields["source_text"] = ui.textarea(
            "Conteúdos programáticos ou texto de base",
            placeholder=(
                "Descreva os temas, competências, objetivos ou conteúdos "
                "programáticos da unidade curricular."
            ),
        ).props("outlined autogrow input-style='min-height: 190px'").classes("full-control")
        accepted = ",".join(sorted(SUPPORTED_SOURCE_SUFFIXES))
        self.uploader = ui.upload(
            label="Adicionar ficheiros de apoio",
            multiple=True,
            auto_upload=True,
            max_file_size=DEFAULT_MAX_FILE_BYTES,
            max_total_size=DEFAULT_MAX_FILE_BYTES * 5,
            on_upload=self.handle_upload,
            on_rejected=lambda: ui.notify(
                "Um ficheiro excede o limite permitido.",
                type="warning",
            ),
        ).props(f"accept={accepted} flat bordered").classes("w-full mt-4")
        self.upload_list = ui.row().classes("upload-list w-full gap-2 mt-2")
        self.render_upload_list()
        ui.label(
            "Formatos aceites: " + ", ".join(sorted(SUPPORTED_SOURCE_SUFFIXES))
        ).classes("text-xs muted")

    def _build_characterization_step(self) -> None:
        ui.label("Caracterização e recursos pretendidos").classes("section-title mb-3")
        with ui.grid(columns=4).classes("w-full gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1"):
            self.fields["program_name"] = ui.input("Curso / formação").classes("full-control")
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
            self.fields["semester"] = ui.input(
                "Semestre", placeholder="Ex.: 1.º semestre"
            ).classes("full-control")
            self.fields["cnaef_code"] = ui.input("Código CNAEF").classes("full-control")
            self.fields["cnaef_name"] = ui.input("Área CNAEF").classes("full-control")
            self.fields["ects_credits"] = ui.number(
                "ECTS", value=0, min=0, precision=1
            ).classes("full-control")
            self.fields["contact_hours"] = ui.number(
                "Horas de contacto", value=0, min=0, precision=1
            ).classes("full-control")
            self.fields["autonomous_hours"] = ui.number(
                "Trabalho autónomo", value=0, min=0, precision=1
            ).classes("full-control")
        self.fields["general_aims"] = ui.textarea(
            "Finalidades gerais da unidade curricular",
            placeholder="Indique as finalidades gerais, se já estiverem definidas.",
        ).props("outlined autogrow").classes("full-control mt-3")
        self.fields["bibliography"] = ui.textarea(
            "Bibliografia fornecida ou validada pelo docente",
            placeholder=(
                "Uma referência por linha. O CoerIA não inventa referências "
                "bibliográficas para o programa da UC."
            ),
        ).props("outlined autogrow").classes("full-control mt-3")
        ui.separator().classes("my-4")
        ui.label("Recursos a produzir").classes("text-base font-semibold")
        ui.label(
            "Seleção provisória; poderá confirmá-la ou alterá-la na matriz de alinhamento."
        ).classes("text-sm muted")
        with ui.grid(columns=2).classes("w-full gap-x-6 max-sm:grid-cols-1"):
            for resource_type in RESOURCE_TYPES:
                self.resource_inputs[resource_type] = ui.checkbox(
                    resource_type,
                    value=resource_type == RESOURCE_PRESENTATION,
                )

    async def handle_upload(self, event: events.UploadEventArguments) -> None:
        self.uploaded_files[event.file.name] = await event.file.read()
        self.render_upload_list()
        ui.notify(f"{event.file.name} adicionado.", type="positive")

    def render_upload_list(self) -> None:
        self.upload_list.clear()
        with self.upload_list:
            if not self.uploaded_files:
                ui.label("Nenhum ficheiro adicionado.").classes("text-sm muted")
                return
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

    def _form_data(self) -> dict[str, Any]:
        data = {name: element.value for name, element in self.fields.items()}
        data["duration_hours"] = int(data.get("duration_hours", 0) or 0)
        for key in ("ects_credits", "contact_hours", "autonomous_hours"):
            data[key] = float(data.get(key, 0) or 0)
        data["resource_types"] = [
            resource
            for resource, checkbox in self.resource_inputs.items()
            if checkbox.value
        ]
        return data

    def _set_form_data(self, data: dict[str, Any]) -> None:
        for name, element in self.fields.items():
            if name in data:
                element.set_value(data[name])
        if "resource_types" in data:
            selected_resources = set(data.get("resource_types", []))
            for resource, checkbox in self.resource_inputs.items():
                checkbox.set_value(resource in selected_resources)

    def _assistance_markdown(self, result: dict[str, Any]) -> str:
        status = (
            "✅ Os campos obrigatórios estão prontos para iniciar a sessão."
            if result["valid"]
            else "⚠️ Existem campos obrigatórios a corrigir."
        )
        parts = [f"### Validação do preenchimento\n\n{status}"]
        if result["issues"]:
            parts.append(
                "**Problemas**\n\n" + "\n".join(f"- ❌ {item}" for item in result["issues"])
            )
        if result["suggestions"]:
            parts.append(
                "**Sugestões**\n\n"
                + "\n".join(f"- 💡 {item}" for item in result["suggestions"])
            )
        return "\n\n".join(parts)

    def handle_validate_initial(self) -> None:
        result = self.service.validate_initial_form(self._form_data())
        self.assistance_status.set_content(self._assistance_markdown(result))
        self.assistance_status.set_visibility(True)

    async def handle_generate_initial(self) -> None:
        self._show_busy("A IA está a completar os campos vazios…")
        try:
            proposal = await run.io_bound(
                self.service.propose_initial_form,
                self._form_data(),
            )
            self._set_form_data(proposal)
            self.assistance_status.set_content(
                "### Proposta inicial gerada\n\n"
                + str(proposal.get("explanation", ""))
                + "\n\nRevise os campos antes de iniciar a sessão."
            )
            self.assistance_status.set_visibility(True)
            ui.notify("Proposta inicial preenchida.", type="positive")
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
        finally:
            self._hide_busy()

    async def handle_start_session(self) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        self._show_busy(
            "A gerar a primeira proposta pedagógica…",
            progress_updates,
            "A operação foi iniciada…",
        )
        try:
            with TemporaryDirectory(prefix="coeria_fontes_") as temporary_directory:
                source_paths: list[str] = []
                for index, (filename, content) in enumerate(self.uploaded_files.items()):
                    safe_name = Path(filename).name
                    path = Path(temporary_directory) / f"{index:02d}_{safe_name}"
                    path.write_bytes(content)
                    source_paths.append(str(path))
                self.state = await run.io_bound(
                    self.service.start_session,
                    self._form_data(),
                    source_paths,
                    progress_updates.put,
                )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self.show_workspace(
                "Sessão iniciada. Valide a proposta atual ou solicite uma reformulação."
            )
            self.refresh_sessions()
            ui.notify("Sessão iniciada e guardada.", type="positive")
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
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

    def show_new_session(self) -> None:
        self.state = None
        self.viewed_stage = None
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self._set_form_data(
            {
                "unit_name": "",
                "audience": "Ensino superior",
                "duration_hours": 12,
                "ai_provider": configured_ai_provider(),
                "taxonomy_type": "SOLO",
                "source_text": "",
                "program_name": "",
                "program_type": None,
                "academic_year": "",
                "semester": "",
                "cnaef_code": "",
                "cnaef_name": "",
                "ects_credits": 0,
                "contact_hours": 0,
                "autonomous_hours": 0,
                "general_aims": "",
                "bibliography": "",
                "resource_types": [RESOURCE_PRESENTATION],
            }
        )
        self.uploaded_files.clear()
        self.uploader.reset()
        self.render_upload_list()
        self.assistance_status.set_visibility(False)
        self.header_context.set_text("Nova sessão")
        self.workspace_view.set_visibility(False)
        self.initial_view.set_visibility(True)
        self.form_stepper.set_value("contexto")
        self.drawer.hide()

    def refresh_sessions(self) -> None:
        self.session_list.clear()
        sessions = self.service.list_sessions()
        with self.session_list:
            if not sessions:
                ui.label("Ainda não existem sessões.").classes("text-sm opacity-60")
                return
            for item in sessions:
                session_id = item["session_id"]

                async def load_selected(_event=None, selected_id=session_id) -> None:
                    await self.handle_load_session(selected_id)

                with ui.button(on_click=load_selected).props("flat no-caps align=left").classes(
                    "session-entry p-2"
                ):
                    with ui.column().classes("items-start gap-0 text-left"):
                        ui.label(item.get("unit_name", "Sessão sem título")).classes(
                            "font-semibold text-sm"
                        )
                        ui.label(
                            f"{item.get('ai_provider', 'OpenAI')} · "
                            f"{STAGE_LABELS.get(item.get('current_stage', ''), 'Sessão')}"
                        ).classes("text-xs opacity-65")

    async def handle_load_session(self, session_id: str) -> None:
        self._show_busy("A retomar a sessão guardada…")
        try:
            self.state = await run.io_bound(self.service.load_session, session_id)
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.uploaded_files.clear()
            self.uploader.reset()
            self.render_upload_list()
            self.show_workspace(
                "Sessão retomada. As fontes incorporadas permanecem no estado guardado."
            )
            self.drawer.hide()
            ui.notify("Sessão retomada com sucesso.", type="positive")
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
        finally:
            self._hide_busy()

    def show_workspace(self, message: str = "") -> None:
        if not self.state:
            return
        self.initial_view.set_visibility(False)
        self.workspace_view.set_visibility(True)
        course = self.state.get("course", {})
        self.header_context.set_text(
            f"{course.get('unit_name', 'Sessão')} · {self.state.get('ai_provider', 'OpenAI')}"
        )
        self._render_workspace(message)

    def _render_workspace(self, message: str = "") -> None:
        if not self.state:
            return
        state = self.state
        self.workspace_view.clear()
        with self.workspace_view:
            with ui.row().classes("w-full items-start gap-3"):
                with ui.column().classes("gap-1"):
                    ui.label("SESSÃO PEDAGÓGICA").classes("eyebrow")
                    ui.label(state.get("course", {}).get("unit_name", "Sessão")).classes(
                        "text-3xl font-extrabold tracking-tight"
                    )
                    with ui.row().classes("gap-2 mt-1"):
                        ui.chip(state.get("ai_provider", "OpenAI"), icon="smart_toy").classes("info-chip")
                        ui.chip(
                            state.get("course", {}).get("taxonomy_type", "SOLO"),
                            icon="account_tree",
                        ).classes("info-chip")
                ui.space()
                ui.button("Nova sessão", icon="add", on_click=self.show_new_session).props(
                    "outline no-caps"
                ).classes("secondary-action")

            if message:
                with ui.row().classes("soft-surface status-banner w-full p-4 items-center"):
                    ui.icon("info", color="primary")
                    ui.label(message).classes("font-medium")

            self._render_stage_track(state)

            viewed_stage = (
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
        with ui.element("div").classes("stage-track"):
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
                visual_status = (
                    "done"
                    if stored_status == "approved"
                    else "current"
                    if stored_status in {"awaiting_review", "generating"}
                    else "stale"
                    if stored_status == "stale"
                    else "pending"
                )
                returns_to_current = (
                    stage == state["current_stage"] and self.viewed_stage is not None
                )
                selectable = returns_to_current or (
                    stage in viewable_stages and stage != state["current_stage"]
                )
                viewing = stage == self.viewed_stage
                item = ui.element("button" if selectable else "div").classes(
                    f"stage-item {visual_status}"
                    + (" selectable" if selectable else "")
                    + (" viewing" if viewing else "")
                )
                if selectable:
                    item.props("type=button")
                    if returns_to_current:
                        item.mark("return-current-stage")
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
                    ui.label(f"{index + 1:02d}").classes("stage-number")
                    ui.label(STAGE_LABELS[stage]).classes("stage-label")
                    stage_status_label = (
                        "Ponto atual · selecionar para voltar"
                        if returns_to_current
                        else status_labels.get(stored_status, stored_status)
                    )
                    ui.label(stage_status_label).classes("stage-state")

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
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
            return
        self.manual_edit_stage = stage
        self._render_workspace(
            "Modo de edição ativado na própria tabela. As alterações ainda não "
            "foram guardadas."
        )

    def _cancel_manual_edit(self) -> None:
        self.manual_edit_stage = None
        self.manual_edit_artifact = None
        self._render_workspace("Edição manual cancelada; a sessão não foi alterada.")

    def _open_revision_dialog(self, target_stage: str) -> None:
        try:
            impact = self.service.revision_impact(self.state, target_stage)
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
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

    def _render_stage_preview(self, state: dict[str, Any], stage: str) -> None:
        """Mostra uma etapa anterior sem a tornar corrente nem a invalidar."""

        editing = (
            self.manual_edit_stage == stage and self.manual_edit_artifact is not None
        )
        with ui.element("div").classes("workspace-grid"):
            with ui.card().classes("surface artifact-card"):
                if editing:
                    self._render_inline_manual_editor(stage)
                else:
                    ui.markdown(
                        render_stage_artifact(state, stage),
                        extras=["tables"],
                    ).classes("artifact-markdown")
            if editing:
                self._render_manual_edit_actions(state, stage)
            else:
                with ui.card().classes("surface decision-card w-full"):
                    ui.label("MODO DE CONSULTA").classes("eyebrow")
                    ui.label("Etapa anterior").classes("section-title")
                    ui.label(
                        "Abrir esta etapa não altera a sessão. Só será criada uma "
                        "nova versão se escolher Editar ou Reformular e confirmar "
                        "a alteração."
                    ).classes("text-sm muted")
                    ui.button(
                        "Editar esta tabela",
                        icon="edit",
                        on_click=lambda: self._start_manual_edit(stage),
                    ).props("unelevated no-caps").classes(
                        "primary-action w-full mt-3"
                    )
                    ui.button(
                        "Reformular esta etapa",
                        icon="edit_note",
                        on_click=lambda: self._open_revision_dialog(stage),
                    ).props("outline no-caps").classes(
                        "secondary-action w-full mt-2"
                    )
                    ui.button(
                        "Voltar ao ponto atual",
                        icon="arrow_back",
                        on_click=self._return_to_current_stage,
                    ).props("outline no-caps").classes(
                        "secondary-action w-full mt-2"
                    )

    def _render_manual_field(
        self,
        target: dict[str, Any],
        field: FieldSpec,
        *,
        compact: bool = False,
    ) -> None:
        value = editor_field_value(target, field)

        def update_value(event: Any) -> None:
            try:
                apply_editor_field_value(target, field, event.value)
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
        if selection_options is not None:
            multiple = field.kind in {"csv", "content_ids", "linked_outcomes"}
            control = ui.select(
                options=(list(selection_options) if multiple else selection_options),
                label=label,
                value=editor_reference_value(target, field),
                multiple=multiple,
                on_change=update_value,
            ).props("options-dense" + (" use-chips" if multiple else ""))
            if not selection_options:
                control.props("disable")
        elif field.kind == "integer":
            control = ui.number(label, value=value, precision=0)
        elif field.kind in {"long", "lines"}:
            control = ui.textarea(label, value=value).props("outlined autogrow")
        else:
            control = ui.input(label, value=value).props("outlined")
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
                                ui.label("Remover")
                    with ui.element("tbody"):
                        for index, row in enumerate(rows):
                            with ui.element("tr"):
                                for field in table.fields:
                                    with ui.element("td"):
                                        self._render_manual_field(
                                            row, field, compact=True
                                        )

                                def remove_row(row_index: int = index) -> None:
                                    rows.pop(row_index)
                                    render_rows.refresh()

                                with ui.element("td").classes("manual-row-action"):
                                    ui.button(icon="delete", on_click=remove_row).props(
                                        "flat round color=negative "
                                        "aria-label='Remover linha'"
                                    )

        def add_row() -> None:
            row = new_table_row(table, self.state)
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
        ui.label("EDIÇÃO NA TABELA ATUAL").classes("eyebrow")
        ui.label(STAGE_LABELS[stage]).classes("section-title mb-2")
        ui.label(
            "Edite os campos abaixo ou adicione e remova linhas. Enquanto não "
            "guardar, a versão aprovada e os passos seguintes permanecem intactos."
        ).classes("text-sm muted mb-4")
        with ui.column().classes("w-full gap-4"):
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

    def _render_manual_edit_actions(
        self,
        state: dict[str, Any],
        stage: str,
    ) -> None:
        impact = self.service.revision_impact(state, stage)
        with ui.card().classes("surface decision-card w-full"):
            ui.label("EDIÇÃO MANUAL").classes("eyebrow")
            ui.label("Guardar alterações").classes("section-title")
            ui.label(
                f"Será criada a versão {impact['next_version']} sem utilizar a IA."
            ).classes("text-sm muted")
            if impact["affected_labels"]:
                ui.label("Etapas que ficarão desatualizadas:").classes(
                    "font-semibold mt-2"
                )
                for label in impact["affected_labels"]:
                    ui.label(f"• {label}").classes("text-xs muted")
            reason = ui.textarea(
                "Nota da edição — opcional",
                placeholder="Explique resumidamente o motivo da alteração.",
            ).props("outlined autogrow").classes("w-full mt-2")

            async def save_manual_version() -> None:
                if self.manual_edit_artifact is None:
                    ui.notify("A edição manual já não está ativa.", type="warning")
                    return
                await self.handle_manual_edit(
                    stage,
                    self.manual_edit_artifact,
                    str(reason.value or ""),
                )

            ui.button(
                "Guardar nova versão",
                icon="save",
                on_click=save_manual_version,
            ).props("unelevated no-caps").classes("primary-action w-full mt-3")
            ui.button(
                "Cancelar edição",
                icon="close",
                on_click=self._cancel_manual_edit,
            ).props("outline no-caps").classes("secondary-action w-full mt-2")

    def _render_authoring_view(self, state: dict[str, Any]) -> None:
        stage = state["current_stage"]
        editing = (
            self.manual_edit_stage == stage and self.manual_edit_artifact is not None
        )
        with ui.element("div").classes("workspace-grid"):
            with ui.card().classes("surface artifact-card"):
                if editing:
                    self._render_inline_manual_editor(stage)
                else:
                    ui.markdown(
                        render_current_artifact(state), extras=["tables"]
                    ).classes("artifact-markdown")
            if editing:
                self._render_manual_edit_actions(state, stage)
            else:
                self._render_decision_card(state)

    def _render_final_validation_view(self, state: dict[str, Any]) -> None:
        with ui.column().classes("w-full gap-5"):
            with ui.element("div").classes("final-hero w-full"):
                ui.label("VALIDAÇÃO FINAL").classes("text-xs tracking-widest font-bold opacity-75")
                ui.label("Confirme a estrutura e o alinhamento antes de concluir.").classes(
                    "text-3xl font-extrabold mt-2"
                )
                ui.label(
                    "Este ecrã é independente das etapas de autoria. A conclusão continua a depender da sua aprovação."
                ).classes("mt-2 opacity-85")
            with ui.element("div").classes("workspace-grid"):
                with ui.card().classes("surface artifact-card"):
                    ui.markdown(render_current_artifact(state), extras=["tables"]).classes(
                        "artifact-markdown"
                    )
                self._render_decision_card(state, final=True)

    def _render_completed_view(self, state: dict[str, Any]) -> None:
        with ui.card().classes("surface complete-hero w-full items-center gap-3"):
            ui.icon("verified", size="4rem", color="positive")
            ui.label("Sessão pedagógica concluída").classes("text-3xl font-extrabold")
            ui.label(
                "A estrutura foi validada. Pode agora exportar os recursos e a rastreabilidade."
            ).classes("muted text-base")
            ui.button(
                "Exportar pacote de recursos",
                icon="download",
                on_click=self.handle_export,
            ).props("unelevated no-caps size=lg").classes("primary-action px-6 mt-2")
        with ui.card().classes("surface artifact-card w-full"):
            ui.markdown(render_current_artifact(state), extras=["tables"]).classes(
                "artifact-markdown"
            )

    def _render_decision_card(self, state: dict[str, Any], final: bool = False) -> None:
        with ui.card().classes("surface decision-card w-full"):
            ui.label("DECISÃO DO DOCENTE").classes("eyebrow")
            ui.label(
                "Validação final" if final else "Rever a proposta"
            ).classes("section-title")
            ui.label(
                "A IA não avança sem a sua decisão."
            ).classes("text-sm muted mb-2")

            decision = None
            feedback = None
            if final:
                ui.label(
                    "Para rever uma componente, selecione primeiro a respetiva "
                    "etapa na barra superior, consulte-a e escolha Reformular."
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

            resource_checks: dict[str, Any] = {}
            if state["current_stage"] == "alignment_matrix":
                ui.separator().classes("my-2")
                ui.label("Confirmar recursos").classes("font-semibold")
                ui.label(
                    "Esta é a etapa em que a seleção provisória pode ser alterada."
                ).classes("text-xs muted")
                selected = set(state.get("resource_types", []))
                for resource_type in RESOURCE_TYPES:
                    resource_checks[resource_type] = ui.checkbox(
                        resource_type,
                        value=resource_type in selected,
                    )
            elif state["current_stage"] == "resources":
                ui.separator().classes("my-2")
                ui.label("Recursos confirmados").classes("font-semibold")
                with ui.row().classes("gap-1"):
                    for resource in state.get("resource_types", []):
                        ui.chip(resource).classes("info-chip")

            async def submit_decision() -> None:
                resources = (
                    [name for name, checkbox in resource_checks.items() if checkbox.value]
                    if resource_checks
                    else None
                )
                await self.handle_review(
                    "approve" if final else str(decision.value),
                    "" if final else str(feedback.value or ""),
                    state["current_stage"],
                    resources,
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
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.show_workspace(message)
            self.refresh_sessions()
            ui.notify(message, type="positive")
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
        finally:
            self._hide_busy()

    async def handle_reopen_stage(self, target_stage: str, feedback: str) -> None:
        progress_updates: SimpleQueue[str] = SimpleQueue()
        self._show_busy(
            f"A criar uma nova versão de «{STAGE_LABELS[target_stage]}»…",
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
            ui.notify(message, type="positive", multi_line=True)
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
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
            )
            self.viewed_stage = None
            self.manual_edit_stage = None
            self.manual_edit_artifact = None
            self._set_form_data(self.service.restored_initial_fields(self.state))
            self.show_workspace(message)
            self.refresh_sessions()
            ui.notify(message, type="positive", multi_line=True)
            return True
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
            return False
        finally:
            self._hide_busy()

    def _render_history_and_audit(self, state: dict[str, Any]) -> None:
        with ui.card().classes("surface w-full p-3 md:p-5"):
            with ui.tabs().props("no-caps align=left").classes("w-full") as tabs:
                history_tab = ui.tab("history", label="Versões", icon="history")
                audit_tab = ui.tab("audit", label="Rastreabilidade", icon="route")
            with ui.tab_panels(tabs, value=history_tab).classes("w-full"):
                with ui.tab_panel(history_tab).classes("px-0"):
                    choices = history_choices(state)
                    options = {value: label for label, value in choices}
                    selected = current_history_value(state)
                    history_select = ui.select(
                        options,
                        value=selected,
                        label="Etapa e versão",
                    ).classes("full-control max-w-3xl")
                    history_markdown = ui.markdown(
                        render_history_artifact(selected, state),
                        extras=["tables"],
                    ).classes("artifact-markdown mt-4 overflow-x-auto")
                    history_select.on_value_change(
                        lambda event: history_markdown.set_content(
                            render_history_artifact(event.value, state)
                        )
                    )
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

    async def handle_export(self) -> None:
        self._show_busy("A preparar o pacote de recursos…")
        try:
            package_path, self.state = await run.io_bound(
                self.service.export_session,
                self.state,
            )
            ui.download(package_path, filename=Path(package_path).name)
            self._render_workspace(
                "Pacote exportado e evento registado na rastreabilidade."
            )
            ui.notify("Pacote de recursos preparado.", type="positive")
        except USER_ERRORS as error:
            ui.notify(str(error), type="negative", multi_line=True, timeout=0)
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
            ui.notify(
                "A autenticação está temporariamente indisponível. Contacte o responsável.",
                type="negative",
                timeout=0,
            )
            return

        if identity is None:
            lock_seconds = LOGIN_THROTTLE.record_failure(user_id)
            access_code.set_value("")
            message = "Identificador ou código de acesso inválido."
            if lock_seconds:
                message += f" Aguarde {lock_seconds} segundos antes de tentar novamente."
            ui.notify(message, type="negative")
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
