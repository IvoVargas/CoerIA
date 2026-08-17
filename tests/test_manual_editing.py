from prism.manual_editing import (
    editor_layout,
    format_editor_value,
    new_table_row,
    parse_editor_value,
    value_at_path,
)
from prism.models import CourseInput
from prism.presentation import active_stage_artifact
from prism.workflow import (
    STAGE_ORDER,
    create_session,
    create_test_agent,
    review_current_stage,
)


def _completed_state() -> dict:
    course = CourseInput.create(
        unit_name="Programação",
        source_text="Algoritmos, variáveis, estruturas de dados, funções e testes.",
        audience="Licenciatura",
        duration_hours=12,
    )
    agent = create_test_agent()
    state = create_session(course, agent=agent)
    for _stage in STAGE_ORDER:
        state = review_current_stage(state, "approve", agent=agent)
    return state


def test_every_authorship_stage_has_editable_fields_and_tables() -> None:
    state = _completed_state()

    for stage in STAGE_ORDER[:-1]:
        artifact = active_stage_artifact(state, stage)
        layout = editor_layout(stage)
        assert layout.fields or layout.tables
        for scalar in layout.fields:
            value_at_path(artifact, scalar.path)
        for table in layout.tables:
            rows = value_at_path(artifact, table.path)
            assert isinstance(rows, list)
            added = new_table_row(table)
            rows.append(added)
            assert rows[-1] == table.template
            rows.pop()


def test_relationship_fields_round_trip_through_the_manual_editor() -> None:
    links = [
        {"content_id": "C1", "importance": "Principal"},
        {"content_id": "C2", "importance": "Secundária"},
    ]
    rendered = format_editor_value(links, "content_links")

    assert parse_editor_value(rendered, "content_links") == links
    assert parse_editor_value("RA1, RA2\nRA3", "csv") == ["RA1", "RA2", "RA3"]
    assert parse_editor_value("Primeiro\n\nSegundo", "lines") == [
        "Primeiro",
        "Segundo",
    ]
