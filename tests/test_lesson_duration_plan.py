"""Temporal scaffolding must not depend on paid model calls."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from prism.agents import AgentGenerationError, OpenAIPedagogicalAgent, _lesson_duration_plan
from prism.curriculum import LESSON_TYPES


def state(hours=75, source=""):
    return {"course": {"contact_hours": hours, "source_text": source},
            "pedagogical_design": {"lessons": []}}


def test_supervisor_75_hours():
    value = state()
    before = deepcopy(value)
    assert _lesson_duration_plan(value) == [180] * 25
    assert value == before


def test_does_not_preserve_single_4500_minute_lesson():
    value = state()
    value["pedagogical_design"]["lessons"] = [{"duration_minutes": 4500}]
    assert _lesson_duration_plan(value) == [180] * 25


def test_preserves_valid_existing_schedule():
    value = state(5)
    value["pedagogical_design"]["lessons"] = [{"duration_minutes": 120}, {"duration_minutes": 180}]
    assert _lesson_duration_plan(value) == [120, 180]


@pytest.mark.parametrize("text", ["10 aulas de 240 minutos", "10 × 240 min", "10 aulas de 4 horas"])
def test_explicit_distribution(text):
    assert _lesson_duration_plan(state(40, text)) == [240] * 10


def test_conflicting_explicit_distribution_is_not_silently_scaled():
    with pytest.raises(AgentGenerationError, match="não corresponde"):
        _lesson_duration_plan(state(75, "10 aulas de 240 minutos"))


def test_fractional_hours_exact_sum():
    plan = _lesson_duration_plan(state(7.25))
    assert sum(plan) == 435
    assert max(plan) <= 180


def test_without_contact_hours():
    assert _lesson_duration_plan(state(0)) == []


def test_generation_preserves_partial_plan_without_repeating_ai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        count = 7 if len(calls) == 1 else 25
        return SimpleNamespace(output_text=json.dumps({"artifact": {"lessons": [
            {"duration_minutes": 180, "session_type": LESSON_TYPES[0],
             "component_ids": [], "notes": f"Conteúdo da aula {i + 1}"}
            for i in range(count)]}}), id="fake", usage=None)
    agent = OpenAIPedagogicalAgent(client_factory=lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = agent.generate("pedagogical_design", state())
    assert len(calls) == 1
    assert sum(item["duration_minutes"] for item in result.artifact["lessons"]) == 4500
    assert len(result.artifact["lessons"]) == 25
    assert result.artifact["lessons"][6]["notes"] == "Conteúdo da aula 7"
    assert result.artifact["lessons"][7]["notes"] == ""
    assert "18 aula" in result.metadata["generation_warnings"][0]


def test_generated_assessment_without_task_remains_editable_with_warning(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    calls = []
    value = state(3)
    value["curriculum_analysis"] = {"contents": [
        {"id": "C1", "title": "Ciclos", "description": "Ciclos contados", "outcome_ids": []}
    ]}
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps({"artifact": {"lessons": [{
            "duration_minutes": 180,
            "session_type": "Avaliação" if len(calls) == 1 else "Teórico-prática",
            "component_ids": [], "notes": "Implementar um ciclo contado para somar valores."
        }]}}), id="fake", usage=None)
    agent = OpenAIPedagogicalAgent(client_factory=lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = agent.generate("pedagogical_design", value)
    assert len(calls) == 1
    assert "sem tarefa TA" in result.metadata["generation_warnings"][0]
    assert json.loads(calls[0]["input"])["suggested_curricular_progression"][0]["content"]["id"] == "C1"
    assert result.artifact["lessons"][0]["component_ids"] == []
    schema = calls[0]["text"]["format"]["schema"]["properties"]["artifact"]["properties"]["lessons"]
    assert schema["minItems"] == schema["maxItems"] == 1
