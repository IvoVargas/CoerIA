"""Regressões do ensaio técnico P01, sem chamadas externas à IA."""

from copy import deepcopy

import pytest

from prism.agents import AgentGenerationError, _schema_for, _validate_artifact
from prism.curriculum import ASSESSMENT_WORK_TYPES
from prism.manual_editing import FieldSpec, editor_reference_options
from prism.models import CourseInput
from prism.quality import evaluate_quality
from prism.workflow import create_session, create_test_agent, review_current_stage


@pytest.fixture
def state():
    agent = create_test_agent()
    course = CourseInput.create(
        unit_name="Planeamento do estudo", source_text="Prioridades, técnicas de organização e planeamento semanal do estudo.",
        audience="Outra", duration_hours=120,
    )
    result = create_session(course, agent=agent)
    result["course"]["contact_hours"] = 40
    for _ in range(4):
        result = review_current_stage(result, "approve", agent=agent)
    return result


def checks(state):
    return {item["id"]: item for item in evaluate_quality(state)["checks"]}


def test_modalidade_is_controlled_in_editor_and_schema():
    assert editor_reference_options({}, FieldSpec("work_type", "Modalidade")) == {
        value: value for value in ASSESSMENT_WORK_TYPES
    }
    schema = _schema_for("assessment_activities")
    assert schema["properties"]["artifact"]["items"]["properties"]["work_type"]["enum"] == list(ASSESSMENT_WORK_TYPES)


def test_task_title_is_not_a_valid_modality(state):
    state["assessment_activities"][0]["work_type"] = "Identificação de Prioridades"
    with pytest.raises(AgentGenerationError, match="modalidade"):
        _validate_artifact("assessment_activities", state["assessment_activities"], state)
    result = checks(state)["assessment_work_types"]
    assert result["status"] == "error"
    assert result["target_stage"] == "assessment_activities"
    assert result["target_key"] == "TA1"


def test_exact_total_does_not_hide_ten_hour_lessons(state):
    lesson = deepcopy(state["pedagogical_design"]["lessons"][0])
    state["pedagogical_design"]["lessons"] = [
        {**deepcopy(lesson), "duration_minutes": 600, "component_ids": []}
        for _ in range(4)
    ]
    # Long lessons remain permitted, but never receive a silently green report.
    _validate_artifact("pedagogical_design", state["pedagogical_design"], state)
    result = checks(state)
    assert result["lesson_duration_review"]["status"] == "warning"
    assert result["lesson_duration_review"]["target_key"] == "LESSON:1"
    assert result["lesson_assessment_schedule"]["status"] == "warning"


def test_ten_four_hour_lessons_need_no_duration_warning(state):
    lesson = deepcopy(state["pedagogical_design"]["lessons"][0])
    state["pedagogical_design"]["lessons"] = [
        {**deepcopy(lesson), "duration_minutes": 240, "component_ids": []}
        for _ in range(10)
    ]
    state["pedagogical_design"]["lessons"][-1]["component_ids"] = [
        item["id"] for item in state["assessment_activities"]
    ]
    _validate_artifact("pedagogical_design", state["pedagogical_design"], state)
    result = checks(state)
    assert "lesson_duration_review" not in result
    assert "lesson_assessment_schedule" not in result


def test_wrong_total_is_rejected_without_mutating_the_lesson(state):
    artifact = {"lessons": [
        {"duration_minutes": 60, "session_type": "Teórica", "component_ids": [], "notes": "Prioridades"}
        for _ in range(4)
    ]}
    before = deepcopy(artifact)
    with pytest.raises(AgentGenerationError, match="2400 minutos"):
        _validate_artifact("pedagogical_design", artifact, state)
    assert artifact == before
