import json
import sys
import unittest
from copy import deepcopy
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from prism.agents import (
    DEFAULT_MODEL,
    AgentGenerationError,
    AgenticPedagogicalTeam,
    CritiqueResult,
    GenerationResult,
    OpenAIPedagogicalAgent,
    OpenAIPedagogicalCritic,
    _validate_artifact,
    _schema_for,
)
from prism.curriculum import (
    ASSESSMENT_PURPOSES,
    has_single_action_verb,
    taxonomy_level_for_verb,
    taxonomy_verb_allowed,
)
from prism.branding import APP_NAME, config_value
from prism.models import CourseInput, SUPPORTED_RESOURCE_TYPES
from prism.persistence import SQLiteSessionStore
from prism.workflow import (
    STAGE_ORDER,
    apply_manual_edit,
    create_session,
    create_test_agent,
    reopen_stage,
    review_current_stage,
    revision_impact,
    validate_alignment,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.course = CourseInput.create(
            unit_name="Introdução à Programação",
            source_text=(
                "Algoritmos e resolução de problemas. Variáveis, condições e ciclos. "
                "Funções, testes e práticas de programação."
            ),
            audience="Licenciatura",
            duration_hours=24,
        )
        self.agent = create_test_agent()

    def test_workflow_stops_at_each_human_review(self) -> None:
        state = create_session(self.course, agent=self.agent)
        self.assertEqual(state["current_stage"], "curriculum_analysis")
        self.assertEqual(state["status"], "awaiting_review")

        for expected_stage in (
            "learning_outcomes",
            "outcome_taxonomy",
            "assessment_activities",
            "pedagogical_design",
            "teaching_activities",
            "alignment_matrix",
            "resources",
            "final_validation",
        ):
            state = review_current_stage(state, "approve", agent=self.agent)
            self.assertEqual(state["current_stage"], expected_stage)
            self.assertEqual(state["status"], "awaiting_review")

        self.assertTrue(all(row["status"] == "Coerente" for row in state["alignment_matrix"]))
        self.assertEqual(state["resources"]["quality"]["status"], "OK")
        self.assertTrue(state["final_validation"]["passed"])

        state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["status"], "completed")

        audit_count = len(state["audit"])
        repeated = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(repeated["status"], "completed")
        self.assertEqual(len(repeated["audit"]), audit_count)

    def test_workflow_reports_real_generation_phases(self) -> None:
        updates: list[str] = []
        state = create_session(
            self.course,
            agent=self.agent,
            progress_callback=updates.append,
        )

        self.assertIn("Conteúdos e objetivos curriculares", updates[0])
        self.assertEqual(
            updates[-1],
            "A preparar a proposta para revisão do docente…",
        )

        updates.clear()
        review_current_stage(
            state,
            "approve",
            agent=self.agent,
            progress_callback=updates.append,
        )

        self.assertIn("Formulação dos resultados de aprendizagem", updates[0])
        self.assertEqual(
            updates[-1],
            "A preparar a proposta para revisão do docente…",
        )

    def test_feedback_is_recorded_in_the_audit_trail(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state = review_current_stage(
            state,
            "revise",
            feedback="Usar verbos mais observáveis.",
            agent=self.agent,
        )

        learning_outcome_audit = next(
            item
            for item in state["audit"]
            if item["stage"] == "Formulação dos resultados de aprendizagem"
            and item["feedback"] == "Usar verbos mais observáveis."
        )
        self.assertEqual(
            learning_outcome_audit["feedback"], "Usar verbos mais observáveis."
        )

    def test_alignment_feedback_returns_to_selected_component(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(6):
            state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["current_stage"], "alignment_matrix")

        state = review_current_stage(
            state,
            "revise",
            feedback="A avaliação deve exigir evidência mais observável.",
            revision_stage="assessment_activities",
            agent=self.agent,
        )

        self.assertEqual(state["current_stage"], "assessment_activities")
        self.assertEqual(
            state["feedback"]["assessment_activities"],
            "A avaliação deve exigir evidência mais observável.",
        )
        self.assertNotIn("pedagogical_design", state)

    def test_completed_session_can_reopen_a_previous_stage_safely(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in STAGE_ORDER:
            state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["status"], "completed")

        previous_resources = deepcopy(state["resources"])
        previous_active_versions = deepcopy(state["active_versions"])
        impact = revision_impact(state, "learning_outcomes")

        self.assertTrue(impact["was_completed"])
        self.assertIn("resources", impact["affected_stages"])
        self.assertEqual(impact["next_version"], 2)

        updated = reopen_stage(
            state,
            "learning_outcomes",
            "Tornar os resultados mais específicos.",
            agent=self.agent,
        )

        self.assertEqual(state["status"], "completed")
        self.assertEqual(updated["current_stage"], "learning_outcomes")
        self.assertEqual(updated["status"], "awaiting_review")
        self.assertEqual(
            updated["stage_statuses"]["learning_outcomes"],
            "awaiting_review",
        )
        self.assertEqual(updated["stage_statuses"]["resources"], "stale")
        self.assertNotIn("resources", updated)
        self.assertEqual(len(updated["versions"]["learning_outcomes"]), 2)
        self.assertEqual(
            updated["version_dependencies"]["learning_outcomes"][-1],
            {"curriculum_analysis": 1},
        )
        snapshot = updated["revision_snapshots"][-1]
        self.assertEqual(snapshot["previous_status"], "completed")
        self.assertEqual(snapshot["active_versions"], previous_active_versions)
        self.assertEqual(snapshot["artifacts"]["resources"], previous_resources)

    def test_manual_edit_creates_a_version_and_invalidates_only_on_save(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        original = deepcopy(state)
        edited = deepcopy(state["curriculum_analysis"])
        edited["contents"][0]["title"] = "Conteúdo revisto manualmente"

        updated = apply_manual_edit(
            state,
            "curriculum_analysis",
            edited,
            "Corrigir a designação do primeiro conteúdo.",
        )

        self.assertEqual(state, original)
        self.assertEqual(updated["current_stage"], "curriculum_analysis")
        self.assertEqual(updated["status"], "awaiting_review")
        self.assertEqual(len(updated["versions"]["curriculum_analysis"]), 2)
        self.assertEqual(
            updated["curriculum_analysis"]["contents"][0]["title"],
            "Conteúdo revisto manualmente",
        )
        self.assertNotIn("learning_outcomes", updated)
        self.assertEqual(updated["stage_statuses"]["learning_outcomes"], "stale")
        self.assertTrue(
            updated["generation_metadata"]["curriculum_analysis"][-1][
                "manual_edit"
            ]
        )

    def test_invalid_manual_edit_does_not_change_the_session(self) -> None:
        state = create_session(self.course, agent=self.agent)
        original = deepcopy(state)
        edited = deepcopy(state["curriculum_analysis"])
        edited["contents"] = []

        with self.assertRaisesRegex(AgentGenerationError, "conteúdos e objetivos"):
            apply_manual_edit(state, "curriculum_analysis", edited)

        self.assertEqual(state, original)

    def test_session_store_persists_the_state_and_audit(self) -> None:
        state = create_session(self.course, agent=self.agent)
        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored["session_id"], session_id)
        self.assertEqual(restored["course"]["unit_name"], "Introdução à Programação")
        self.assertEqual(len(restored["audit"]), len(state["audit"]))

    def test_session_store_lists_saved_sessions(self) -> None:
        state = create_session(self.course, agent=self.agent)
        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            sessions = store.list_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], session_id)
        self.assertEqual(sessions[0]["unit_name"], "Introdução à Programação")
        self.assertEqual(sessions[0]["ai_provider"], "OpenAI")

    def test_loading_a_legacy_session_adds_the_new_curricular_structure(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state.pop("schema_version", None)
        state.pop("orchestration", None)
        for key in (
            "program_name", "program_type", "academic_year", "semester",
            "cnaef_code", "cnaef_name", "ects_credits", "contact_hours",
            "autonomous_hours", "general_aims", "bibliography",
        ):
            state["course"].pop(key, None)
        state["curriculum_analysis"].pop("contents", None)
        state["curriculum_analysis"].pop("objectives", None)

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], 6)
        self.assertEqual(restored["migrated_from_schema_version"], 1)
        self.assertEqual(restored["ai_provider"], "OpenAI")
        self.assertTrue(restored["curriculum_analysis"]["contents"])
        self.assertTrue(restored["curriculum_analysis"]["objectives"])
        self.assertIn("program_name", restored["course"])
        self.assertIn("stage_statuses", restored)
        self.assertIn("active_versions", restored)
        self.assertIn("revision_snapshots", restored)

    def test_session_id_survives_a_langgraph_transition(self) -> None:
        state = create_session(self.course, agent=self.agent)
        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            state["session_id"] = session_id

            updated = review_current_stage(state, "approve", agent=self.agent)
            self.assertEqual(updated["session_id"], session_id)
            store.save(updated, session_id=updated.get("session_id"))
            sessions = store.list_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], session_id)

    def test_openai_agent_never_falls_back_when_the_key_is_unavailable(self) -> None:
        with patch.dict(environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(AgentGenerationError):
                create_session(self.course, agent=OpenAIPedagogicalAgent())

    def test_selected_provider_is_used_by_the_workflow(self) -> None:
        with patch(
            "prism.workflow.build_pedagogical_team",
            return_value=self.agent,
        ) as team_factory:
            state = create_session(self.course, ai_provider="IAedu")

        self.assertEqual(state["ai_provider"], "IAedu")
        team_factory.assert_called_once_with("IAedu")

    def test_openai_agent_repairs_a_semantically_invalid_resource(self) -> None:
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(6):
            state = review_current_stage(state, "approve", agent=self.agent)

        valid_state = review_current_stage(deepcopy(state), "approve", agent=self.agent)
        valid_artifact = deepcopy(valid_state["resources"])
        valid_artifact.pop("quality", None)
        invalid_artifact = deepcopy(valid_artifact)
        invalid_artifact["practical_activity"]["criteria"][0]["weight"] -= 1

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []
                self.artifacts = [invalid_artifact, valid_artifact]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                artifact = self.artifacts.pop(0)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": artifact}),
                    id=f"response-{len(self.calls)}",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        fake_responses = FakeResponses()
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(responses=fake_responses)
        )
        environment = {
            "OPENAI_API_KEY": "test-key",
            "PRISM_OPENAI_VALIDATION_RETRIES": "1",
        }
        with patch.dict(environ, environment), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIPedagogicalAgent().generate("resources", state)

        self.assertEqual(result.artifact, valid_artifact)
        self.assertEqual(result.metadata["validation_attempts"], 2)
        self.assertEqual(result.metadata["total_tokens"], 60)
        self.assertEqual(len(fake_responses.calls), 2)
        retry_context = json.loads(fake_responses.calls[1]["input"])
        self.assertIn("automatic_validation_feedback", retry_context)
        self.assertIn(
            "totalizar 100%",
            retry_context["automatic_validation_feedback"]["validation_error"],
        )

    def test_openai_agent_completes_visual_metadata_without_retry(self) -> None:
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(6):
            state = review_current_stage(state, "approve", agent=self.agent)

        valid_state = review_current_stage(deepcopy(state), "approve", agent=self.agent)
        incomplete_artifact = deepcopy(valid_state["resources"])
        incomplete_artifact.pop("quality", None)
        for slide_index in (1, 3):
            slide = incomplete_artifact["presentation_outline"][slide_index]
            slide["visual_kind"] = "comparação"
            slide["visual_title"] = ""
            slide["visual_items"] = [""]
            slide["visual_source"] = ""
            slide["alt_text"] = ""

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": incomplete_artifact}),
                    id="response-1",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        fake_responses = FakeResponses()
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(responses=fake_responses)
        )
        environment = {
            "OPENAI_API_KEY": "test-key",
            "PRISM_OPENAI_VALIDATION_RETRIES": "2",
        }
        with patch.dict(environ, environment), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIPedagogicalAgent().generate("resources", state)

        self.assertEqual(len(fake_responses.calls), 1)
        self.assertEqual(result.metadata["validation_attempts"], 1)
        self.assertEqual(len(result.metadata["guardrail_corrections"]), 2)
        for slide_index in (1, 3):
            slide = result.artifact["presentation_outline"][slide_index]
            self.assertEqual(slide["visual_kind"], "comparacao")
            self.assertTrue(slide["visual_title"])
            self.assertTrue(2 <= len(slide["visual_items"]) <= 4)
            self.assertTrue(slide["visual_source"])
            self.assertTrue(slide["alt_text"])
        _validate_artifact("resources", result.artifact, state)

    def test_taxonomy_guardrail_canonicalizes_level_from_approved_verb(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        invalid_artifact = [
            {
                "outcome_id": outcome["id"],
                "taxonomy": "Bloom",
                "level": "Recordar",
                "action_verb": "listar",
            }
            for outcome in state["learning_outcomes"]
        ]

        fake_responses = SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=json.dumps({"artifact": invalid_artifact}),
                id="taxonomy-response",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=20,
                    total_tokens=30,
                ),
            )
        )
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(responses=fake_responses)
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIPedagogicalAgent().generate("outcome_taxonomy", state)

        outcome_by_id = {item["id"]: item for item in state["learning_outcomes"]}
        for classification in result.artifact:
            expected_verb = outcome_by_id[classification["outcome_id"]]["action_verb"]
            self.assertEqual(classification["taxonomy"], "SOLO")
            self.assertEqual(classification["action_verb"], expected_verb)
            self.assertEqual(
                classification["level"],
                taxonomy_level_for_verb("SOLO", expected_verb),
            )
        self.assertEqual(
            len(result.metadata["guardrail_corrections"]),
            len(state["learning_outcomes"]),
        )

    def test_assessment_guardrail_normalizes_primary_outcome_links(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        outcomes = state["learning_outcomes"]
        invalid_artifact = []
        for index, outcome in enumerate(outcomes):
            next_outcome = outcomes[(index + 1) % len(outcomes)]["id"]
            invalid_artifact.append(
                {
                    "id": f"AV{index + 1}",
                    "outcome_id": outcome["id"],
                    "outcome_ids": (
                        [] if index == 0 else [next_outcome, outcome["id"]]
                    ),
                    "work_type": "Trabalho individual",
                    "assessment_purpose": "formativa",
                    "activity": "Resolver uma tarefa aplicada.",
                    "evidence": "Resposta fundamentada.",
                    "criterion": "Cumprimento dos critérios definidos.",
                }
            )

        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(
                responses=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        output_text=json.dumps({"artifact": invalid_artifact}),
                        id="assessment-response",
                        usage=SimpleNamespace(
                            input_tokens=10,
                            output_tokens=20,
                            total_tokens=30,
                        ),
                    )
                )
            )
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIPedagogicalAgent().generate(
                "assessment_activities", state
            )

        for item in result.artifact:
            self.assertTrue(item["outcome_ids"])
            self.assertEqual(item["outcome_id"], item["outcome_ids"][0])
            self.assertEqual(item["assessment_purpose"], "Formativa")
        self.assertTrue(result.metadata["guardrail_corrections"])

    def test_alignment_guardrail_derives_status_from_approved_evidence(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        valid_artifact = validate_alignment(state)["alignment_matrix"]
        invalid_artifact = [
            {
                **row,
                "assessment": "Não",
                "teaching_activity": "Não",
                "status": "Coerente",
                "assessment_ids": [],
                "teaching_activity_ids": [],
            }
            for row in valid_artifact
        ]
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(
                responses=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        output_text=json.dumps({"artifact": invalid_artifact}),
                        id="alignment-response",
                        usage=SimpleNamespace(
                            input_tokens=10,
                            output_tokens=20,
                            total_tokens=30,
                        ),
                    )
                )
            )
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIPedagogicalAgent().generate("alignment_matrix", state)

        self.assertEqual(result.artifact, valid_artifact)
        self.assertEqual(
            len(result.metadata["guardrail_corrections"]),
            len(valid_artifact),
        )

    def test_at_least_one_resource_type_is_required(self) -> None:
        with self.assertRaises(ValueError):
            create_session(self.course, resource_types=[], agent=self.agent)

    def test_all_openai_response_schemas_have_an_object_at_the_root(self) -> None:
        for stage in STAGE_ORDER:
            if stage == "final_validation":
                continue
            schema = _schema_for(stage)
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["required"], ["artifact"])

    def test_coeria_brand_and_legacy_configuration_compatibility(self) -> None:
        self.assertEqual(APP_NAME, "CoerIA")
        with patch.dict(
            environ,
            {
                "PRISM_OPENAI_MODEL": "legacy-model",
                "AGIR_SOLO_OPENAI_MODEL": "intermediate-model",
                "COERIA_OPENAI_MODEL": "new-model",
            },
            clear=False,
        ):
            self.assertEqual(config_value("OPENAI_MODEL"), "new-model")

    def test_default_openai_profile_prioritises_cost(self) -> None:
        cleared_configuration = {
            f"{prefix}_{suffix}": ""
            for prefix in ("COERIA", "AGIR_SOLO", "PRISM")
            for suffix in ("OPENAI_MODEL", "OPENAI_REASONING_EFFORT")
        }
        cleared_configuration.update(
            {
                "COERIA_OPENAI_CRITIC_MODEL": "",
                "AGIR_SOLO_OPENAI_CRITIC_MODEL": "",
                "PRISM_OPENAI_CRITIC_MODEL": "",
            }
        )
        with patch.dict(environ, cleared_configuration, clear=False):
            generator = OpenAIPedagogicalAgent()
            critic = OpenAIPedagogicalCritic()

        self.assertEqual(DEFAULT_MODEL, "gpt-5-nano")
        self.assertEqual(generator.model, "gpt-5-nano")
        self.assertEqual(generator.reasoning_effort, "minimal")
        self.assertEqual(critic.model, "gpt-5-nano")
        self.assertEqual(critic.reasoning_effort, "minimal")
        self.assertNotIn(
            "resources", AgenticPedagogicalTeam.DEFAULT_CRITIC_STAGES
        )

    def test_curricular_relations_are_explicit_and_many_to_many(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(6):
            state = review_current_stage(state, "approve", agent=self.agent)

        self.assertGreaterEqual(len(state["learning_outcomes"]), 4)
        taxonomy_by_outcome = {
            item["outcome_id"]: item for item in state["outcome_taxonomy"]
        }
        self.assertTrue(
            all(
                taxonomy_verb_allowed(
                    taxonomy_by_outcome[item["id"]]["taxonomy"],
                    taxonomy_by_outcome[item["id"]]["level"],
                    item["action_verb"],
                )
                for item in state["learning_outcomes"]
            )
        )
        self.assertTrue(
            any(len(item["outcome_ids"]) > 1 for item in state["assessment_activities"])
        )
        self.assertTrue(
            all(row["content_ids"] for row in state["alignment_matrix"])
        )
        self.assertTrue(
            all(row["assessment_ids"] for row in state["alignment_matrix"])
        )

    def test_bloom_is_exclusive_and_assessments_are_never_mixed(self) -> None:
        course = CourseInput.create(
            "Programação com Bloom",
            self.course.source_text,
            taxonomy_type="Bloom",
        )
        state = create_session(course, agent=self.agent)
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)

        self.assertTrue(
            all(item["taxonomy"] == "Bloom" for item in state["outcome_taxonomy"])
        )
        self.assertTrue(
            all(
                item["assessment_purpose"] in ASSESSMENT_PURPOSES
                for item in state["assessment_activities"]
            )
        )
        self.assertNotIn(
            "Mista",
            {item["assessment_purpose"] for item in state["assessment_activities"]},
        )

    def test_a_session_may_use_only_summative_assessments(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(3):
            state = review_current_stage(state, "approve", agent=self.agent)
        assessments = deepcopy(state["assessment_activities"])
        for item in assessments:
            item["assessment_purpose"] = "Sumativa"
        _validate_artifact("assessment_activities", assessments, state)

    def test_learning_outcome_requires_exactly_one_action_verb(self) -> None:
        self.assertTrue(
            has_single_action_verb(
                "Analisar os dados recolhidos.", "analisar", "SOLO"
            )
        )
        self.assertFalse(
            has_single_action_verb(
                "Analisar e comparar os dados recolhidos.", "analisar", "SOLO"
            )
        )

    def test_agentic_team_revises_once_and_preserves_human_control(self) -> None:
        class FakeGenerator:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def generate(self, stage, state):
                self.calls.append(deepcopy(state))
                return GenerationResult(
                    artifact={"version": len(self.calls)},
                    metadata={"provider": "fake", "model": "fake", "total_tokens": 5},
                )

        class FakeCritic:
            def __init__(self) -> None:
                self.calls = 0

            def review(self, stage, state, artifact):
                self.calls += 1
                passed = self.calls > 1
                return CritiqueResult(
                    passed=passed,
                    findings=[] if passed else [{
                        "severity": "blocking",
                        "criterion": "alinhamento",
                        "message": "Explicitar a evidência.",
                    }],
                    revision_instructions="Explicitar a evidência.",
                    metadata={"role": "crítico pedagógico", "total_tokens": 3},
                )

        generator = FakeGenerator()
        team = AgenticPedagogicalTeam(
            generator,
            critic=FakeCritic(),
            enabled=True,
            max_revisions=1,
            critic_stages=("learning_outcomes",),
        )
        result = team.generate("learning_outcomes", {"course": {}, "feedback": {}})

        self.assertEqual(result.artifact["version"], 2)
        self.assertEqual(len(generator.calls), 2)
        self.assertIn(
            "crítico pedagógico",
            generator.calls[1]["feedback"]["learning_outcomes"].casefold(),
        )
        self.assertTrue(result.metadata["agentic"]["critic_passed"])
        self.assertEqual(result.metadata["agentic"]["automatic_revisions"], 1)


if __name__ == "__main__":
    unittest.main()
