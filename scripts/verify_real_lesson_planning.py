"""Opt-in paid smoke test; uses synthetic data and never writes session storage."""
import json
from copy import deepcopy
from pathlib import Path

from prism.agents import OpenAIPedagogicalAgent, OpenAILocalizedAssistanceAgent
from prism.models import CourseInput
from prism.workflow import create_session, create_test_agent, review_current_stage, request_ai_assistance


def main():
    course = CourseInput.create(
        unit_name="Teste isolado — Introdução à Programação",
        source_text="Algoritmos e resolução de problemas. Variáveis, condições e ciclos. Funções, testes e práticas de programação.",
        audience="Licenciatura", duration_hours=175,
    )
    fixture_agent = create_test_agent()
    state = create_session(course, agent=fixture_agent)
    for _ in range(4):
        state = review_current_stage(state, "approve", agent=fixture_agent)
    state["course"].update(contact_hours=75, autonomous_hours=100)
    state["pedagogical_design"] = {"lessons": []}
    before = deepcopy(state)
    proposed = request_ai_assistance(
        state, "pedagogical_design", [], "Toda a etapa",
        "Criar o planeamento completo das aulas com base nos conteúdos, atividades e avaliações anteriores.",
    )
    proposal = proposed["ai_proposals"][-1]
    lessons = proposal["after"]["lessons"]
    assert state == before, "Original state was mutated"
    assert sum(item["duration_minutes"] for item in lessons) == 4500
    assert all(0 < item["duration_minutes"] <= 240 for item in lessons)
    assert not proposal["metadata"].get("agentic", {}).get("enabled")
    print(json.dumps({"structural_validation": "passed", "semantic_review_passed": proposal["metadata"].get("agentic", {}).get("critic_passed"), "lessons": len(lessons), "minutes": 4500, "metadata": proposal["metadata"]}, ensure_ascii=False), flush=True)
    # Deliberately incomplete timetable: a localized notes proposal must still work.
    partial = deepcopy(state)
    partial["pedagogical_design"] = {"lessons": [deepcopy(lessons[0])]}
    localized = request_ai_assistance(
        partial, "pedagogical_design", ["lessons", 0, "notes"], "Texto da aula 1",
        "Clarifica o foco curricular desta aula numa frase concreta, sem alterar duração nem componentes.",
        agent=OpenAILocalizedAssistanceAgent(),
    )
    fragment = localized["ai_proposals"][-1]
    assert isinstance(fragment["after"], str) and fragment["after"].strip()
    assert localized["pedagogical_design"] == partial["pedagogical_design"]
    output = Path(".local_validation/real_lesson_planning_manual_review_20261006.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"input": before, "complete_proposal": proposal, "localized_proposal": fragment}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Localized proposal passed; evidence: " + str(output), flush=True)


if __name__ == "__main__":
    main()
