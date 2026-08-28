from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest
from nicegui import ui
from nicegui.testing import User

import app
from prism.application_service import ApplicationService
from prism.models import (
    CourseInput,
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
)
from prism.persistence import SQLiteSessionStore
from prism.workflow import (
    ai_review_context_signature,
    create_session,
    create_test_agent,
    navigate_to_stage,
    review_current_stage,
    save_manual_draft,
)


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected"),
    [
        (0, "Tempo decorrido: 0 s"),
        (12.9, "Tempo decorrido: 12 s"),
        (65, "Tempo decorrido: 1 min 05 s"),
    ],
)
def test_busy_elapsed_duration_is_readable(
    elapsed_seconds: float,
    expected: str,
) -> None:
    assert app._format_elapsed_duration(elapsed_seconds) == expected


@pytest.mark.parametrize(
    ("status", "css_class"),
    list(app.STAGE_STATUS_CSS_CLASSES.items()),
)
def test_each_stage_status_has_a_specific_background_class(
    status: str,
    css_class: str,
) -> None:
    assert app._stage_status_css_class(status) == css_class
    assert f".stage-item.{css_class}" in app.APP_CSS


def test_unknown_stage_status_uses_the_pending_background() -> None:
    assert app._stage_status_css_class("legacy-status") == "stage-status-pending"


def test_stage_status_colors_preserve_the_original_selected_background() -> None:
    assert "--agir-bg: #f3f7f6;" in app.APP_CSS
    assert (
        ".stage-item.stage-status-empty { background: #ffffff; "
        "border-color: #c6d7d4; }"
        in app.APP_CSS
    )
    assert (
        ".stage-item.stage-status-approved { background: #d9efe4; "
        "border-color: #82c2a3; }"
        in app.APP_CSS
    )
    assert (
        ".stage-item.current { color: white; background: linear-gradient(135deg, "
        "var(--agir-primary), var(--agir-secondary)); border-color: transparent;"
        in app.APP_CSS
    )


@pytest.mark.parametrize(
    ("phase", "elapsed_seconds", "expected"),
    [
        (
            "A gerar e validar «Geração de recursos educativos»…",
            7,
            "A gerar e validar «Geração de recursos educativos»…",
        ),
        (
            "A gerar e validar «Geração de recursos educativos»…",
            8,
            "A aguardar a resposta do fornecedor de IA…",
        ),
        (
            "A gerar e validar «Geração de recursos educativos»…",
            30,
            "O fornecedor continua a gerar os recursos educativos; "
            "esta é normalmente a etapa mais demorada…",
        ),
        (
            "A gerar recurso 2 de 4: Teste…",
            8,
            "A gerar recurso 2 de 4: Teste…",
        ),
        (
            "A gerar recurso 2 de 4: Teste…",
            20,
            "A aguardar a resposta do fornecedor de IA para este recurso…",
        ),
        (
            "A corrigir recurso 1 de 4: Apresentação PowerPoint…",
            60,
            "A geração deste recurso continua ativa no fornecedor de IA…",
        ),
        (
            "A verificar o conjunto final dos recursos…",
            45,
            "A verificar o conjunto final dos recursos…",
        ),
    ],
)
def test_busy_phase_explains_long_provider_waits(
    phase: str,
    elapsed_seconds: float,
    expected: str,
) -> None:
    assert app._busy_phase_message(phase, elapsed_seconds) == expected


@pytest.mark.asyncio
async def test_nicegui_initial_page_exposes_the_guided_workflow(
    user: User,
    monkeypatch,
) -> None:
    monkeypatch.setenv("COERIA_AUTH_MODE", "disabled")
    await user.open("/")

    await user.should_see("CoerIA")
    await user.should_see("Construa uma unidade curricular coerente")
    await user.should_see("Iniciar nova sessão")
    user.find(marker="start-new-session").click()
    await user.should_see("Configure o ponto de partida")
    await user.should_see("Validar dados")
    await user.should_see("ASSISTÊNCIA COM IA")
    await user.should_see("Gerar proposta inicial por IA")
    await user.should_not_see("Preenchimento manual orientado")
    await user.should_see("Fornecedor de IA")
    await user.should_see("OpenAI")
    await user.should_see("IAedu")
    await user.should_see("SOLO")
    await user.should_see("Bloom")
    await user.should_see("CoerIA v0.2.8 · SQLite")


def test_error_notification_replaces_the_previous_one_and_can_be_closed() -> None:
    class ExistingNotification:
        def __init__(self) -> None:
            self.dismissed = False
            self.deleted = False

        def dismiss(self) -> None:
            self.dismissed = True

        def delete(self) -> None:
            self.deleted = True

    previous = ExistingNotification()
    replacement = object()
    with patch.object(app.ui, "notification", return_value=replacement) as create:
        result = app._replace_error_notification(previous, "Erro de validação")

    assert previous.dismissed
    assert previous.deleted
    assert result is replacement
    create.assert_called_once_with(
        "Erro de validação",
        type="negative",
        multi_line=True,
        position="top",
        close_button="Fechar",
        timeout=app.ERROR_NOTIFICATION_TIMEOUT_SECONDS,
    )


def test_error_notification_is_replaced_after_the_previous_one_was_closed() -> None:
    class ClosedNotification:
        def dismiss(self) -> None:
            raise RuntimeError("already dismissed")

        def delete(self) -> None:
            raise RuntimeError("already deleted")

    replacement = object()
    with patch.object(app.ui, "notification", return_value=replacement) as create:
        result = app._replace_error_notification(
            ClosedNotification(), "Novo erro de validação"
        )

    assert result is replacement
    create.assert_called_once()


@pytest.mark.asyncio
async def test_application_opens_on_home_before_starting_a_new_session(
    user: User,
) -> None:
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_home")
    def home_page():
        interfaces.append(app.AGIRSoloInterface())

    await user.open("/_test_home")

    await user.should_see("Construa uma unidade curricular coerente")
    await user.should_not_see("Identificação e opções pedagógicas")
    assert interfaces[-1].home_view.visible
    assert not interfaces[-1].initial_view.visible

    user.find(marker="start-new-session").click()

    await user.should_see("Identificação e opções pedagógicas")
    await user.should_see("01 · DADOS INICIAIS")
    await user.should_see("Formulação dos resultados de aprendizagem")
    assert user.find(marker="manual-stage-initial_data").elements
    assert not interfaces[-1].home_view.visible
    assert interfaces[-1].initial_view.visible
    form_data = interfaces[-1]._form_data()
    assert form_data["resource_types"] == [RESOURCE_PRESENTATION]
    assert form_data["ai_image_generation_enabled"] is True
    assert form_data["semester"] == "1.º semestre"
    assert form_data["audience"] == "Ensino superior"
    assert form_data["duration_hours"] == 0
    interfaces[-1].fields["program_type"].set_value("Mestrado")
    interfaces[-1].fields["contact_hours"].set_value(45.5)
    interfaces[-1].fields["autonomous_hours"].set_value(116.75)
    assert interfaces[-1]._form_data()["audience"] == "Mestrado"
    assert interfaces[-1]._form_data()["duration_hours"] == 162.25

    await user.should_see("Texto de base e fontes de referência")
    await user.should_see("Informação de referência para a unidade curricular")
    await user.should_see("Nome da unidade curricular ou ação de formação")
    await user.should_see("Curso ou programa em que se integra")
    await user.should_see("Caracterização da unidade curricular")
    await user.should_see("Iniciar desenho curricular alinhado")
    await user.should_not_see("Público-alvo")
    await user.should_not_see("Duração prevista")
    await user.should_not_see("Objetivos gerais da unidade curricular")
    await user.should_not_see("Recursos a produzir")
    await user.should_not_see("Permitir geração de imagens por IA")
    toolbar = next(iter(user.find(marker="initial-stage-toolbar").elements))
    provider = next(iter(user.find(marker="new-session-provider").elements))
    create_button = next(
        iter(user.find(marker="create-pedagogical-session").elements)
    )
    form = next(iter(user.find(marker="new-session-form").elements))
    assert toolbar.id < provider.id < form.id
    assert form.id < create_button.id
    user.find(marker="stage-toolbar-help-initial").click()
    await user.should_see("AJUDA DA BARRA DE FERRAMENTAS")
    await user.should_see("Não usa IA nem tem custo de API")
    user.find(marker="close-toolbar-help").click()


@pytest.mark.asyncio
async def test_initial_validation_results_focus_the_related_field(
    user: User,
) -> None:
    interfaces: list[app.AGIRSoloInterface] = []
    focus_handlers: list[AsyncMock] = []
    scroll_handlers: list[AsyncMock] = []

    @ui.page("/_test_initial_validation_focus")
    def initial_validation_focus_page():
        interface = app.AGIRSoloInterface()

        async def record_focus(*_args, **_kwargs) -> None:
            ui.notify("Campo localizado.")

        handler = AsyncMock(side_effect=record_focus)
        scroll_handler = AsyncMock()
        interface._focus_initial_result = handler
        interface._scroll_and_highlight = scroll_handler
        interface.show_new_session()
        interfaces.append(interface)
        focus_handlers.append(handler)
        scroll_handlers.append(scroll_handler)

    await user.open("/_test_initial_validation_focus")

    user.find(marker="validate-initial-data").click()
    await user.should_see("Existem campos obrigatórios a corrigir.")
    await user.should_see(
        "Selecione uma observação para localizar o campo correspondente."
    )
    scroll_handlers[-1].assert_awaited_once_with(
        f"#c{interfaces[-1].assistance_status.id}"
    )
    user.find(marker="initial-validation-result-0").click()
    await user.should_see("Campo localizado.")

    focus_handlers[-1].assert_awaited_once_with("unit_name")
    assert interfaces[-1].initial_view.visible


@pytest.mark.asyncio
async def test_duration_validation_focuses_both_workload_fields(user: User) -> None:
    interfaces: list[app.AGIRSoloInterface] = []
    scroll_handlers: list[AsyncMock] = []

    @ui.page("/_test_initial_duration_focus")
    def initial_duration_focus_page():
        interface = app.AGIRSoloInterface()
        scroll_handler = AsyncMock()
        interface._scroll_and_highlight = scroll_handler
        interface.show_new_session()
        interfaces.append(interface)
        scroll_handlers.append(scroll_handler)

    await user.open("/_test_initial_duration_focus")
    await interfaces[-1]._focus_initial_result("duration_hours")

    scroll_handlers[-1].assert_awaited_once_with(
        f"#c{interfaces[-1].initial_hours_group.id}"
    )
    hours_group = next(iter(user.find(marker="initial-hours-group").elements))
    assert hours_group.id == interfaces[-1].initial_hours_group.id


@pytest.mark.asyncio
async def test_existing_session_can_return_to_and_update_initial_data(
    user: User,
    tmp_path: Path,
) -> None:
    service = ApplicationService(SQLiteSessionStore(tmp_path / "edit-initial.db"))
    state = create_session(
        CourseInput.create(
            "Introdução às Pescas",
            "Ecossistemas aquáticos, gestão sustentável, segurança e técnicas de captura.",
        )
    )
    state["source_input_text"] = state["course"]["source_text"]
    state["source_original_text"] = (
        "[Texto introduzido pelo docente]\n"
        + state["source_input_text"]
        + "\n\n[Ficheiro: 00_programa.pdf]\nPrograma documental anterior."
    )
    state["source_images"] = [
        {"id": "source-image-1", "source_file": "00_programa.pdf"}
    ]
    state = service._persist(state)
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_edit_initial_session")
    def edit_initial_session_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_edit_initial_session")

    await user.should_see("Dados iniciais")
    await user.should_not_see("Editar dados iniciais")
    assert user.find(marker="manual-stage-initial_data").elements
    user.find("Etapa anterior").click()
    await user.should_see("Reveja o ponto de partida")
    await user.should_see("Guardar alterações iniciais")
    await user.should_see("ASSISTÊNCIA COM IA")
    await user.should_see("Incorporado: programa.pdf")
    assert user.find(marker="initial-stage-toolbar").elements
    assert interfaces[-1].initial_view.visible
    assert interfaces[-1].state is not None
    assert interfaces[-1]._form_data()["unit_name"] == "Introdução às Pescas"

    interfaces[-1].fields["unit_name"].set_value("Introdução às Pescas Costeiras")
    user.find(marker="toggle-existing-source").click()
    await user.should_see("programa.pdf — será removido")
    user.find(marker="create-pedagogical-session").click()

    await user.should_see("Dados iniciais atualizados")
    await user.should_see("Introdução às Pescas Costeiras")
    assert interfaces[-1].workspace_view.visible
    assert not interfaces[-1].editing_initial_session
    assert interfaces[-1].state["course"]["unit_name"] == (
        "Introdução às Pescas Costeiras"
    )
    assert "[Ficheiro: 00_programa.pdf]" not in interfaces[-1].state["source_original_text"]
    assert interfaces[-1].state["source_images"] == []


@pytest.mark.asyncio
async def test_initial_data_stage_navigates_to_another_stage_when_unchanged(
    user: User,
    tmp_path: Path,
) -> None:
    service = ApplicationService(SQLiteSessionStore(tmp_path / "initial-navigation.db"))
    state = service._persist(
        create_session(
            CourseInput.create(
                "Programação",
                "Algoritmos, estruturas de dados, funções e testes.",
            )
        )
    )
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_initial_navigation")
    def initial_navigation_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_initial_navigation")

    user.find(marker="edit-initial-session-data").click()
    await user.should_see("Reveja o ponto de partida")
    user.find("Etapa seguinte").click()

    await user.should_see("Etapa aberta: Formulação dos resultados de aprendizagem.")
    assert interfaces[-1].workspace_view.visible
    assert interfaces[-1].state["current_stage"] == "learning_outcomes"


@pytest.mark.asyncio
async def test_initial_data_navigation_requires_a_decision_for_unsaved_changes(
    user: User,
    tmp_path: Path,
) -> None:
    service = ApplicationService(SQLiteSessionStore(tmp_path / "initial-unsaved.db"))
    state = service._persist(
        create_session(
            CourseInput.create(
                "Programação",
                "Algoritmos, estruturas de dados, funções e testes.",
            )
        )
    )
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_initial_unsaved_navigation")
    def initial_unsaved_navigation_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_initial_unsaved_navigation")

    user.find(marker="edit-initial-session-data").click()
    interfaces[-1].fields["unit_name"].set_value("Programação alterada")
    user.find(marker="manual-stage-curriculum_analysis").click()

    await user.should_see("Guardar antes de mudar de etapa?")
    assert interfaces[-1].initial_view.visible
    user.find(marker="discard-initial-changes").click()

    await user.should_see("Alterações aos dados iniciais descartadas.")
    assert interfaces[-1].workspace_view.visible
    assert interfaces[-1].state["current_stage"] == "curriculum_analysis"
    assert interfaces[-1].state["course"]["unit_name"] == "Programação"


@pytest.mark.asyncio
async def test_initial_data_navigation_can_save_and_continue(
    user: User,
    tmp_path: Path,
) -> None:
    service = ApplicationService(SQLiteSessionStore(tmp_path / "initial-save.db"))
    state = service._persist(
        create_session(
            CourseInput.create(
                "Programação",
                "Algoritmos, estruturas de dados, funções e testes.",
            )
        )
    )
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_initial_save_navigation")
    def initial_save_navigation_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_initial_save_navigation")

    user.find(marker="edit-initial-session-data").click()
    interfaces[-1].fields["unit_name"].set_value("Programação aplicada")
    user.find(marker="manual-stage-curriculum_analysis").click()
    await user.should_see("Guardar antes de mudar de etapa?")
    user.find(marker="save-initial-and-continue").click()

    await user.should_see("Dados iniciais guardados.")
    assert interfaces[-1].workspace_view.visible
    assert interfaces[-1].state["current_stage"] == "curriculum_analysis"
    assert interfaces[-1].state["course"]["unit_name"] == "Programação aplicada"


@pytest.mark.asyncio
async def test_workspace_uses_a_notification_instead_of_a_status_banner(user: User) -> None:
    state = create_session(
        CourseInput.create(
            unit_name="Programação",
            source_text="Algoritmos, estruturas de dados, funções e testes.",
        )
    )

    @ui.page("/_test_workspace_without_status_banner")
    def workspace_without_status_banner_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace("Etapa aberta: Resultados de aprendizagem.")

    await user.open("/_test_workspace_without_status_banner")

    await user.should_see("Etapa aberta: Resultados de aprendizagem.")
    assert ".status-banner" not in app.APP_CSS


@pytest.mark.asyncio
async def test_teacher_decision_is_above_the_current_artifact_in_light_theme(
    user: User,
) -> None:
    course = CourseInput.create(
        unit_name="Programação",
        source_text="Algoritmos, estruturas de dados, funções e testes.",
        audience="Licenciatura",
        duration_hours=12,
    )
    state = create_session(course, agent=create_test_agent())
    final_state = deepcopy(state)
    while final_state["current_stage"] != "final_validation":
        final_state = review_current_stage(
            final_state,
            "approve",
            agent=create_test_agent(),
        )
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_decision_position")
    def decision_position_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_decision_position")

    decision_elements = user.find(marker="teacher-decision").elements
    artifact_elements = user.find(marker="artifact-content").elements
    assert len(decision_elements) == 1
    assert len(artifact_elements) == 1
    decision = next(iter(decision_elements))
    artifact = next(iter(artifact_elements))
    assert decision.id < artifact.id
    assert not hasattr(interfaces[-1], "dark_mode")
    assert "workspace-grid" not in app.APP_CSS
    assert "background: var(--agir-primary) !important;" in app.APP_CSS
    assert "color: #ffffff !important;" in app.APP_CSS
    assert (
        ".info-chip *, .info-chip .q-icon { color: #ffffff !important; }"
        in app.APP_CSS
    )
    assert "repeat(var(--stage-count), minmax(126px, 1fr))" in app.APP_CSS

    with user:
        interfaces[-1].state = final_state
        interfaces[-1].show_workspace()
    final_toolbars = user.find(marker="final-stage-toolbar").elements
    final_decisions = user.find(marker="teacher-decision").elements
    final_artifacts = user.find(marker="artifact-content").elements
    assert len(final_toolbars) == 1
    assert len(final_decisions) == 1
    assert len(final_artifacts) == 1
    assert next(iter(final_toolbars)).id < next(iter(final_decisions)).id
    assert next(iter(final_decisions)).id < next(iter(final_artifacts)).id


@pytest.mark.asyncio
async def test_manual_first_workspace_allows_free_navigation_and_editing(
    user: User,
    tmp_path: Path,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    service = ApplicationService(SQLiteSessionStore(tmp_path / "manual-ui.db"))
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_manual_first_workspace")
    def manual_first_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_manual_first_workspace")

    await user.should_see("Dados iniciais")
    assert user.find(marker="manual-stage-initial_data").elements
    await user.should_see("Ponto atual · Rascunho")
    assert user.find(marker="stage-status-draft").elements
    assert user.find(marker="stage-status-empty").elements
    await user.should_not_see("Autoria manual com IA facultativa")
    await user.should_see("Etapa seguinte")
    await user.should_not_see("Continuar sem executar a IA")
    await user.should_not_see("CONTROLO DO DOCENTE")
    await user.should_see("ASSISTÊNCIA COM IA")
    await user.should_not_see("ASSISTÊNCIA LOCALIZADA DA IA")
    await user.should_see("Criar etapa completa com IA")
    await user.should_see("Pedir propostas à IA")
    await user.should_see("Conteúdos e objetivos curriculares")
    create_button = next(iter(user.find(marker="create-ai-version").elements))
    assistance_heading = next(
        iter(user.find(marker="ai-assistance-heading").elements)
    )
    proposal_button = next(iter(user.find(marker="open-ai-assistance").elements))
    verify_button = next(iter(user.find(marker="verify-stage-with-ai").elements))
    edit_button = next(iter(user.find(marker="edit-artifact-content").elements))
    toolbar = next(iter(user.find(marker="stage-toolbar").elements))
    assert toolbar.id < create_button.id
    assert edit_button.id < assistance_heading.id
    assert assistance_heading.id < create_button.id < proposal_button.id < verify_button.id
    user.find(marker="stage-toolbar-help-authoring").click()
    await user.should_see("Autoria da etapa")
    await user.should_see("Esta ação não pertence à assistência com IA")
    user.find(marker="close-toolbar-help").click()
    user.find(marker="open-ai-assistance").click()
    await user.should_see("Pedir uma proposta localizada")
    await user.should_see("Âmbito da assistência")
    assert user.find(marker="ai-assistance-request").elements
    user.find(marker="submit-ai-assistance-request").elements
    user.find(marker="cancel-ai-assistance").click()
    user.find(marker="edit-artifact-content").click()
    await user.should_see("EDIÇÃO NA TABELA ATUAL")
    await user.should_see("Adicionar linha")
    assert interfaces[-1].manual_edit_stage == "learning_outcomes"
    user.find("Adicionar linha").click()
    await user.should_see("RA1")
    assert interfaces[-1].manual_edit_artifact[0]["id"] == "RA1"
    id_control = next(
        iter(user.find(marker="learning-outcome-id").elements)
    )
    assert id_control._props.get("readonly") is True
    user.find("Cancelar edição").click()
    user.find(marker="manual-stage-pedagogical_design").click()
    await user.should_see("Organização da sequência pedagógica — versão 1", retries=20)
    await user.should_not_see("RECURSOS A PREPARAR")
    user.find(marker="manual-stage-resources").click()
    await user.should_see("RECURSOS A PREPARAR", retries=20)
    await user.should_see("Guardar seleção de recursos", retries=20)
    resource_settings_button = next(
        iter(user.find("Guardar seleção de recursos").elements)
    )
    create_button = next(iter(user.find(marker="create-ai-version").elements))
    assistance_heading = next(
        iter(user.find(marker="ai-assistance-heading").elements)
    )
    assert assistance_heading.id < create_button.id < resource_settings_button.id
    user.find(marker="manual-stage-curriculum_analysis").click()
    await user.should_see("Objetivos gerais")
    await user.should_see("Criar etapa completa com IA")
    assert interfaces[-1].state["current_stage"] == "curriculum_analysis"


@pytest.mark.asyncio
async def test_curriculum_content_ids_are_readonly_in_the_editor(user: User) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, estruturas de dados, funções, testes e controlo de fluxo.",
        )
    )
    state["curriculum_analysis"] = {
        "summary": "Síntese.",
        "objectives": "Objetivos.",
        "assumptions": [],
        "contents": [
            {
                "id": "C1",
                "outcome_ids": [],
                "title": "Algoritmos",
                "description": "Fundamentos de algoritmos.",
            }
        ],
    }
    state = navigate_to_stage(state, "curriculum_analysis")

    @ui.page("/_test_readonly_curriculum_content_ids")
    def readonly_curriculum_content_ids_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_readonly_curriculum_content_ids")
    user.find(marker="edit-artifact-content").click()

    content_id_control = next(iter(user.find(marker="content-id").elements))
    assert content_id_control.value == "C1"
    assert content_id_control._props.get("readonly") is True


@pytest.mark.asyncio
async def test_outcome_reference_select_shows_descriptions_only_in_options(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos fundamentais de um algoritmo.",
        },
        {
            "id": "RA2",
            "outcome_type": "Conhecimento prático",
            "theme": "Testes",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar resultados de testes com casos concretos.",
        },
    ]
    state["teaching_activities"] = [
        {
            "id": "AE1",
            "outcome_ids": ["RA1"],
            "learning_context": "Presencial",
            "activity": "Exploração orientada.",
            "practice": "Resolver exemplos.",
            "support": "Acompanhamento do docente.",
            "feedback_strategy": "Feedback formativo.",
        }
    ]
    state = navigate_to_stage(state, "teaching_activities")

    @ui.page("/_test_outcome_reference_labels")
    def outcome_reference_labels_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_outcome_reference_labels")
    user.find(marker="edit-artifact-content").click()

    controls = user.find(marker="learning-outcome-reference").elements
    assert len(controls) == 1
    control = next(iter(controls))
    assert control.options["RA1"] == (
        "RA1 — Identificar os elementos fundamentais de um algoritmo."
    )
    assert control.value == ["RA1"]
    assert "selected-item" in control.slots
    selected_template = str(control.slots["selected-item"].template)
    assert "props.opt.label" in selected_template
    assert "scope." not in selected_template
    assert "split(' — ')[0]" in selected_template
    assert "removable" not in selected_template
    assert "removeAtIndex" not in selected_template


@pytest.mark.asyncio
async def test_ai_review_findings_focus_the_related_artifact(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    finding = {
        "severity": "warning",
        "criterion": "Clareza dos resultados",
        "message": "Clarificar o enunciado do RA1.",
        "target": "RA1",
    }
    review = {
        "timestamp": "2026-08-27 18:30:00 UTC",
        "context_signature": "",
        "passed": True,
        "findings": [finding],
        "revision_instructions": "Clarificar RA1.",
        "metadata": {"provider": "Teste", "model": "critic-fake"},
        "non_blocking": True,
    }
    state["ai_reviews"] = {"learning_outcomes": [review]}
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos de um algoritmo.",
        }
    ]
    review["context_signature"] = ai_review_context_signature(
        state, "learning_outcomes"
    )
    focus_handlers: list[AsyncMock] = []

    @ui.page("/_test_ai_review_focus")
    def ai_review_focus_page():
        interface = app.AGIRSoloInterface()

        async def record_focus(*_args, **_kwargs) -> None:
            ui.notify("Artefacto localizado.")

        handler = AsyncMock(side_effect=record_focus)
        interface._focus_stage_finding = handler
        interface.state = state
        interface.show_workspace()
        focus_handlers.append(handler)

    await user.open("/_test_ai_review_focus")

    await user.should_see(
        "Selecione uma observação para localizar o conteúdo relacionado."
    )
    artifact = next(iter(user.find(marker="artifact-content").elements))
    assert "stage-artifact-focus" in artifact._classes
    user.find(marker="ai-review-finding-0").click()
    await user.should_see("Artefacto localizado.")

    focus_handlers[-1].assert_awaited_once_with(finding)
    selector, activate_selector = app.AGIRSoloInterface._structured_focus_plan(
        state,
        "learning_outcomes",
        "RA1",
    )
    assert selector.endswith("tbody tr:nth-child(1)")
    assert activate_selector == ""


def test_structured_focus_distinguishes_ra1_from_ra10() -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["learning_outcomes"] = [
        {"id": "RA10", "statement": "Analisar algoritmos complexos."},
        {"id": "RA1", "statement": "Identificar elementos de algoritmos."},
    ]

    selector, _activate = app.AGIRSoloInterface._structured_focus_plan(
        state,
        "learning_outcomes",
        "RA1",
    )

    assert selector.endswith("tbody tr:nth-child(2)")
    assert "RA1" not in selector


@pytest.mark.asyncio
async def test_final_validation_controls_are_clickable(user: User) -> None:
    state = navigate_to_stage(
        create_session(
            CourseInput.create(
                "Programação",
                "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
            )
        ),
        "final_validation",
    )
    focus_handlers: list[AsyncMock] = []

    @ui.page("/_test_final_validation_links")
    def final_validation_links_page():
        interface = app.AGIRSoloInterface()

        async def record_focus(*_args, **_kwargs) -> None:
            ui.notify("Controlo localizado.")

        handler = AsyncMock(side_effect=record_focus)
        interface._focus_final_validation_result = handler
        interface.state = state
        interface.show_workspace()
        focus_handlers.append(handler)

    await user.open("/_test_final_validation_links")
    await user.should_see("CONTROLOS DA ESTRUTURA E DO ALINHAMENTO")
    await user.should_see("QUALIDADE AUTOMÁTICA DOS RECURSOS")

    structural = next(
        item
        for item in state["final_validation"]["checks"]
        if item["id"] == "stage_learning_outcomes"
    )
    user.find(marker="final-validation-check-stage_learning_outcomes").click()
    await user.should_see("Controlo localizado.")
    focus_handlers[-1].assert_awaited_once_with(structural)

    quality_button = next(
        iter(user.find(marker="resource-quality-check-unique_outcomes").elements)
    )
    assert "validation-result-link" in quality_button._classes


@pytest.mark.asyncio
async def test_final_validation_arms_the_target_before_changing_stage() -> None:
    state = navigate_to_stage(
        create_session(
            CourseInput.create(
                "Programação",
                "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
            )
        ),
        "final_validation",
    )
    result = next(
        item
        for item in state["final_validation"]["checks"]
        if item["id"] == "stage_learning_outcomes"
    )
    interface = object.__new__(app.AGIRSoloInterface)
    interface.state = state
    interface._arm_scroll_and_highlight = AsyncMock()
    interface._focus_structured_target = AsyncMock()

    async def navigate(target_stage: str, *, notice: str = "") -> None:
        interface.state["current_stage"] = target_stage

    interface._navigate_manual_stage = AsyncMock(side_effect=navigate)

    await interface._focus_final_validation_result(result)

    selector, activate_selector = interface._structured_focus_plan(
        state,
        "learning_outcomes",
        "__stage__",
    )
    interface._arm_scroll_and_highlight.assert_awaited_once_with(
        selector,
        activate_selector=activate_selector,
    )
    interface._navigate_manual_stage.assert_awaited_once_with(
        "learning_outcomes",
        notice="Controlo localizado na etapa correspondente.",
    )
    interface._focus_structured_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_history_offers_explicit_version_restore(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    first = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos de um algoritmo.",
        }
    ]
    second = deepcopy(first)
    second[0]["statement"] = "Identificar os elementos essenciais de um algoritmo."
    state = save_manual_draft(state, "learning_outcomes", first)
    state = save_manual_draft(state, "learning_outcomes", second)

    @ui.page("/_test_manual_history_restore")
    def manual_history_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_manual_history_restore")

    expansion = next(
        iter(user.find(marker="history-audit-expansion").elements)
    )
    assert expansion.value is False
    user.find(marker="history-audit-expansion").click()
    await user.should_see("Restaurar versão selecionada")
    await user.should_see("voltar a tornar ativa")
    history_select = next(
        iter(user.find(marker="history-version-select").elements)
    )
    restore_button = next(
        iter(user.find(marker="restore-history-version").elements)
    )
    assert history_select.parent_slot.parent.id == restore_button.parent_slot.parent.id


@pytest.mark.asyncio
async def test_ai_version_action_remains_available_after_content_exists(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos de um algoritmo.",
        }
    ]

    @ui.page("/_test_first_ai_version_with_content")
    def first_ai_version_with_content_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_first_ai_version_with_content")

    await user.should_see("Criar etapa completa com IA")
    await user.should_see("Pedir propostas à IA")


@pytest.mark.asyncio
async def test_ai_version_action_requests_the_complete_stage(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    handlers: list[AsyncMock] = []

    @ui.page("/_test_first_ai_version_action")
    def first_ai_version_action_page():
        interface = app.AGIRSoloInterface()

        async def record_request(*_args, **_kwargs) -> None:
            ui.notify("Pedido da versão registado.")

        handler = AsyncMock(side_effect=record_request)
        interface._handle_ai_assistance = handler
        interface.state = state
        interface.show_workspace()
        handlers.append(handler)

    await user.open("/_test_first_ai_version_action")

    user.find("Criar etapa completa com IA").click()
    await user.should_see("Pedido da versão registado.")

    handlers[-1].assert_awaited_once_with(
        "learning_outcomes",
        [],
        "Toda a etapa",
        "Crie uma versão completa desta etapa com base no contexto da "
        "unidade curricular, no rascunho atual e nos artefactos anteriores.",
    )


@pytest.mark.asyncio
async def test_localized_ai_action_uses_the_toolbar_dialog(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    handlers: list[AsyncMock] = []

    @ui.page("/_test_toolbar_ai_dialog")
    def toolbar_ai_dialog_page():
        interface = app.AGIRSoloInterface()

        async def record_request(*_args, **_kwargs) -> None:
            ui.notify("Pedido localizado registado.")

        handler = AsyncMock(side_effect=record_request)
        interface._handle_ai_assistance = handler
        interface.state = state
        interface.show_workspace()
        handlers.append(handler)

    await user.open("/_test_toolbar_ai_dialog")

    user.find(marker="open-ai-assistance").click()
    await user.should_see("Pedir uma proposta localizada")
    handlers[-1].assert_not_awaited()
    user.find(marker="submit-ai-assistance-request").click()
    await user.should_see("Pedido localizado registado.")

    handlers[-1].assert_awaited_once_with(
        "learning_outcomes",
        [],
        "Toda a etapa",
        "",
    )


@pytest.mark.asyncio
async def test_first_resource_generation_requires_explicit_confirmation(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state = navigate_to_stage(state, "resources")
    handlers: list[AsyncMock] = []

    @ui.page("/_test_first_resource_generation_confirmation")
    def first_resource_generation_confirmation_page():
        interface = app.AGIRSoloInterface()

        async def record_request(*_args, **_kwargs) -> None:
            ui.notify("Geração de recursos registada.")

        handler = AsyncMock(side_effect=record_request)
        interface._handle_ai_assistance = handler
        interface.state = state
        interface.show_workspace()
        handlers.append(handler)

    await user.open("/_test_first_resource_generation_confirmation")

    user.find("Criar etapa completa com IA").click()
    await user.should_see("Confirmar geração dos recursos selecionados")
    await user.should_see("pode originar várias chamadas")
    handlers[-1].assert_not_awaited()
    user.find(marker="confirm-resource-generation").click()
    await user.should_see("Geração de recursos registada.")

    handlers[-1].assert_awaited_once_with(
        "resources",
        [],
        "Toda a etapa",
        "Crie uma versão completa desta etapa com base no contexto da "
        "unidade curricular, no rascunho atual e nos artefactos anteriores.",
    )


@pytest.mark.asyncio
async def test_resources_are_separated_into_tabs_in_view_and_edit_modes(
    user: User,
) -> None:
    agent = create_test_agent()
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        ),
        resource_types=[
            RESOURCE_PRESENTATION,
            RESOURCE_WORKSHEET,
            RESOURCE_TEST,
            RESOURCE_PRACTICAL,
        ],
        agent=agent,
    )
    for _ in range(5):
        state = review_current_stage(state, "approve", agent=agent)
    assert state["current_stage"] == "resources"
    state["orchestration"]["mode"] = "manual-first"
    state["source_images"] = [
        {
            "id": "document-ui-test",
            "origin_type": "document",
            "source_file": "apoio.pdf",
            "source_location": "Página 2",
            "media_type": "image/png",
            "thumbnail_media_type": "image/png",
            "thumbnail_base64": (
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
            ),
            "approved": False,
        }
    ]
    assert len(state["resources"]["presentation_outline"]) >= 5
    fifth_slide = state["resources"]["presentation_outline"][4]
    fifth_slide["visual_mode"] = "documento"
    fifth_slide["visual_asset_id"] = "document-ui-test"
    fifth_slide["visual_title"] = "Visual exclusivo do slide 5"
    fifth_slide["visual_source"] = "Imagem extraída de apoio.pdf, Página 2."
    fifth_slide["visual_warning"] = "Aviso técnico que não deve aparecer na etapa."
    state.setdefault("ai_reviews", {})["resources"] = [
        {
            "findings": [
                {
                    "severity": "blocking",
                    "criterion": "assessment_coverage",
                    "message": "Parecer antigo que já não corresponde aos artefactos.",
                }
            ],
            "non_blocking": True,
        }
    ]
    active_resource_version = int(state["active_versions"]["resources"])
    state["versions"]["resources"][active_resource_version - 1] = deepcopy(
        state["resources"]
    )

    @ui.page("/_test_resource_tabs")
    def resource_tabs_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_resource_tabs")

    await user.should_see("CONTEÚDO DOS RECURSOS")
    await user.should_not_see("IMAGENS DOCUMENTAIS CANDIDATAS")
    await user.should_see("VERIFICAÇÃO FACULTATIVA DA IA DESATUALIZADA")
    await user.should_not_see(
        "Parecer antigo que já não corresponde aos artefactos."
    )
    await user.should_see("Modo visual")
    await user.should_not_see("AVISOS VISUAIS")
    await user.should_not_see("IMAGENS SELECIONADAS")
    assert len(user.find(marker="presentation-view-thumbnail-5").elements) == 1
    for tab_id in ("presentation", "worksheet", "test", "practical"):
        assert len(user.find(marker=f"resource-view-tab-{tab_id}").elements) == 1

    user.find(marker="resource-view-tab-worksheet").click()
    await user.should_see("Enquadramento:")
    user.find(marker="resource-view-tab-test").click()
    await user.should_see("Chave de correção")
    user.find(marker="resource-view-tab-practical").click()
    await user.should_see("Entregáveis:")

    user.find(marker="edit-artifact-content").click()
    for tab_id in ("presentation", "worksheet", "test", "practical"):
        assert len(user.find(marker=f"resource-edit-tab-{tab_id}").elements) == 1

    await user.should_see("Slides da apresentação")
    await user.should_see("Slide 1 —")
    await user.should_see("Elementos do diagrama — 2 a 4, um por linha")
    await user.should_see("introduza entre 2 e 4 elementos não vazios")
    await user.should_not_see("Origem visual")
    await user.should_not_see("Modo visual")
    fifth_expansion = next(
        iter(user.find(marker="presentation-slide-5").elements)
    )
    fifth_expansion.value = True
    await user.should_see("Visual exclusivo do slide 5")
    user.find(marker="choose-slide-image-5").click()
    await user.should_see("Imagem associada ao slide")
    assert len(user.find(marker="presentation-image-tab-available").elements) == 1
    assert len(user.find(marker="presentation-image-tab-generate").elements) == 1
    assert len(user.find(marker="presentation-image-tab-upload").elements) == 1
    user.find(marker="presentation-image-tab-generate").click()
    await user.should_see("Pode gerar mais 2 de 2 imagens adicionais")
    assert len(user.find(marker="suggest-slide-image-prompt-5").elements) == 1
    assert len(user.find(marker="generate-slide-image-5").elements) == 1
    user.find(marker="presentation-image-tab-upload").click()
    assert len(user.find(marker="upload-slide-image-5").elements) == 1
    user.find(marker="presentation-image-tab-available").click()
    await user.should_see("apoio.pdf — Página 2")
    user.find(marker="select-slide-image-document-ui-test").click()
    await user.should_see("Imagem documental")
    await user.should_see("Visual exclusivo do slide 5")
    user.find(marker="resource-edit-tab-worksheet").click()
    await user.should_see("Ficha — enquadramento")
    user.find(marker="resource-edit-tab-test").click()
    await user.should_see("Teste — cotação total")
    user.find(marker="resource-edit-tab-practical").click()
    await user.should_see("Critérios da atividade prática")


@pytest.mark.asyncio
async def test_manual_first_workspace_renders_a_pending_ai_proposal(
    user: User,
    tmp_path: Path,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar algoritmos.",
        }
    ]
    state["ai_proposals"] = [
        {
            "id": "P1",
            "stage": "learning_outcomes",
            "scope_path": [0],
            "scope_label": "Linha 1 (RA1)",
            "instruction": "Melhorar a linha.",
            "before": deepcopy(state["learning_outcomes"][0]),
            "after": {
                **state["learning_outcomes"][0],
                "theme": "Algoritmos eficientes",
                "statement": "Analisar algoritmos através de exemplos concretos.",
            },
            "status": "pending",
            "metadata": {"provider": "Teste"},
        }
    ]

    interfaces: list[app.AGIRSoloInterface] = []
    service = ApplicationService(SQLiteSessionStore(tmp_path / "inline-proposal.db"))

    @ui.page("/_test_pending_ai_proposal")
    def pending_proposal_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_pending_ai_proposal")

    await user.should_see("PROPOSTA PENDENTE")
    await user.should_see("REVISÃO DA PROPOSTA DA IA")
    await user.should_see("Atual")
    await user.should_see("Sugestão da IA")
    await user.should_see("Analisar algoritmos.")
    await user.should_see("Analisar algoritmos através de exemplos concretos.")
    await user.should_see("Aceitar")
    await user.should_see("Rejeitar")
    await user.should_see("Aplicar alterações aceites")
    await user.should_see("Rejeitar todas as alterações")
    assert user.find(marker="inline-ai-proposal").elements

    next(iter(user.find(marker="ai-decision-change-1").elements)).set_value(
        "Rejeitar"
    )
    next(iter(user.find(marker="ai-change-change-2").elements)).set_value(
        "Analisar algoritmos com casos reais."
    )
    user.find("Aplicar alterações aceites").click()
    await user.should_not_see("PROPOSTA PENDENTE")

    assert interfaces[-1].state["learning_outcomes"][0]["theme"] == "Algoritmos"
    assert interfaces[-1].state["learning_outcomes"][0]["statement"].endswith(
        "casos reais."
    )
    assert interfaces[-1].state["ai_proposals"][-1]["status"] == "partially_accepted"
    assert len(interfaces[-1].state["versions"]["learning_outcomes"]) == 1


@pytest.mark.asyncio
async def test_stale_ai_proposal_review_closes_when_decision_is_already_saved(
    user: User,
    tmp_path: Path,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar algoritmos.",
        }
    ]
    state["ai_proposals"] = [
        {
            "id": "P1",
            "stage": "learning_outcomes",
            "scope_path": [0],
            "scope_label": "Linha 1 (RA1)",
            "instruction": "Melhorar a linha.",
            "before": deepcopy(state["learning_outcomes"][0]),
            "after": {
                **state["learning_outcomes"][0],
                "statement": "Analisar algoritmos através de exemplos concretos.",
            },
            "status": "pending",
            "metadata": {"provider": "Teste"},
        }
    ]

    interfaces: list[app.AGIRSoloInterface] = []
    service = ApplicationService(SQLiteSessionStore(tmp_path / "stale-proposal.db"))

    @ui.page("/_test_stale_ai_proposal")
    def stale_proposal_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_stale_ai_proposal")
    await user.should_see("PROPOSTA PENDENTE")

    # Simula a decisão persistida entre o desenho do cartão e uma reconexão.
    interfaces[-1].state["ai_proposals"][0]["status"] = "accepted"
    user.find("Rejeitar todas as alterações").click()

    await user.should_not_see("PROPOSTA PENDENTE")
    await user.should_not_see("Esta proposta de IA já foi decidida.")
    await user.should_see("Analisar algoritmos.")


@pytest.mark.asyncio
async def test_complete_resource_proposal_reuses_editor_and_hides_unselected_resources(
    user: User,
    tmp_path: Path,
) -> None:
    agent = create_test_agent()
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        ),
        resource_types=[RESOURCE_PRESENTATION],
        agent=agent,
    )
    for _ in range(5):
        state = review_current_stage(state, "approve", agent=agent)
    assert state["current_stage"] == "resources"
    before = deepcopy(state["resources"])
    proposed = deepcopy(before)
    proposed["presentation_outline"][0]["title"] = "Apresentação proposta"
    proposed["lesson_worksheet"] = {
        "title": "Ficha que não foi selecionada",
        "overview": "Não deve aparecer.",
        "instructions": "Não deve aparecer.",
        "sections": [
            {
                "heading": "Secção indevida",
                "content": "Conteúdo indevido.",
                "outcome_ids": ["RA1"],
                "activity": "Atividade indevida.",
            }
        ],
    }
    state["ai_proposals"] = [
        {
            "id": "P1",
            "stage": "resources",
            "scope_path": [],
            "scope_label": "Toda a etapa",
            "instruction": "Criar a etapa completa.",
            "before": before,
            "after": proposed,
            "status": "pending",
            "metadata": {"provider": "Teste"},
            "generated_images": [],
        }
    ]

    interfaces: list[app.AGIRSoloInterface] = []
    service = ApplicationService(SQLiteSessionStore(tmp_path / "resource-proposal.db"))

    @ui.page("/_test_complete_resource_proposal")
    def complete_resource_proposal_page():
        interface = app.AGIRSoloInterface(service=service)
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_complete_resource_proposal")

    assert user.find(marker="resource-ai-proposal-review").elements
    assert len(user.find(marker="resource-edit-tab-presentation").elements) == 1
    await user.should_see("Slides da apresentação")
    await user.should_see("Slide 1 — Apresentação proposta")
    await user.should_not_see("Ficha que não foi selecionada")

    user.find(marker="apply-edited-resource-proposal").click()
    await user.should_not_see("REVISÃO DA PROPOSTA DA IA")

    applied = interfaces[-1].state
    assert applied["resources"]["presentation_outline"][0]["title"] == (
        "Apresentação proposta"
    )
    assert applied["resources"]["lesson_worksheet"]["sections"] == []
    assert applied["ai_proposals"][-1]["review_mode"] == (
        "edited_complete_resource"
    )


def test_export_format_choice_maps_to_requested_document_formats() -> None:
    assert app._document_formats_for_export_choice("word") == ("word",)
    assert app._document_formats_for_export_choice("latex") == ("latex",)
    assert app._document_formats_for_export_choice("both") == ("word", "latex")


@pytest.mark.asyncio
async def test_completed_view_offers_word_latex_or_both(
    user: User,
) -> None:
    course = CourseInput.create(
        unit_name="Programação",
        source_text="Algoritmos, estruturas de dados, funções e testes automatizados.",
        audience="Licenciatura",
        duration_hours=12,
    )
    agent = create_test_agent()
    state = create_session(course, resource_types=[RESOURCE_TEST], agent=agent)
    while state.get("status") != "completed":
        state = review_current_stage(state, "approve", agent=agent)
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_export_formats")
    def export_formats_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_export_formats")

    await user.should_see("Formato dos documentos editáveis")
    await user.should_see(app.EXPORT_DOCUMENT_FORMAT_CHOICES["word"])
    await user.should_see(app.EXPORT_DOCUMENT_FORMAT_CHOICES["latex"])
    await user.should_see(app.EXPORT_DOCUMENT_FORMAT_CHOICES["both"])
    assert interfaces[-1].export_document_format == "word"


@pytest.mark.asyncio
async def test_completed_manual_session_requires_explicit_reopen_dialog(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, estruturas de dados, funções e testes automatizados.",
        )
    )
    state = navigate_to_stage(state, "final_validation")
    state["status"] = "completed"

    @ui.page("/_test_manual_completed_reopen")
    def manual_completed_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_manual_completed_reopen")

    await user.should_see("Sessão concluída")
    user.find(marker="reopen-completed-session").click()
    await user.should_see("REABERTURA EXPLÍCITA")
    await user.should_see("Motivo da reabertura")


@pytest.mark.asyncio
async def test_manual_table_editor_renders_for_the_current_stage(
    user: User,
) -> None:
    course = CourseInput.create(
        unit_name="Programação",
        source_text="Algoritmos, variáveis, estruturas de dados, funções e testes.",
        audience="Licenciatura",
        duration_hours=12,
    )
    agent = create_test_agent()
    state = create_session(course, agent=agent)
    state = review_current_stage(state, "approve", agent=agent)
    state = review_current_stage(state, "approve", agent=agent)
    original = deepcopy(state)
    interfaces: list[app.AGIRSoloInterface] = []

    @ui.page("/_test_manual_editor")
    def manual_editor_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()
        interfaces.append(interface)

    await user.open("/_test_manual_editor")

    await user.should_see("Editar a tabela manualmente")
    user.find("Editar a tabela manualmente").click()
    await user.should_see("EDIÇÃO NA TABELA ATUAL")
    user.find("Cancelar edição").click()
    with user:
        interfaces[-1]._view_stage("curriculum_analysis")
    await user.should_see("MODO DE CONSULTA")
    user.find(marker="return-current-stage").click()
    await user.should_not_see("MODO DE CONSULTA")
    assert interfaces[-1].viewed_stage is None

    with user:
        interfaces[-1]._view_stage("curriculum_analysis")
    user.find("Editar esta tabela").click()
    await user.should_see("EDIÇÃO NA TABELA ATUAL")
    await user.should_not_see("MODO DE CONSULTA")
    await user.should_see("Conteúdos identificados")
    await user.should_see("Adicionar linha")
    await user.should_see("Guardar nova versão")
    assert interfaces[-1].manual_edit_stage == "curriculum_analysis"
    user.find("Cancelar edição").click()
    await user.should_see("MODO DE CONSULTA")
    assert interfaces[-1].manual_edit_stage is None
    assert state == original


def test_loading_a_session_restores_all_initial_fields() -> None:
    course = CourseInput.create(
        unit_name="Introdução às Pescas",
        source_text=(
            "[Texto introduzido pelo docente]\nEcossistemas aquáticos, artes de "
            "pesca, gestão sustentável dos recursos e segurança das operações "
            "marítimas.\n\n[Ficheiro: apoio.pdf]\nConteúdo complementar."
        ),
        audience="Estudantes de licenciatura",
        duration_hours=18,
        taxonomy_type="Bloom",
        program_name="Engenharia do Ambiente",
        program_type="Licenciatura",
        academic_year="1.º ano",
        semester="1.º semestre",
        cnaef_code="852",
        cnaef_name="Ambientes naturais e vida selvagem",
        ects_credits=6,
        contact_hours=45,
        autonomous_hours=117,
        general_aims="Compreender o setor pesqueiro de forma integrada.",
        bibliography="FAO. (2024). Relatório sobre pescas sustentáveis.",
    )
    resources = [RESOURCE_TEST, RESOURCE_PRACTICAL]
    state = create_session(
        course,
        resource_types=resources,
        agent=create_test_agent(),
        ai_provider="IAedu",
    )

    with TemporaryDirectory() as temporary_directory:
        store = SQLiteSessionStore(Path(temporary_directory) / "agir_solo.db")
        service = ApplicationService(store)
        session_id = store.save(state)
        restored_state = service.load_session(session_id)
        fields = service.restored_initial_fields(restored_state)

    assert fields["unit_name"] == course.unit_name
    assert fields["audience"] == course.audience
    assert fields["duration_hours"] == course.duration_hours
    assert fields["taxonomy_type"] == "Bloom"
    assert fields["ai_provider"] == "IAedu"
    assert fields["resource_types"] == resources
    assert fields["source_text"].startswith("Ecossistemas aquáticos")
    assert "[Texto introduzido pelo docente]" not in fields["source_text"]
    assert "[Ficheiro:" not in fields["source_text"]
    assert fields["program_name"] == course.program_name
    assert fields["general_aims"] == course.general_aims
    assert fields["bibliography"] == course.bibliography


def test_opening_a_previous_stage_is_read_only() -> None:
    course = CourseInput.create(
        unit_name="Programação",
        source_text="Algoritmos, estruturas de dados, funções e testes.",
        audience="Licenciatura",
        duration_hours=12,
    )
    agent = create_test_agent()
    state = create_session(course, agent=agent)
    state = review_current_stage(state, "approve", agent=agent)
    state = review_current_stage(state, "approve", agent=agent)
    original = deepcopy(state)
    messages: list[str] = []

    interface = object.__new__(app.AGIRSoloInterface)
    interface.state = state
    interface.viewed_stage = None
    interface._render_workspace = messages.append

    interface._view_stage("curriculum_analysis")

    assert interface.viewed_stage == "curriculum_analysis"
    assert state == original
    assert "apenas para consulta" in messages[-1]

    interface._return_to_current_stage()
    assert interface.viewed_stage is None
    assert state == original


def test_application_service_cannot_load_another_owner_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    session_id = store.save(
        {
            "course": {"unit_name": "UC reservada"},
            "current_stage": "contents",
            "status": "in_progress",
            "audit": [],
        },
        owner_id="D01",
    )

    owner_service = ApplicationService(store, owner_id="D01")
    other_service = ApplicationService(store, owner_id="D02")

    assert owner_service.load_session(session_id)["course"]["unit_name"] == "UC reservada"
    assert other_service.list_sessions() == []
    with pytest.raises(ValueError, match="já não está disponível"):
        other_service.load_session(session_id)


def test_application_service_deletes_only_owner_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    session_id = store.save(
        {
            "course": {"unit_name": "UC a eliminar"},
            "current_stage": "contents",
            "status": "in_progress",
            "audit": [],
        },
        owner_id="D01",
    )

    owner_service = ApplicationService(store, owner_id="D01")
    other_service = ApplicationService(store, owner_id="D02")

    with pytest.raises(ValueError, match="já não está disponível"):
        other_service.delete_session(session_id)

    assert store.load(session_id, owner_id="D01") is not None
    owner_service.delete_session(session_id)
    assert store.load(session_id, owner_id="D01") is None


@pytest.mark.asyncio
async def test_session_drawer_exposes_backup_and_restore_actions(
    user: User,
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    state = create_session(
        CourseInput.create(
            "Introdução à Psicologia",
            "Conceitos, métodos de investigação e teorias psicológicas.",
        )
    )
    store.save(state, owner_id="D01")
    service = ApplicationService(store, owner_id="D01")

    @ui.page("/_test_session_backup_actions")
    def session_backup_actions_page():
        app.AGIRSoloInterface(service)

    await user.open("/_test_session_backup_actions")

    await user.should_see("Restaurar cópia de segurança")
    assert len(user.find(marker="open-session-restore").elements) == 1
    assert len(user.find(marker="backup-session").elements) == 1
    user.find(marker="open-session-restore").click()
    await user.should_see("Restaurar uma sessão")
    assert len(user.find(marker="session-restore-upload").elements) == 1


def test_manual_assistance_validates_without_starting_a_session() -> None:
    result = ApplicationService.validate_initial_form(
        {
            "unit_name": "Introdução às Pescas",
            "source_text": (
                "Conteúdos suficientemente detalhados para validar o formulário inicial."
            ),
            "audience": "Licenciatura",
            "program_type": "Licenciatura",
            "duration_hours": 18,
            "taxonomy_type": "SOLO",
            "semester": "1.º semestre",
        }
    )

    assert result["valid"]
    assert result["suggestions"]


def test_session_duration_is_derived_from_contact_and_autonomous_work() -> None:
    with TemporaryDirectory() as temporary_directory:
        service = ApplicationService(
            SQLiteSessionStore(Path(temporary_directory) / "duration.db")
        )
        state = service.start_session(
            {
                "unit_name": "Introdução às Pescas",
                "source_text": (
                    "Ecossistemas aquáticos, técnicas de captura e gestão "
                    "sustentável dos recursos pesqueiros."
                ),
                "program_type": "Licenciatura",
                "duration_hours": 999,
                "contact_hours": 45.5,
                "autonomous_hours": 116.75,
                "taxonomy_type": "SOLO",
                "semester": "1.º semestre",
                "resource_types": [RESOURCE_PRESENTATION],
            }
        )

    assert state["course"]["duration_hours"] == 162.25
