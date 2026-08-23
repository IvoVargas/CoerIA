from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from nicegui import ui
from nicegui.testing import User

import app
from prism.application_service import ApplicationService
from prism.models import CourseInput, RESOURCE_PRACTICAL, RESOURCE_TEST
from prism.persistence import SQLiteSessionStore
from prism.workflow import (
    create_session,
    create_test_agent,
    navigate_to_stage,
    review_current_stage,
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
    ("phase", "elapsed_seconds", "expected"),
    [
        (
            "A gerar e validar «Recursos educativos»…",
            7,
            "A gerar e validar «Recursos educativos»…",
        ),
        (
            "A gerar e validar «Recursos educativos»…",
            8,
            "A aguardar a resposta do fornecedor de IA…",
        ),
        (
            "A gerar e validar «Recursos educativos»…",
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
    await user.should_see("Da ideia aos recursos, com cada decisão sob o seu controlo.")
    await user.should_see("Preenchimento manual orientado")
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
    assert "background: #edf5f3 !important;" in app.APP_CSS
    assert "color: #064e4a !important;" in app.APP_CSS
    assert ".info-chip * { color: inherit !important; }" in app.APP_CSS

    with user:
        interfaces[-1].state = final_state
        interfaces[-1].show_workspace()
    final_decisions = user.find(marker="teacher-decision").elements
    final_artifacts = user.find(marker="artifact-content").elements
    assert len(final_decisions) == 1
    assert len(final_artifacts) == 1
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

    await user.should_see("IA facultativa")
    await user.should_see("Autoria manual com IA facultativa")
    await user.should_see("Continuar sem executar a IA")
    await user.should_see("Conteúdos e objetivos curriculares")
    user.find("Editar campos e tabelas").click()
    await user.should_see("EDIÇÃO NA TABELA ATUAL")
    await user.should_see("Adicionar linha")
    assert interfaces[-1].manual_edit_stage == "learning_outcomes"
    user.find("Cancelar edição").click()
    user.find(marker="manual-stage-curriculum_analysis").click()
    await user.should_see("Objetivos gerais")
    assert interfaces[-1].state["current_stage"] == "curriculum_analysis"


@pytest.mark.asyncio
async def test_manual_first_workspace_renders_a_pending_ai_proposal(
    user: User,
) -> None:
    state = create_session(
        CourseInput.create(
            "Programação",
            "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        )
    )
    state["ai_proposals"] = [
        {
            "id": "P1",
            "stage": "learning_outcomes",
            "scope_path": [],
            "scope_label": "Toda a etapa",
            "instruction": "Propor um resultado.",
            "before": [],
            "after": [{"id": "RA1", "statement": "Identificar conceitos."}],
            "status": "pending",
            "metadata": {"provider": "Teste"},
        }
    ]

    @ui.page("/_test_pending_ai_proposal")
    def pending_proposal_page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface.show_workspace()

    await user.open("/_test_pending_ai_proposal")

    await user.should_see("PROPOSTA PENDENTE")
    await user.should_see("Antes")
    await user.should_see("Proposta da IA")
    await user.should_see("Aceitar e guardar nova versão")
    await user.should_see("Rejeitar proposta")


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


def test_manual_assistance_validates_without_starting_a_session() -> None:
    result = ApplicationService.validate_initial_form(
        {
            "unit_name": "Introdução às Pescas",
            "source_text": (
                "Conteúdos suficientemente detalhados para validar o formulário inicial."
            ),
            "audience": "Licenciatura",
            "duration_hours": 18,
            "taxonomy_type": "SOLO",
        }
    )

    assert result["valid"]
    assert result["suggestions"]
