from prism.manual_editing import (
    FieldSpec,
    apply_editor_field_value,
    apply_presentation_image_choice,
    assistance_scope_options,
    available_presentation_images,
    editor_field_value,
    editor_reference_options,
    editor_reference_value,
    editor_taxonomy_level_options,
    editor_taxonomy_verb_options,
    editor_layout,
    format_editor_value,
    move_table_row,
    new_table_row,
    parse_editor_value,
    apply_proposal_review_changes,
    proposal_review_changes,
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
            if any(field.kind == "content_id" for field in table.fields):
                assert rows[-1] == {**table.template, "id": "C1"}
            elif any(
                field.kind == "learning_outcome_id" for field in table.fields
            ):
                assert rows[-1] == {**table.template, "id": "RA1"}
            elif any(
                field.kind == "teaching_activity_id" for field in table.fields
            ):
                assert rows[-1] == {**table.template, "id": "AE1"}
            elif any(
                field.kind == "assessment_task_id" for field in table.fields
            ):
                assert rows[-1] == {**table.template, "id": "TA1"}
            else:
                assert rows[-1] == table.template
            rows.pop()


def test_only_lesson_planning_table_is_reorderable() -> None:
    reorderable_stages = {
        stage
        for stage in STAGE_ORDER[:-1]
        if any(table.reorderable for table in editor_layout(stage).tables)
    }
    assert reorderable_stages == {"pedagogical_design"}


def test_lesson_rows_can_move_without_losing_content() -> None:
    rows = [
        {"duration_minutes": 60, "notes": "Primeira aula"},
        {"duration_minutes": 90, "notes": "Segunda aula"},
        {"duration_minutes": 120, "notes": "Terceira aula"},
    ]

    assert move_table_row(rows, 1, -1) is True
    assert [row["notes"] for row in rows] == [
        "Segunda aula",
        "Primeira aula",
        "Terceira aula",
    ]
    assert rows[0]["duration_minutes"] == 90
    assert move_table_row(rows, 0, -1) is False
    assert move_table_row(rows, 2, 1) is False


def test_only_assessment_tasks_expose_three_identifier_types() -> None:
    identifier_fields = {
        "id",
        "outcome_id",
        "outcome_ids",
        "content_ids",
        "content_links",
        "teaching_activity_ids",
        "assessment_ids",
        "component_ids",
    }

    for stage in STAGE_ORDER[:-1]:
        for table in editor_layout(stage).tables:
            visible_identifiers = {
                field.key for field in table.fields if field.key in identifier_fields
            }
            if stage == "assessment_activities":
                assert visible_identifiers == {
                    "id",
                    "teaching_activity_ids",
                    "outcome_ids",
                }
            else:
                assert len(visible_identifiers) <= 2, (
                    stage,
                    table.title,
                    visible_identifiers,
                )


def test_test_question_column_uses_the_questions_label() -> None:
    test_table = next(
        table
        for table in editor_layout("resources").tables
        if table.path == ("test", "questions")
    )

    prompt_field = next(field for field in test_table.fields if field.key == "prompt")
    assert prompt_field.label == "Questões"


def test_ai_assistance_scopes_omit_technical_id_fields() -> None:
    state = _completed_state()

    for stage in STAGE_ORDER[:-1]:
        artifact = active_stage_artifact(state, stage)
        labels = [
            option["label"]
            for option in assistance_scope_options(stage, artifact)
        ]

        assert all("campo ID" not in label for label in labels)


def test_presentation_assistance_omits_internal_visual_fields() -> None:
    state = _completed_state()

    labels = [
        option["label"]
        for option in assistance_scope_options("resources", state["resources"])
    ]

    assert all("Origem visual" not in label for label in labels)
    assert all("Imagem associada" not in label for label in labels)
    assert all("Tipo visual" not in label for label in labels)


def test_presentation_image_choice_derives_visual_provenance() -> None:
    slide = {
        "visual_mode": "diagrama",
        "visual_asset_id": "",
        "visual_prompt": "",
        "visual_source": "Diagrama nativo.",
        "alt_text": "Descrição existente.",
    }
    document = {
        "id": "document-1",
        "origin_type": "document",
        "source_file": "apoio.pdf",
        "source_location": "Página 3",
        "alt_text": "Figura do documento.",
    }

    apply_presentation_image_choice(slide, document)

    assert slide["visual_mode"] == "documento"
    assert slide["visual_asset_id"] == "document-1"
    assert slide["visual_source"] == "Imagem extraída de apoio.pdf, Página 3."
    assert slide["alt_text"] == "Figura do documento."

    apply_presentation_image_choice(slide, None)
    assert slide["visual_mode"] == "diagrama"
    assert slide["visual_asset_id"] == ""
    assert slide["visual_source"].startswith("Diagrama nativo gerado pelo CoerIA")


def test_available_presentation_images_include_all_documents_uploads_and_ai() -> None:
    state = {
        "source_images": [
            {"id": "document-selected", "origin_type": "document"},
            {"id": "document-hidden", "origin_type": "document"},
            {
                "id": "upload-visible",
                "origin_type": "user_uploaded",
                "source_file": "imagem.png",
            },
        ],
        "generated_images": [
            {"id": "ai-generated", "origin_type": "ai_generated"}
        ],
    }

    assert [asset["id"] for asset in available_presentation_images(state)] == [
        "document-selected",
        "document-hidden",
        "upload-visible",
        "ai-generated",
    ]


def test_uploaded_presentation_image_has_teacher_provenance() -> None:
    slide = {
        "visual_mode": "diagrama",
        "visual_asset_id": "",
        "visual_prompt": "",
        "visual_source": "Diagrama nativo.",
        "alt_text": "",
    }
    asset = {
        "id": "upload-visible",
        "origin_type": "user_uploaded",
        "source_file": "imagem.png",
    }

    apply_presentation_image_choice(slide, asset)

    assert slide["visual_mode"] == "documento"
    assert slide["visual_asset_id"] == "upload-visible"
    assert slide["visual_source"] == "Imagem fornecida pelo docente — imagem.png."


def test_proposal_review_preserves_ids_and_applies_only_accepted_cells() -> None:
    artifact = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar algoritmos.",
        }
    ]
    proposed = [
        {
            **artifact[0],
            "id": "RA99",
            "theme": "Algoritmos eficientes",
            "statement": "Analisar algoritmos através de exemplos concretos.",
        }
    ]

    changes = proposal_review_changes(
        "learning_outcomes", artifact, [], proposed
    )

    assert [change["field_key"] for change in changes] == ["theme", "statement"]
    result = apply_proposal_review_changes(
        artifact,
        changes,
        [
            {"key": changes[0]["key"], "accept": False},
            {
                "key": changes[1]["key"],
                "accept": True,
                "value": "Analisar algoritmos com casos reais.",
            },
        ],
    )

    assert result[0]["id"] == "RA1"
    assert result[0]["theme"] == "Algoritmos"
    assert result[0]["statement"] == "Analisar algoritmos com casos reais."


def test_proposal_review_accepts_an_edited_new_row_as_one_decision() -> None:
    artifact: list[dict] = []
    proposed = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar elementos de um algoritmo.",
        }
    ]
    changes = proposal_review_changes(
        "learning_outcomes", artifact, [], proposed
    )
    edited_row = {**proposed[0], "theme": "Estruturas algorítmicas"}

    result = apply_proposal_review_changes(
        artifact,
        changes,
        [{"key": changes[0]["key"], "accept": True, "value": edited_row}],
    )

    assert result == [edited_row]


def test_proposal_review_identifies_a_removed_middle_row_by_stable_id() -> None:
    artifact = [
        {"id": "RA1", "theme": "Algoritmos"},
        {"id": "RA2", "theme": "Estruturas"},
        {"id": "RA3", "theme": "Testes"},
    ]
    proposed = [artifact[0], artifact[2]]

    changes = proposal_review_changes(
        "learning_outcomes", artifact, [], proposed
    )

    assert len(changes) == 1
    assert changes[0]["kind"] == "remove_row"
    assert changes[0]["path"] == [1]
    result = apply_proposal_review_changes(
        artifact,
        changes,
        [{"key": changes[0]["key"], "accept": True}],
    )
    assert [row["id"] for row in result] == ["RA1", "RA3"]


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


def test_curriculum_editor_only_links_curricular_contents() -> None:
    layout = editor_layout("curriculum_analysis")

    assert [field.path for field in layout.fields] == [("summary",)]
    assert [table.title for table in layout.tables] == ["Conteúdos identificados"]
    outcome_field = next(
        field for field in layout.tables[0].fields if field.key == "outcome_ids"
    )
    assert outcome_field.kind == "linked_outcomes"
    description_field = next(
        field for field in layout.tables[0].fields if field.key == "description"
    )
    title_field = next(
        field for field in layout.tables[0].fields if field.key == "title"
    )
    assert title_field.label == "Tema"
    assert description_field.label == "Descrição do tema"
    assert next(
        field for field in layout.tables[0].fields if field.key == "id"
    ).kind == "content_id"


def test_new_curriculum_content_row_uses_the_next_readonly_identifier() -> None:
    table = editor_layout("curriculum_analysis").tables[0]

    row = new_table_row(table, existing_rows=[{"id": "C1"}, {"id": "C3"}])

    assert row["id"] == "C4"


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
    assert "**Etapa 2 de 8**" in rendered
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


def test_new_learning_outcome_row_inherits_the_first_allowed_level() -> None:
    state = _completed_state()
    table = editor_layout("learning_outcomes").tables[0]

    row = new_table_row(table, state)

    assert row["id"] == "RA1"
    assert row["taxonomy_level"] == "Uni-estrutural"


def test_new_learning_outcome_row_uses_the_next_ra_identifier() -> None:
    state = _completed_state()
    table = editor_layout("learning_outcomes").tables[0]
    rows = [{"id": "RA1"}, {"id": "RA3"}]

    row = new_table_row(table, state, rows)

    assert row["id"] == "RA4"
    assert next(field for field in table.fields if field.key == "id").kind == (
        "learning_outcome_id"
    )


def test_new_teaching_and_assessment_rows_use_localized_identifiers() -> None:
    state = _completed_state()
    teaching_table = editor_layout("teaching_activities").tables[0]
    assessment_table = editor_layout("assessment_activities").tables[0]

    teaching_row = new_table_row(
        teaching_table,
        state,
        [{"id": "AE1"}, {"id": "AE3"}],
    )
    assessment_row = new_table_row(
        assessment_table,
        state,
        [{"id": "TA1"}, {"id": "TA3"}],
    )

    assert teaching_row["id"] == "AE4"
    assert assessment_row["id"] == "TA4"
    assert next(
        field for field in teaching_table.fields if field.key == "id"
    ).kind == "teaching_activity_id"
    assert next(
        field for field in assessment_table.fields if field.key == "id"
    ).kind == "assessment_task_id"


def test_assessment_editor_selects_existing_teaching_activities_and_outcomes() -> None:
    state = _completed_state()
    table = editor_layout("assessment_activities").tables[0]
    field = next(
        item for item in table.fields if item.key == "teaching_activity_ids"
    )

    options = editor_reference_options(state, field)

    assert field.kind == "csv"
    assert options is not None
    assert set(options) == {
        item["id"] for item in state["teaching_activities"]
    }
    assert all(
        label.startswith(f"{identifier} — ")
        for identifier, label in options.items()
    )
    outcome_field = next(item for item in table.fields if item.key == "outcome_ids")
    outcome_options = editor_reference_options(state, outcome_field)
    assert outcome_options is not None
    assert set(outcome_options) == {
        item["id"] for item in state["learning_outcomes"]
    }
    new_row = new_table_row(table, state, [])
    assert new_row["teaching_activity_ids"] == []
    assert new_row["outcome_ids"] == []


def test_assessment_presentation_shows_the_direct_results_column() -> None:
    rendered = render_stage_artifact(
        _completed_state(),
        "assessment_activities",
    )

    assert "Atividades de ensino-aprendizagem" in rendered
    assert "| Resultados |" in rendered


def test_lesson_planning_selects_existing_teaching_and_assessment_components() -> None:
    state = _completed_state()
    table = editor_layout("pedagogical_design").tables[0]
    field = next(item for item in table.fields if item.key == "component_ids")

    options = editor_reference_options(state, field)

    assert field.kind == "csv"
    assert options is not None
    assert set(options) == {
        item["id"]
        for stage in ("teaching_activities", "assessment_activities")
        for item in state[stage]
    }
    assert all(
        label.startswith(f"{identifier} — ")
        for identifier, label in options.items()
    )

    rendered = render_stage_artifact(state, "pedagogical_design")
    first_teaching = state["teaching_activities"][0]
    first_assessment = state["assessment_activities"][0]
    assert f"{first_teaching['id']} —" in rendered
    assert first_teaching["activity"][:40] in rendered
    assert f"{first_assessment['id']} —" in rendered
    assert first_assessment["activity"][:40] in rendered
