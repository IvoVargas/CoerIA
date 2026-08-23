from prism.manual_editing import (
    FieldSpec,
    apply_editor_field_value,
    editor_field_value,
    editor_reference_options,
    editor_reference_value,
    editor_taxonomy_level_options,
    editor_taxonomy_verb_options,
    editor_layout,
    format_editor_value,
    new_table_row,
    parse_editor_value,
    value_at_path,
)
from prism.models import CourseInput
from prism.curriculum import taxonomy_level_label
from prism.presentation import active_stage_artifact, render_stage_artifact
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


def test_learning_outcome_editor_matches_the_visible_table() -> None:
    table = editor_layout("learning_outcomes").tables[0]

    assert [field.label for field in table.fields] == [
        "ID",
        "Tipo",
        "Tema ou objeto",
        "Nível",
        "Verbo",
        "Resultado de aprendizagem",
    ]
    assert any(field.key == "theme" for field in table.fields)
    assert next(field for field in table.fields if field.key == "action_verb").kind == (
        "taxonomy_verb"
    )


def test_curriculum_editor_uses_free_text_objectives_and_links_contents() -> None:
    layout = editor_layout("curriculum_analysis")

    objectives = next(field for field in layout.fields if field.path == ("objectives",))
    assert objectives.label == "Objetivos gerais"
    assert objectives.kind == "long"
    assert [table.title for table in layout.tables] == ["Conteúdos identificados"]
    outcome_field = next(
        field for field in layout.tables[0].fields if field.key == "outcome_ids"
    )
    assert outcome_field.kind == "linked_outcomes"


def test_compact_relationship_fields_preserve_the_internal_model() -> None:
    row = {
        "outcome_id": "RA1",
        "outcome_ids": ["RA1", "RA2"],
        "content_links": [
            {"content_id": "C1", "importance": "Principal"},
            {"content_id": "C2", "importance": "Secundária"},
        ],
    }
    contents = FieldSpec("content_links", "Conteúdos", "content_ids")
    outcomes = FieldSpec("outcome_ids", "Resultados", "linked_outcomes")

    assert editor_field_value(row, contents) == "C1, C2"
    apply_editor_field_value(row, contents, "C2, C3")
    assert row["content_links"] == [
        {"content_id": "C2", "importance": "Secundária"},
        {"content_id": "C3", "importance": "Secundária"},
    ]

    apply_editor_field_value(row, outcomes, "RA3, RA4")
    assert row["outcome_ids"] == ["RA3", "RA4"]
    assert row["outcome_id"] == "RA3"


def test_reference_fields_offer_ids_from_previous_stages() -> None:
    state = _completed_state()
    outcome_field = FieldSpec("outcome_id", "Resultado")
    contents_field = FieldSpec("content_links", "Conteúdos", "content_ids")
    row = state["learning_outcomes"][0]

    outcome_options = editor_reference_options(state, outcome_field)
    content_options = editor_reference_options(state, contents_field)

    assert outcome_options is not None
    assert list(outcome_options) == ["RA1", "RA2", "RA3", "RA4"]
    assert outcome_options["RA1"].startswith("RA1 — ")
    assert content_options is not None
    assert set(editor_reference_value(row, contents_field)) <= set(content_options)


def test_reference_select_values_are_applied_without_free_text_parsing() -> None:
    row = {
        "outcome_id": "RA1",
        "outcome_ids": ["RA1"],
    }
    outcomes = FieldSpec("outcome_ids", "Resultados", "linked_outcomes")

    apply_editor_field_value(row, outcomes, ["RA2", "RA3"])

    assert row["outcome_ids"] == ["RA2", "RA3"]
    assert row["outcome_id"] == "RA2"


def test_learning_outcome_editor_omits_taxonomy_and_numbers_levels() -> None:
    state = _completed_state()
    table = editor_layout("learning_outcomes").tables[0]
    level_field = next(
        field for field in table.fields if field.key == "taxonomy_level"
    )

    assert [field.label for field in table.fields] == [
        "ID",
        "Tipo",
        "Tema ou objeto",
        "Nível",
        "Verbo",
        "Resultado de aprendizagem",
    ]
    options = editor_taxonomy_level_options(state, level_field)
    assert options is not None
    assert options["Uni-estrutural"] == "Uni-estrutural — SOLO 2"
    assert options["Abstrato expandido"] == "Abstrato expandido — SOLO 5"

    rendered = render_stage_artifact(state, "learning_outcomes")
    assert "| ID | Tipo | Tema ou objeto | Nível | Verbo |" in rendered
    assert "| Taxonomia |" not in rendered
    assert "Uni-estrutural — SOLO 2" in rendered


def test_taxonomy_level_labels_follow_the_selected_taxonomy() -> None:
    assert taxonomy_level_label("SOLO", "Relacional") == "Relacional — SOLO 4"
    assert taxonomy_level_label("Bloom", "Recordar") == "Recordar — Bloom 1"
    assert taxonomy_level_label("Bloom", "Criar") == "Criar — Bloom 6"


def test_learning_outcome_verb_options_follow_the_level_in_the_same_row() -> None:
    state = _completed_state()
    verb_field = next(
        field
        for field in editor_layout("learning_outcomes").tables[0].fields
        if field.key == "action_verb"
    )
    row = {"taxonomy_level": "Relacional"}

    options = editor_taxonomy_verb_options(state, row, verb_field)

    assert options is not None
    assert "analisar" in options
    assert "identificar" not in options

    row["taxonomy_level"] = "Uni-estrutural"
    options = editor_taxonomy_verb_options(state, row, verb_field)
    assert options is not None
    assert "identificar" in options
    assert "analisar" not in options

    bloom_state = {"course": {"taxonomy_type": "Bloom"}}
    row["taxonomy_level"] = "Analisar"
    options = editor_taxonomy_verb_options(bloom_state, row, verb_field)
    assert options is not None
    assert "analisar" in options
    assert "aplicar" not in options

    row["action_verb"] = ""
    assert editor_reference_value(row, verb_field) is None


def test_alignment_editor_omits_redundant_taxonomy_and_numbers_levels() -> None:
    state = _completed_state()
    table = editor_layout("alignment_matrix").tables[0]
    level_field = next(
        field for field in table.fields if field.key == "taxonomy_level"
    )

    assert "Taxonomia" not in [field.label for field in table.fields]
    options = editor_taxonomy_level_options(state, level_field)
    assert options is not None
    assert options["Uni-estrutural"] == "Uni-estrutural — SOLO 2"
    assert options["Abstrato expandido"] == "Abstrato expandido — SOLO 5"

    first_row = state["alignment_matrix"][0]
    expected_level = taxonomy_level_label(
        first_row["taxonomy"], first_row["taxonomy_level"]
    )
    rendered = render_stage_artifact(state, "alignment_matrix")
    assert "| Resultado | Conteúdos | Nível |" in rendered
    assert "| Taxonomia |" not in rendered
    assert expected_level in rendered


def test_new_learning_outcome_row_inherits_the_first_allowed_level() -> None:
    state = _completed_state()
    table = editor_layout("learning_outcomes").tables[0]

    row = new_table_row(table, state)

    assert row["taxonomy_level"] == "Uni-estrutural"
