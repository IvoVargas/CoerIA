from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from nicegui.testing import User

from prism.application_service import ApplicationService
from prism.models import CourseInput, RESOURCE_PRACTICAL, RESOURCE_TEST
from prism.persistence import SQLiteSessionStore
from prism.workflow import create_session, create_test_agent


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
    await user.should_see("CoerIA v0.1.0 · SQLite")


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
