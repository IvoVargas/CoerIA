"""The study profile must send the tested model and reasoning to the API."""
import json
from types import SimpleNamespace
from prism.agents import OpenAIPedagogicalAgent, OpenAILocalizedAssistanceAgent, OpenAIPedagogicalCritic
from prism.models import CourseInput
from prism.workflow import create_session, create_test_agent


def test_study_profile_request(monkeypatch):
    for prefix in ('COERIA', 'PRISM', 'AGIR_SOLO'):
        for suffix in ('MODEL', 'RESOURCE_MODEL', 'CRITIC_MODEL', 'REASONING_EFFORT'):
            monkeypatch.delenv(f'{prefix}_OPENAI_{suffix}', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-placeholder')
    course = CourseInput.create(unit_name='Programação', source_text='Algoritmos e variáveis. Condições e ciclos. Funções e testes.', audience='Licenciatura', duration_hours=150)
    state = create_session(course, agent=create_test_agent())
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps({'artifact': state['learning_outcomes']}), usage=None, id='unit-test')
    generator = OpenAIPedagogicalAgent(client_factory=lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    generator.generate('learning_outcomes', state)
    assert calls[0]['model'] == 'gpt-5.4-mini'
    assert calls[0]['reasoning'] == {'effort': 'low'}
    assert generator.resource_model == 'gpt-5.4-mini'
    for agent in (OpenAILocalizedAssistanceAgent(), OpenAIPedagogicalCritic()):
        assert agent.model == 'gpt-5.4-mini'
        assert agent.reasoning_effort == 'low'
