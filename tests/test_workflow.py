import json
import sys
import unittest
from copy import deepcopy
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from prism.ai_modes import AI_MODE_OFF, AI_MODE_ON
from prism.agents import (
    DEFAULT_MODEL,
    DEFAULT_RESOURCE_MODEL,
    AgentGenerationError,
    AgenticPedagogicalTeam,
    CritiqueResult,
    GenerationResult,
    OpenAILocalizedAssistanceAgent,
    OpenAIPedagogicalAgent,
    OpenAIPedagogicalCritic,
    _canonicalize_assessment_activities,
    _schema_for,
    _upstream_context,
    _validate_artifact,
)
from prism.curriculum import (
    ASSESSMENT_PURPOSES,
    has_single_action_verb,
    is_learning_outcome_id,
    starts_with_objective_action_verb,
    taxonomy_level_for_verb,
    taxonomy_verb_allowed,
)
from prism.branding import APP_NAME, config_value
from prism.models import (
    CourseInput,
    RESOURCE_PRACTICAL,
    RESOURCE_PRESENTATION,
    RESOURCE_TEST,
    RESOURCE_WORKSHEET,
    SUPPORTED_RESOURCE_TYPES,
)
from prism.persistence import SQLiteSessionStore, migrate_legacy_state
from prism.relationships import derive_alignment_rows
from prism.workflow import (
    SCHEMA_VERSION,
    STAGE_ORDER,
    STAGE_LABELS,
    apply_manual_edit,
    build_final_validation,
    create_session,
    create_test_agent,
    request_ai_assistance,
    reopen_stage,
    review_current_stage,
    revision_impact,
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

    def test_resources_stage_uses_the_generation_title(self) -> None:
        self.assertEqual(
            STAGE_LABELS["resources"],
            "Geração de recursos educativos",
        )

    def test_schema_31_presentation_links_are_migrated_without_regeneration(self) -> None:
        state = create_session(self.course)
        state["schema_version"] = 31
        state["learning_outcomes"] = [
            {"id": "RA1"},
            {"id": "RA2"},
        ]
        state["resources"]["presentation_outline"] = [
            {
                "title": "Resultados de aprendizagem",
                "bullets": ["RA1 — Identificar", "RA2 — Aplicar"],
                "outcome_id": ".",
            },
        ]
        state["resources"]["lesson_presentations"] = [
            {
                "lesson_number": 1,
                "presentation_outline": [
                    {
                        "title": "Avaliação",
                        "bullets": ["Resultados: RA2"],
                        "outcome_id": "",
                    }
                ],
            }
        ]

        migrated = migrate_legacy_state(deepcopy(state))

        general_slide = migrated["resources"]["presentation_outline"][0]
        lesson_slide = migrated["resources"]["lesson_presentations"][0][
            "presentation_outline"
        ][0]
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(general_slide["outcome_ids"], ["RA1", "RA2"])
        self.assertEqual(general_slide["outcome_id"], "")
        self.assertEqual(lesson_slide["outcome_ids"], ["RA2"])
        self.assertEqual(lesson_slide["outcome_id"], "RA2")

    def test_reduced_sources_require_explicit_curriculum_coverage(self) -> None:
        reduction = {
            "applied": True,
            "sources": [
                {"source": "Ficheiro: programa.pdf", "original_chars": 1000, "initial_chunks": 1},
                {"source": "Ficheiro: Mayer.pdf", "original_chars": 8000, "initial_chunks": 3},
            ],
        }
        state = create_session(
            self.course,
            agent=self.agent,
            source_reduction=reduction,
        )
        state = review_current_stage(state, "approve", agent=self.agent)
        coverage = state["curriculum_analysis"]["source_coverage"]
        self.assertEqual(
            {item["source"] for item in coverage},
            {"Ficheiro: programa.pdf", "Ficheiro: Mayer.pdf"},
        )

        invalid = deepcopy(state["curriculum_analysis"])
        invalid["source_coverage"] = invalid["source_coverage"][:1]
        with self.assertRaisesRegex(AgentGenerationError, "cobertura de todas as fontes"):
            _validate_artifact("curriculum_analysis", invalid, state)

    def test_openai_curriculum_prompt_and_schema_preserve_all_reduced_sources(self) -> None:
        reduction = {
            "applied": True,
            "sources": [
                {"source": "Ficheiro: FUC.pdf", "original_chars": 11000, "initial_chunks": 1},
                {"source": "Ficheiro: Mayer.pdf", "original_chars": 128000, "initial_chunks": 2},
                {"source": "Ficheiro: Sweller.pdf", "original_chars": 852000, "initial_chunks": 11},
            ],
        }
        expected_state = create_session(
            self.course,
            agent=self.agent,
            source_reduction=reduction,
        )
        expected_state = review_current_stage(
            expected_state, "approve", agent=self.agent
        )
        artifact = deepcopy(expected_state["curriculum_analysis"])

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": artifact}, ensure_ascii=False),
                    id="response-curriculum",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
                )

        responses = FakeResponses()
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=responses)
        )
        state = {
            "course": self.course.to_dict(),
            "learning_outcomes": expected_state["learning_outcomes"],
            "source_reduction": reduction,
            "feedback": {},
            "resource_types": list(SUPPORTED_RESOURCE_TYPES),
        }
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = agent.generate("curriculum_analysis", state)

        self.assertEqual(result.artifact, artifact)
        call = responses.calls[0]
        schema = call["text"]["format"]["schema"]
        self.assertIn("source_coverage", schema["properties"]["artifact"]["properties"])
        self.assertIn("nenhuma fonte ficou sem representação", call["instructions"])
        request_context = json.loads(call["input"])
        self.assertEqual(
            len(request_context["source_coverage_rules"]["sources"]),
            3,
        )

    def test_learning_outcome_context_uses_optional_teacher_assumptions(self) -> None:
        state = create_session(self.course)
        state["learning_outcome_assumptions"] = [
            "Os estudantes dominam conceitos introdutórios."
        ]

        context = _upstream_context(state, "learning_outcomes")
        curriculum_schema = _schema_for("curriculum_analysis", state)[
            "properties"
        ]["artifact"]

        self.assertEqual(
            context["optional_assumptions_for_learning_outcomes"],
            state["learning_outcome_assumptions"],
        )
        self.assertNotIn("assumptions", curriculum_schema["properties"])

    def test_openai_localized_assistance_uses_the_exact_cell_schema(self) -> None:
        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"proposal": "Enunciado clarificado."}),
                    id="response-fragment",
                    usage=SimpleNamespace(input_tokens=4, output_tokens=3, total_tokens=7),
                )

        responses = FakeResponses()
        agent = OpenAILocalizedAssistanceAgent(
            client_factory=lambda: SimpleNamespace(responses=responses)
        )
        state = {
            "course": self.course.to_dict(),
            "learning_outcomes": [
                {
                    "id": "RA1",
                    "theme": "Algoritmos",
                    "statement": "Analisar algoritmos.",
                    "action_verb": "Analisar",
                    "taxonomy_level": "Relacional",
                    "outcome_type": "Conhecimento teórico",
                }
            ],
            "feedback": {},
            "resource_types": [],
        }
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = agent.propose(
                "learning_outcomes",
                state,
                [0, "statement"],
                "Linha 1 — campo Resultado de aprendizagem",
                "Clarificar o enunciado.",
                "Analisar algoritmos.",
            )

        self.assertEqual(result.artifact, "Enunciado clarificado.")
        call = responses.calls[0]
        proposal_schema = call["text"]["format"]["schema"]["properties"]["proposal"]
        self.assertEqual(proposal_schema, {"type": "string"})
        request_context = json.loads(call["input"])
        self.assertEqual(request_context["scope"]["path"], [0, "statement"])

    def test_workflow_stops_at_each_human_review(self) -> None:
        self.assertEqual(
            STAGE_ORDER[:5],
            (
                "learning_outcomes",
                "curriculum_analysis",
                "teaching_activities",
                "assessment_activities",
                "pedagogical_design",
            ),
        )
        state = create_session(self.course, agent=self.agent)
        self.assertEqual(state["current_stage"], "learning_outcomes")
        self.assertEqual(state["status"], "awaiting_review")

        for expected_stage in (
            "curriculum_analysis",
            "teaching_activities",
            "assessment_activities",
            "pedagogical_design",
            "resources",
            "final_validation",
        ):
            state = review_current_stage(state, "approve", agent=self.agent)
            self.assertEqual(state["current_stage"], expected_stage)
            self.assertEqual(state["status"], "awaiting_review")

        self.assertTrue(
            all(row["status"] == "Coerente" for row in derive_alignment_rows(state))
        )
        self.assertTrue(
            all("assessment_ids" not in item for item in state["teaching_activities"])
        )
        self.assertEqual(state["resources"]["quality"]["status"], "OK")
        self.assertTrue(state["final_validation"]["passed"])

        state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["status"], "completed")

        audit_count = len(state["audit"])
        repeated = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(repeated["status"], "completed")
        self.assertEqual(len(repeated["audit"]), audit_count)

    def test_ai_mode_defaults_to_off_and_remains_aligned_across_the_chain(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _stage in STAGE_ORDER[:-1]:
            state = review_current_stage(state, "approve", agent=self.agent)

        self.assertTrue(
            all(item["ai_mode"] == AI_MODE_OFF for item in state["learning_outcomes"])
        )
        self.assertTrue(
            all(item["ai_mode"] == AI_MODE_OFF for item in state["teaching_activities"])
        )
        self.assertTrue(
            all(item["ai_mode"] == AI_MODE_OFF for item in state["assessment_activities"])
        )
        check = next(
            item
            for item in state["final_validation"]["checks"]
            if item["id"] == "ai_mode_alignment"
        )
        self.assertTrue(check["passed"])

    def test_ai_mode_mismatch_is_blocked_and_identifies_the_activity(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state["learning_outcomes"][0]["ai_mode"] = AI_MODE_ON

        with self.assertRaisesRegex(AgentGenerationError, "mesmo AI-mode"):
            _validate_artifact(
                "teaching_activities",
                state["teaching_activities"],
                state,
            )

    def test_mixed_assessment_modes_are_canonicalized_to_an_empty_value(self) -> None:
        state = {
            "learning_outcomes": [
                {"id": "RA1", "ai_mode": AI_MODE_OFF},
                {"id": "RA2", "ai_mode": AI_MODE_ON},
            ],
            "teaching_activities": [],
        }
        artifact = [
            {
                "id": "TA9",
                "outcome_ids": ["RA1", "RA2"],
                "teaching_activity_ids": [],
                "ai_mode": AI_MODE_ON,
                "assessment_purpose": "Sumativa",
            }
        ]

        canonical, _corrections = _canonicalize_assessment_activities(
            artifact,
            state,
        )

        self.assertEqual(canonical[0]["ai_mode"], "")

    def test_lesson_cannot_mix_components_with_different_ai_modes(self) -> None:
        state = {
            "course": {"contact_hours": 2},
            "learning_outcomes": [
                {"id": "RA1", "ai_mode": AI_MODE_OFF},
                {"id": "RA2", "ai_mode": AI_MODE_ON},
            ],
            "teaching_activities": [
                {"id": "AE1", "outcome_ids": ["RA1"], "ai_mode": AI_MODE_OFF}
            ],
            "assessment_activities": [
                {
                    "id": "TA1",
                    "outcome_ids": ["RA2"],
                    "teaching_activity_ids": [],
                    "ai_mode": AI_MODE_ON,
                }
            ],
        }
        design = {
            "lessons": [
                {
                    "duration_minutes": 120,
                    "session_type": "Teórico-prática",
                    "component_ids": ["AE1", "TA1"],
                    "notes": "",
                }
            ]
        }

        with self.assertRaisesRegex(AgentGenerationError, "modos de IA diferentes"):
            _validate_artifact("pedagogical_design", design, state)

        validation = build_final_validation(
            {**state, "pedagogical_design": design}
        )
        mode_check = next(
            item
            for item in validation["checks"]
            if item["id"] == "ai_mode_alignment"
        )
        self.assertFalse(mode_check["passed"])
        self.assertEqual(mode_check["target_stage"], "pedagogical_design")

    def test_schema_30_migrates_existing_sessions_to_ai_off(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _stage in STAGE_ORDER[:-1]:
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 29
        for stage in (
            "learning_outcomes",
            "teaching_activities",
            "assessment_activities",
        ):
            for row in legacy[stage]:
                row.pop("ai_mode", None)
            for version in legacy["versions"].get(stage, []):
                for row in version:
                    row.pop("ai_mode", None)

        restored = migrate_legacy_state(legacy)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        for stage in (
            "learning_outcomes",
            "teaching_activities",
            "assessment_activities",
        ):
            self.assertTrue(
                all(row["ai_mode"] == AI_MODE_OFF for row in restored[stage])
            )
        self.assertTrue(build_final_validation(restored)["passed"])

    def test_curriculum_contents_are_linked_to_learning_outcomes(self) -> None:
        state = create_session(self.course, agent=self.agent)
        approved_outcome_ids = {item["id"] for item in state["learning_outcomes"]}

        state = review_current_stage(state, "approve", agent=self.agent)

        content_outcome_ids = {
            identifier
            for content in state["curriculum_analysis"]["contents"]
            for identifier in content["outcome_ids"]
        }
        self.assertEqual(content_outcome_ids, approved_outcome_ids)
        self.assertNotIn("objectives", state["curriculum_analysis"])
        self.assertNotIn("summary", state["curriculum_analysis"])
        self.assertNotIn("themes", state["curriculum_analysis"])
        self.assertTrue(
            all(
                item["outcome_ids"]
                for item in state["curriculum_analysis"]["contents"]
            )
        )
        self.assertTrue(
            all(
                not starts_with_objective_action_verb(item["description"])
                for item in state["curriculum_analysis"]["contents"]
            )
        )

    def test_curriculum_validation_rejects_objective_like_descriptions(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        curriculum = deepcopy(state["curriculum_analysis"])
        curriculum["contents"][0]["description"] = (
            "Analisar os conceitos fundamentais da programação."
        )

        with self.assertRaisesRegex(
            AgentGenerationError,
            "não começar por verbos",
        ):
            _validate_artifact("curriculum_analysis", curriculum, state)

        self.assertTrue(
            starts_with_objective_action_verb(
                "Desenvolver conhecimentos sobre estruturas de controlo."
            )
        )
        self.assertFalse(
            starts_with_objective_action_verb(
                "Princípios, tipos e aplicações das estruturas de controlo."
            )
        )

    def test_workflow_reports_real_generation_phases(self) -> None:
        updates: list[str] = []
        state = create_session(
            self.course,
            agent=self.agent,
            progress_callback=updates.append,
        )

        self.assertIn("Formulação dos resultados de aprendizagem", updates[0])
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

        self.assertIn("Conteúdos curriculares", updates[0])
        self.assertEqual(
            updates[-1],
            "A preparar a proposta para revisão do docente…",
        )

    def test_feedback_is_recorded_in_the_audit_trail(self) -> None:
        state = create_session(self.course, agent=self.agent)
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

    def test_resources_feedback_returns_to_selected_component(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["current_stage"], "resources")

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
            {},
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
        self.assertNotIn("objectives", updated["curriculum_analysis"])
        self.assertIn("learning_outcomes", updated)
        self.assertEqual(updated["stage_statuses"]["learning_outcomes"], "approved")
        self.assertNotIn("assessment_activities", updated)
        self.assertTrue(
            updated["generation_metadata"]["curriculum_analysis"][-1][
                "manual_edit"
            ]
        )

    def test_invalid_manual_edit_does_not_change_the_session(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        original = deepcopy(state)
        edited = deepcopy(state["curriculum_analysis"])
        edited["contents"] = []

        with self.assertRaisesRegex(AgentGenerationError, "conteúdos"):
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
        state = review_current_stage(state, "approve", agent=self.agent)
        state.pop("schema_version", None)
        state.pop("orchestration", None)
        for key in (
            "program_name", "program_type", "academic_year", "semester",
            "cnaef_code", "cnaef_name", "isced_f_code", "isced_f_name",
            "ects_credits", "contact_hours", "autonomous_hours", "general_aims",
            "bibliography",
        ):
            state["course"].pop(key, None)
        state["curriculum_analysis"]["summary"] = "Síntese curricular legada."
        state["curriculum_analysis"]["themes"] = [
            item["title"] for item in state["curriculum_analysis"]["contents"]
        ]
        state["curriculum_analysis"].pop("contents", None)
        state["curriculum_analysis"].pop("objectives", None)

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["migrated_from_schema_version"], 1)
        self.assertEqual(restored["ai_provider"], "OpenAI")
        self.assertTrue(restored["curriculum_analysis"]["contents"])
        self.assertNotIn("objectives", restored["curriculum_analysis"])
        self.assertNotIn("summary", restored["curriculum_analysis"])
        self.assertNotIn("themes", restored["curriculum_analysis"])
        self.assertEqual(restored["course"]["general_aims"], "")
        self.assertTrue(
            restored["curriculum_analysis"]["contents"][0]["outcome_ids"]
        )
        self.assertIn("program_name", restored["course"])
        self.assertEqual(restored["course"]["isced_f_code"], "")
        self.assertEqual(restored["course"]["isced_f_name"], "")
        self.assertEqual(restored["course"]["semester"], "1.º semestre")
        self.assertIn("stage_statuses", restored)
        self.assertIn("active_versions", restored)
        self.assertIn("revision_snapshots", restored)

    def test_schema_26_moves_optional_assumptions_to_learning_outcomes(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        assumptions = [
            "Os estudantes possuem conhecimentos introdutórios.",
            "A unidade dispõe de sessões práticas.",
        ]
        state["schema_version"] = 26
        state.pop("learning_outcome_assumptions", None)
        state["curriculum_analysis"]["assumptions"] = deepcopy(assumptions)
        state["versions"]["curriculum_analysis"][-1]["assumptions"] = deepcopy(
            assumptions
        )
        state["revision_snapshots"] = [
            {
                "artifacts": {
                    "curriculum_analysis": {
                        **deepcopy(state["curriculum_analysis"]),
                        "assumptions": deepcopy(assumptions),
                    }
                }
            }
        ]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["learning_outcome_assumptions"], assumptions)
        self.assertNotIn("assumptions", restored["curriculum_analysis"])
        self.assertNotIn(
            "assumptions",
            restored["versions"]["curriculum_analysis"][-1],
        )
        self.assertNotIn(
            "assumptions",
            restored["revision_snapshots"][0]["artifacts"][
                "curriculum_analysis"
            ],
        )

    def test_schema_27_moves_general_aims_to_initial_data_without_losing_history(
        self,
    ) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 27
        state["course"]["general_aims"] = "Formulação anterior dos dados iniciais."
        objective = "Desenvolver competências de programação aplicada."
        state["curriculum_analysis"]["objectives"] = objective
        state["versions"]["curriculum_analysis"][-1]["objectives"] = objective
        state["revision_snapshots"] = [
            {
                "artifacts": {
                    "curriculum_analysis": {
                        **deepcopy(state["curriculum_analysis"]),
                        "objectives": objective,
                    }
                }
            }
        ]
        state["ai_proposals"] = [
            {
                "id": "P1",
                "stage": "curriculum_analysis",
                "status": "pending",
                "before": {
                    **deepcopy(state["curriculum_analysis"]),
                    "objectives": objective,
                },
                "after": {
                    **deepcopy(state["curriculum_analysis"]),
                    "objectives": "Objetivo proposto pela IA.",
                },
            }
        ]
        expected_stage = state["current_stage"]
        expected_status = state["status"]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["course"]["general_aims"], objective)
        self.assertEqual(restored["current_stage"], expected_stage)
        self.assertEqual(restored["status"], expected_status)
        self.assertNotIn("objectives", restored["curriculum_analysis"])
        self.assertNotIn(
            "objectives", restored["versions"]["curriculum_analysis"][-1]
        )
        self.assertNotIn(
            "objectives",
            restored["revision_snapshots"][0]["artifacts"][
                "curriculum_analysis"
            ],
        )
        self.assertNotIn("objectives", restored["ai_proposals"][0]["before"])
        self.assertNotIn("objectives", restored["ai_proposals"][0]["after"])

    def test_schema_28_removes_redundant_curriculum_fields_from_session_history(
        self,
    ) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 28
        titles = [item["title"] for item in state["curriculum_analysis"]["contents"]]

        def add_redundant_fields(artifact: dict) -> dict:
            artifact["summary"] = "Síntese curricular redundante."
            artifact["themes"] = deepcopy(titles)
            return artifact

        add_redundant_fields(state["curriculum_analysis"])
        add_redundant_fields(state["versions"]["curriculum_analysis"][-1])
        state["revision_snapshots"] = [
            {
                "artifacts": {
                    "curriculum_analysis": add_redundant_fields(
                        deepcopy(state["curriculum_analysis"])
                    )
                }
            }
        ]
        state["ai_proposals"] = [
            {
                "id": "P1",
                "stage": "curriculum_analysis",
                "scope_path": ["summary"],
                "status": "pending",
                "before": "Síntese atual.",
                "after": "Síntese proposta.",
            },
            {
                "id": "P2",
                "stage": "curriculum_analysis",
                "scope_path": [],
                "status": "pending",
                "before": add_redundant_fields(
                    deepcopy(state["curriculum_analysis"])
                ),
                "after": add_redundant_fields(
                    deepcopy(state["curriculum_analysis"])
                ),
            },
        ]
        expected_contents = deepcopy(state["curriculum_analysis"]["contents"])
        expected_stage = state["current_stage"]
        expected_status = state["status"]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], expected_stage)
        self.assertEqual(restored["status"], expected_status)
        self.assertEqual(restored["curriculum_analysis"]["contents"], expected_contents)
        for artifact in (
            restored["curriculum_analysis"],
            restored["versions"]["curriculum_analysis"][-1],
            restored["revision_snapshots"][0]["artifacts"]["curriculum_analysis"],
            restored["ai_proposals"][1]["before"],
            restored["ai_proposals"][1]["after"],
        ):
            self.assertNotIn("summary", artifact)
            self.assertNotIn("themes", artifact)
        self.assertEqual(restored["ai_proposals"][0]["status"], "superseded")
        self.assertEqual(
            restored["ai_proposals"][0]["decision"],
            "invalidada_por_migracao_curricular",
        )

    def test_schema_16_session_is_migrated_to_biggs_stage_dependencies(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 16
        state["teaching_activities"][0]["assessment_ids"] = ["AV1"]
        state["versions"]["teaching_activities"][-1][0]["assessment_ids"] = ["AV1"]
        state["version_dependencies"]["teaching_activities"][-1][
            "assessment_activities"
        ] = 1

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertNotIn("assessment_ids", restored["teaching_activities"][0])
        self.assertNotIn(
            "assessment_ids",
            restored["versions"]["teaching_activities"][-1][0],
        )
        self.assertNotIn(
            "assessment_activities",
            restored["version_dependencies"]["teaching_activities"][-1],
        )

    def test_schema_17_design_sequence_becomes_lesson_planning(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["current_stage"] != "pedagogical_design":
            state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 17
        legacy_design = {
            "strategy": "Progressão dos conceitos para a aplicação.",
            "sequence": [
                {
                    "outcome_id": outcome["id"],
                    "focus": outcome["statement"],
                    "assessment": next(
                        item["activity"]
                        for item in state["assessment_activities"]
                        if outcome["id"] in item["outcome_ids"]
                    ),
                }
                for outcome in state["learning_outcomes"]
            ],
        }
        state["pedagogical_design"] = deepcopy(legacy_design)
        state["versions"]["pedagogical_design"] = [deepcopy(legacy_design)]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        expected_components = {
            item["id"]
            for stage in ("teaching_activities", "assessment_activities")
            for item in restored[stage]
        }
        planned_components = {
            identifier
            for lesson in restored["pedagogical_design"]["lessons"]
            for identifier in lesson["component_ids"]
        }
        self.assertEqual(planned_components, expected_components)
        self.assertTrue(
            all(
                item["notes"].strip()
                for item in restored["pedagogical_design"]["lessons"]
            )
        )
        self.assertIn(
            "lessons",
            restored["versions"]["pedagogical_design"][-1],
        )

    def test_schema_17_sequential_session_before_teaching_is_repositioned(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["current_stage"] != "pedagogical_design":
            state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 17
        state["teaching_activities"] = []
        state["versions"]["teaching_activities"] = []
        state["active_versions"].pop("teaching_activities", None)

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["current_stage"], "curriculum_analysis")
        self.assertEqual(restored["status"], "awaiting_review")
        self.assertEqual(
            restored["stage_statuses"]["teaching_activities"], "stale"
        )
        self.assertNotIn("assessment_activities", restored["active_versions"])
        self.assertNotIn("pedagogical_design", restored["active_versions"])
        self.assertTrue(restored["versions"]["assessment_activities"])
        self.assertTrue(restored["versions"]["pedagogical_design"])

    def test_schema_19_localizes_activity_ids_and_removes_legacy_alignment(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["current_stage"] != "resources":
            state = review_current_stage(state, "approve", agent=self.agent)
        state["schema_version"] = 19

        def use_legacy_ids(rows, prefix):
            mapping = {}
            for index, row in enumerate(rows, start=1):
                old = row["id"]
                row["id"] = f"{prefix}{index}"
                mapping[old] = row["id"]
            return mapping

        use_legacy_ids(state["assessment_activities"], "AT")
        use_legacy_ids(state["teaching_activities"], "TLA")
        use_legacy_ids(state["versions"]["assessment_activities"][-1], "AT")
        use_legacy_ids(state["versions"]["teaching_activities"][-1], "TLA")
        legacy_matrix = derive_alignment_rows(state)
        state["alignment_matrix"] = deepcopy(legacy_matrix)
        state["versions"]["alignment_matrix"] = [deepcopy(legacy_matrix)]
        state["revision_snapshots"] = [
            {
                "artifacts": {
                    "assessment_activities": deepcopy(state["assessment_activities"]),
                    "teaching_activities": deepcopy(state["teaching_activities"]),
                    "alignment_matrix": deepcopy(legacy_matrix),
                }
            }
        ]
        state["ai_proposals"] = [
            {
                "stage": "teaching_activities",
                "before": deepcopy(state["teaching_activities"]),
                "after": deepcopy(state["teaching_activities"]),
            },
            {
                "stage": "alignment_matrix",
                "before": deepcopy(legacy_matrix),
                "after": deepcopy(legacy_matrix),
            },
        ]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(state)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["migrated_from_schema_version"], 19)
        self.assertTrue(
            all(
                item["id"] == f"AE{index}"
                for index, item in enumerate(
                    restored["teaching_activities"], start=1
                )
            )
        )
        self.assertTrue(
            all(
                item["id"] == f"TA{index}"
                for index, item in enumerate(
                    restored["assessment_activities"], start=1
                )
            )
        )
        self.assertNotIn("alignment_matrix", restored)
        self.assertNotIn("alignment_matrix", restored["versions"])
        self.assertNotIn(
            "alignment_matrix", restored["revision_snapshots"][0]["artifacts"]
        )
        teaching_proposal = restored["ai_proposals"][0]
        self.assertTrue(
            all(
                item["id"].startswith("AE")
                for item in teaching_proposal["before"] + teaching_proposal["after"]
            )
        )
        self.assertEqual(len(restored["ai_proposals"]), 1)

    def test_schema_20_sequential_session_at_removed_alignment_stage_reopens_sequence(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 20
        legacy["current_stage"] = "alignment_matrix"
        legacy["status"] = "awaiting_review"
        legacy_matrix = derive_alignment_rows(legacy)
        legacy["alignment_matrix"] = deepcopy(legacy_matrix)
        legacy["versions"]["alignment_matrix"] = [deepcopy(legacy_matrix)]
        legacy["active_versions"]["alignment_matrix"] = 1
        legacy["stage_statuses"]["alignment_matrix"] = "draft"

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], "pedagogical_design")
        self.assertEqual(restored["status"], "awaiting_review")
        self.assertEqual(
            restored["stage_statuses"]["pedagogical_design"], "awaiting_review"
        )
        self.assertNotIn("alignment_matrix", restored)
        self.assertNotIn("alignment_matrix", restored["versions"])
        self.assertIn("verificadas automaticamente", restored["review"]["message"])

    def test_schema_20_manual_session_at_removed_alignment_stage_moves_to_resources(self) -> None:
        legacy = create_session(self.course)
        legacy["schema_version"] = 20
        legacy["current_stage"] = "alignment_matrix"
        legacy["status"] = "drafting"
        legacy["alignment_matrix"] = []
        legacy["versions"]["alignment_matrix"] = [[]]
        legacy["active_versions"]["alignment_matrix"] = 1
        legacy["stage_statuses"]["alignment_matrix"] = "draft"

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], "resources")
        self.assertEqual(restored["status"], "drafting")
        self.assertEqual(restored["stage_statuses"]["resources"], "draft")
        self.assertNotIn("alignment_matrix", restored)

    def test_schema_21_infers_assessment_links_to_teaching_activities(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 21
        for index, item in enumerate(legacy["assessment_activities"]):
            item.pop("teaching_activity_ids", None)
            item["outcome_id"] = legacy["learning_outcomes"][index]["id"]
            item["outcome_ids"] = [item["outcome_id"]]
        for version in legacy["versions"]["assessment_activities"]:
            for index, item in enumerate(version):
                item.pop("teaching_activity_ids", None)
                item["outcome_id"] = legacy["learning_outcomes"][index]["id"]
                item["outcome_ids"] = [item["outcome_id"]]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        teaching_ids = {item["id"] for item in restored["teaching_activities"]}
        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertTrue(
            all(
                item["teaching_activity_ids"]
                and set(item["teaching_activity_ids"]) <= teaching_ids
                for item in restored["assessment_activities"]
            )
        )
        self.assertTrue(
            all(
                "outcome_id" not in item and item["outcome_ids"]
                for item in restored["assessment_activities"]
            )
        )
        self.assertTrue(
            all(
                item["teaching_activity_ids"]
                for version in restored["versions"]["assessment_activities"]
                for item in version
            )
        )

    def test_schema_22_restores_direct_assessment_outcome_links(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 22
        for index, item in enumerate(legacy["assessment_activities"]):
            item["outcome_id"] = legacy["learning_outcomes"][index]["id"]
            item["outcome_ids"] = [item["outcome_id"]]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertTrue(
            all(item["teaching_activity_ids"] for item in restored["assessment_activities"])
        )
        self.assertTrue(
            all(
                "outcome_id" not in item and item["outcome_ids"]
                for item in restored["assessment_activities"]
            )
        )

    def test_schema_23_sequence_moves_direct_links_to_tasks_and_becomes_lessons(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["status"] != "completed":
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 23
        assessment_by_outcome = {
            outcome["id"]: next(
                item
                for item in legacy["assessment_activities"]
                if outcome["id"] in item["outcome_ids"]
            )
            for outcome in legacy["learning_outcomes"]
        }
        for item in legacy["assessment_activities"]:
            item.pop("outcome_ids", None)
        legacy_design = {
            "strategy": "Progressão alinhada.",
            "sequence": [
                {
                    "outcome_id": outcome["id"],
                    "focus": outcome["statement"],
                    "assessment": assessment_by_outcome[outcome["id"]]["activity"],
                }
                for outcome in legacy["learning_outcomes"]
            ],
        }
        legacy["pedagogical_design"] = deepcopy(legacy_design)
        legacy["versions"]["pedagogical_design"] = [deepcopy(legacy_design)]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertTrue(
            all(
                item["outcome_ids"]
                for item in restored["assessment_activities"]
            )
        )
        self.assertTrue(restored["pedagogical_design"]["lessons"])
        self.assertNotIn("sequence", restored["pedagogical_design"])
        self.assertTrue(
            all(row["status"] == "Coerente" for row in derive_alignment_rows(restored))
        )
        self.assertTrue(restored["final_validation"]["passed"])

    def test_schema_24_direct_sequence_links_move_to_tasks(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["status"] != "completed":
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 24
        old_sequence = []
        for outcome in legacy["learning_outcomes"]:
            teaching = next(
                item
                for item in legacy["teaching_activities"]
                if outcome["id"] in item["outcome_ids"]
            )
            assessment = next(
                item
                for item in legacy["assessment_activities"]
                if outcome["id"] in item["outcome_ids"]
            )
            old_sequence.append(
                {
                    "outcome_id": outcome["id"],
                    "focus": outcome["statement"],
                    "teaching_activity": teaching["activity"],
                    "assessment_ids": [assessment["id"]],
                }
            )
        for item in legacy["assessment_activities"]:
            item.pop("outcome_ids", None)
        legacy_design = {
            "strategy": "Progressão guiada por resultados.",
            "sequence": old_sequence,
        }
        legacy["pedagogical_design"] = deepcopy(legacy_design)
        legacy["versions"]["pedagogical_design"] = [deepcopy(legacy_design)]

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertTrue(
            all(row["status"] == "Coerente" for row in derive_alignment_rows(restored))
        )
        self.assertTrue(restored["pedagogical_design"]["lessons"])
        self.assertNotIn("sequence", restored["pedagogical_design"])
        self.assertTrue(restored["final_validation"]["passed"])

    def test_schema_20_completed_session_rebuilds_final_validation_without_matrix(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["status"] != "completed":
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 20
        legacy_matrix = derive_alignment_rows(legacy)
        legacy["alignment_matrix"] = deepcopy(legacy_matrix)
        legacy["versions"]["alignment_matrix"] = [deepcopy(legacy_matrix)]
        legacy["final_validation"]["checks"].append(
            {
                "id": "stage_alignment_matrix",
                "label": "Matriz de alinhamento",
                "passed": True,
                "detail": "Controlo legado.",
            }
        )

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        check_ids = {item["id"] for item in restored["final_validation"]["checks"]}
        self.assertEqual(restored["status"], "completed")
        self.assertNotIn("alignment_matrix", restored)
        self.assertNotIn("stage_alignment_matrix", check_ids)
        self.assertIn("alignment", check_ids)

    def test_legacy_session_at_the_old_first_stage_moves_to_outcomes(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 11
        legacy.pop("learning_outcomes", None)
        legacy["versions"].pop("learning_outcomes", None)
        legacy["generation_metadata"].pop("learning_outcomes", None)
        legacy["active_versions"].pop("learning_outcomes", None)
        legacy["current_stage"] = "curriculum_analysis"
        legacy["status"] = "awaiting_review"
        legacy["curriculum_analysis"]["objectives"] = [
            {"id": "OG1", "statement": "Desenvolver conhecimentos fundamentais."}
        ]
        for item in legacy["curriculum_analysis"]["contents"]:
            item.pop("outcome_ids", None)

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], "learning_outcomes")
        self.assertEqual(restored["status"], "drafting")
        self.assertEqual(
            restored["course"]["general_aims"],
            "Desenvolver conhecimentos fundamentais.",
        )
        self.assertNotIn("objectives", restored["curriculum_analysis"])
        self.assertTrue(restored["learning_outcomes"])
        self.assertEqual(
            restored["stage_statuses"]["curriculum_analysis"], "needs_review"
        )
        self.assertNotIn("curriculum_analysis", restored["active_versions"])

    def test_legacy_session_at_the_old_second_stage_keeps_outcomes_current(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 11
        legacy["current_stage"] = "learning_outcomes"
        legacy["status"] = "awaiting_review"
        legacy["review"] = {
            "stage": "learning_outcomes",
            "label": "Formulação dos resultados de aprendizagem",
            "message": "A aguardar validação do docente.",
        }
        legacy["stage_statuses"]["curriculum_analysis"] = "approved"
        legacy["stage_statuses"]["learning_outcomes"] = "awaiting_review"
        legacy["curriculum_analysis"]["objectives"] = [
            {
                "id": "OG1",
                "statement": "Desenvolver conhecimentos fundamentais.",
                "outcome_ids": [item["id"] for item in legacy["learning_outcomes"]],
            }
        ]
        for item in legacy["curriculum_analysis"]["contents"]:
            item.pop("outcome_ids", None)

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            restored["course"]["general_aims"],
            "Desenvolver conhecimentos fundamentais.",
        )
        self.assertNotIn("objectives", restored["curriculum_analysis"])
        self.assertEqual(restored["current_stage"], "learning_outcomes")
        self.assertEqual(restored["status"], "drafting")
        self.assertEqual(
            restored["stage_statuses"]["learning_outcomes"], "draft"
        )
        self.assertEqual(
            restored["stage_statuses"]["curriculum_analysis"], "needs_review"
        )
        self.assertNotIn("curriculum_analysis", restored["active_versions"])
        self.assertTrue(restored["versions"]["curriculum_analysis"])

        regenerated = review_current_stage(restored, "approve", agent=self.agent)
        self.assertEqual(regenerated["current_stage"], "curriculum_analysis")
        self.assertEqual(regenerated["status"], "drafting")
        expected_outcomes = {
            item["id"] for item in regenerated["learning_outcomes"]
        }
        self.assertEqual(
            {
                outcome_id
                for item in regenerated["curriculum_analysis"]["contents"]
                for outcome_id in item["outcome_ids"]
            },
            expected_outcomes,
        )
        self.assertNotIn("objectives", regenerated["curriculum_analysis"])

    def test_schema_12_session_moves_objective_list_to_initial_data(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["current_stage"] != "resources":
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 12
        legacy_objectives = [
            {
                "id": "OG1",
                "statement": "Compreender os fundamentos da programação.",
                "outcome_ids": ["RA1", "RA2"],
            },
            {
                "id": "OG2",
                "statement": "Aplicar os conhecimentos em problemas concretos.",
                "outcome_ids": ["RA3", "RA4"],
            },
        ]
        legacy["curriculum_analysis"]["objectives"] = deepcopy(legacy_objectives)
        legacy["versions"]["curriculum_analysis"][-1]["objectives"] = deepcopy(
            legacy_objectives
        )
        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        expected_text = (
            "Compreender os fundamentos da programação.\n"
            "Aplicar os conhecimentos em problemas concretos."
        )
        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], "resources")
        self.assertEqual(restored["status"], "drafting")
        self.assertEqual(restored["course"]["general_aims"], expected_text)
        self.assertNotIn("objectives", restored["curriculum_analysis"])
        self.assertNotIn(
            "objectives", restored["versions"]["curriculum_analysis"][-1]
        )
        self.assertNotIn("alignment_matrix", restored)

    def test_schema_13_session_at_removed_taxonomy_stage_reopens_outcomes(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 13
        classifications = [
            {
                "outcome_id": item["id"],
                "taxonomy": "SOLO",
                "level": item["taxonomy_level"],
                "action_verb": item["action_verb"],
            }
            for item in legacy["learning_outcomes"]
        ]
        for item in legacy["learning_outcomes"]:
            item.pop("taxonomy_level")
        for version in legacy["versions"]["learning_outcomes"]:
            for item in version:
                item.pop("taxonomy_level", None)
        legacy["outcome_taxonomy"] = classifications
        legacy["versions"]["outcome_taxonomy"] = [deepcopy(classifications)]
        legacy["active_versions"]["outcome_taxonomy"] = 1
        legacy["stage_statuses"]["learning_outcomes"] = "approved"
        legacy["stage_statuses"]["curriculum_analysis"] = "approved"
        legacy["stage_statuses"]["outcome_taxonomy"] = "awaiting_review"
        legacy["current_stage"] = "outcome_taxonomy"
        legacy["status"] = "awaiting_review"

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["schema_version"], SCHEMA_VERSION)
        self.assertEqual(restored["current_stage"], "learning_outcomes")
        self.assertEqual(
            restored["stage_statuses"]["learning_outcomes"], "draft"
        )
        self.assertEqual(
            restored["stage_statuses"]["curriculum_analysis"], "needs_review"
        )
        self.assertNotIn("curriculum_analysis", restored["active_versions"])
        self.assertNotIn("outcome_taxonomy", restored)
        self.assertNotIn("outcome_taxonomy", restored["stage_statuses"])
        self.assertTrue(
            all(item.get("taxonomy_level") for item in restored["learning_outcomes"])
        )

        continued = review_current_stage(restored, "approve", agent=self.agent)
        self.assertEqual(continued["current_stage"], "curriculum_analysis")

    def test_schema_13_session_after_removed_stage_keeps_its_current_stage(self) -> None:
        state = create_session(self.course, agent=self.agent)
        while state["current_stage"] != "resources":
            state = review_current_stage(state, "approve", agent=self.agent)
        legacy = deepcopy(state)
        legacy["schema_version"] = 13
        classifications = [
            {
                "outcome_id": item["id"],
                "taxonomy": "SOLO",
                "level": item["taxonomy_level"],
                "action_verb": item["action_verb"],
            }
            for item in legacy["learning_outcomes"]
        ]
        for item in legacy["learning_outcomes"]:
            item.pop("taxonomy_level")
        legacy["outcome_taxonomy"] = classifications
        legacy["versions"]["outcome_taxonomy"] = [deepcopy(classifications)]
        legacy["active_versions"]["outcome_taxonomy"] = 1
        legacy["stage_statuses"]["outcome_taxonomy"] = "approved"

        with TemporaryDirectory() as temporary_directory:
            store = SQLiteSessionStore(Path(temporary_directory) / "prism.db")
            session_id = store.save(legacy)
            restored = store.load(session_id)

        self.assertEqual(restored["current_stage"], "resources")
        self.assertEqual(restored["status"], "drafting")
        self.assertNotIn("outcome_taxonomy", restored)
        self.assertNotIn("outcome_taxonomy", restored["active_versions"])
        self.assertTrue(
            all(item.get("taxonomy_level") for item in restored["learning_outcomes"])
        )

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
        team_factory.assert_not_called()


    def test_learning_outcome_retry_is_explicit_and_has_safe_final_fallback(self) -> None:
        state = create_session(self.course, agent=self.agent)
        valid_artifact = deepcopy(
            self.agent.generate("learning_outcomes", state).artifact
        )
        invalid_artifact = deepcopy(valid_artifact)
        first = invalid_artifact[0]
        second = invalid_artifact[1]
        first["statement"] = (
            f"{first['action_verb'].capitalize()} conceitos essenciais e explicar "
            "como aplicá-los."
        )
        second["statement"] = (
            f"{second['action_verb'].capitalize()} e comparar estruturas fundamentais."
        )

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": invalid_artifact}),
                    id=f"response-{len(self.calls)}",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        fake_responses = FakeResponses()
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=fake_responses)
        )
        with patch.dict(
            environ,
            {
                "OPENAI_API_KEY": "test-key",
                "COERIA_OPENAI_VALIDATION_RETRIES": "2",
            },
            clear=False,
        ):
            result = agent.generate("learning_outcomes", state)

        self.assertEqual(len(fake_responses.calls), 3)
        self.assertIn(
            "REPARAÇÃO OBRIGATÓRIA DA TENTATIVA ANTERIOR",
            fake_responses.calls[1]["instructions"],
        )
        self.assertIn(
            "não pode ser repetida",
            fake_responses.calls[2]["instructions"],
        )
        self.assertEqual(result.metadata["validation_attempts"], 3)
        self.assertEqual(len(result.metadata["guardrail_corrections"]), 2)
        for outcome in result.artifact:
            self.assertTrue(
                has_single_action_verb(
                    outcome["statement"],
                    outcome["action_verb"],
                    state["course"]["taxonomy_type"],
                )
            )
        _validate_artifact("learning_outcomes", result.artifact, state)

    def test_openai_agent_repairs_a_semantically_invalid_resource(self) -> None:
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        valid_state = review_current_stage(deepcopy(state), "approve", agent=self.agent)
        valid_artifact = deepcopy(valid_state["resources"])
        valid_artifact.pop("quality", None)
        invalid_artifact = deepcopy(valid_artifact)
        invalid_artifact["practical_activity"]["duration_minutes"] = 0

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
            "duração deve ser positiva",
            retry_context["automatic_validation_feedback"]["validation_error"],
        )

    def test_openai_agent_completes_visual_metadata_without_retry(self) -> None:
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        valid_state = review_current_stage(deepcopy(state), "approve", agent=self.agent)
        incomplete_artifact = deepcopy(valid_state["resources"])
        incomplete_artifact.pop("quality", None)
        state["source_images"] = [
            {
                "id": "document-private-test",
                "origin_type": "document",
                "source_file": "apoio.pdf",
                "source_location": "Página 3",
                "filename": "figura.png",
                "media_type": "image/png",
                "candidate_kind": "embedded",
                "width_px": 800,
                "height_px": 450,
                "thumbnail_base64": "PRIVATE_THUMBNAIL_BYTES",
                "data_base64": "PRIVATE_ORIGINAL_BYTES",
            }
        ]
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
        request_input = fake_responses.calls[0]["input"]
        self.assertIsInstance(request_input, str)
        self.assertNotIn("PRIVATE_THUMBNAIL_BYTES", request_input)
        self.assertNotIn("PRIVATE_ORIGINAL_BYTES", request_input)
        self.assertNotIn("input_image", request_input)
        request_context = json.loads(request_input)
        self.assertEqual(
            request_context["source_image_catalogue"][0]["id"],
            "document-private-test",
        )
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

    def test_openai_agent_requests_only_the_current_resource_payload(self) -> None:
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        resource_fields = {
            RESOURCE_PRESENTATION: "presentation_outline",
            RESOURCE_WORKSHEET: "lesson_worksheet",
            RESOURCE_TEST: "test",
            RESOURCE_PRACTICAL: "practical_activity",
        }
        for resource_type, resource_field in resource_fields.items():
            with self.subTest(resource_type=resource_type):
                scoped_state = deepcopy(state)
                scoped_state["resource_types"] = [resource_type]
                scoped_state["resource_generation_scope"] = resource_type
                expected = self.agent.generate("resources", scoped_state).artifact
                resource_payload = deepcopy(expected[resource_field])

                class FakeResponses:
                    def __init__(self):
                        self.calls = []

                    def create(self, **kwargs):
                        self.calls.append(kwargs)
                        return SimpleNamespace(
                            output_text=json.dumps({"artifact": resource_payload}),
                            id="response-resource",
                            usage=SimpleNamespace(
                                input_tokens=10,
                                output_tokens=20,
                                total_tokens=30,
                            ),
                        )

                fake_responses = FakeResponses()
                agent = OpenAIPedagogicalAgent(
                    model="gpt-5-nano",
                    resource_model="gpt-4o-mini",
                    client_factory=lambda: SimpleNamespace(
                        responses=fake_responses
                    )
                )
                with patch.dict(
                    environ,
                    {
                        "OPENAI_API_KEY": "test-key",
                        "COERIA_OPENAI_VALIDATION_RETRIES": "0",
                    },
                    clear=False,
                ):
                    result = agent.generate("resources", scoped_state)

                schema = fake_responses.calls[0]["text"]["format"]["schema"]
                request_context = json.loads(fake_responses.calls[0]["input"])
                self.assertEqual(fake_responses.calls[0]["model"], "gpt-4o-mini")
                self.assertNotIn("reasoning", fake_responses.calls[0])
                self.assertEqual(result.metadata["model"], "gpt-4o-mini")
                self.assertNotIn("selected_types", json.dumps(schema))
                self.assertEqual(
                    request_context["requested_resource_types"], [resource_type]
                )
                self.assertIn(
                    "Não devolvas selected_types",
                    fake_responses.calls[0]["instructions"],
                )
                self.assertEqual(result.artifact["selected_types"], [resource_type])
                self.assertEqual(result.artifact[resource_field], resource_payload)
                self.assertEqual(
                    result.metadata["resource_generation_scope"], resource_type
                )
                _validate_artifact("resources", result.artifact, scoped_state)

    def test_scoped_resource_selection_is_not_controlled_by_the_model(self) -> None:
        state = create_session(
            self.course,
            resource_types=[RESOURCE_TEST],
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        state["resource_generation_scope"] = RESOURCE_TEST
        legacy_response = self.agent.generate("resources", state).artifact
        legacy_response["selected_types"] = list(SUPPORTED_RESOURCE_TYPES)

        fake_responses = SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=json.dumps({"artifact": legacy_response}),
                id="response-legacy-resource",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=20,
                    total_tokens=30,
                ),
            )
        )
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=fake_responses)
        )
        with patch.dict(
            environ,
            {
                "OPENAI_API_KEY": "test-key",
                "COERIA_OPENAI_VALIDATION_RETRIES": "0",
            },
            clear=False,
        ):
            result = agent.generate("resources", state)

        self.assertEqual(result.artifact["selected_types"], [RESOURCE_TEST])
        self.assertTrue(result.artifact["test"]["questions"])
        _validate_artifact("resources", result.artifact, state)

    def test_scoped_test_repairs_coverage_and_derives_total_points(self) -> None:
        state = create_session(
            self.course,
            resource_types=[RESOURCE_TEST],
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        state["resource_generation_scope"] = RESOURCE_TEST
        valid_test = deepcopy(
            self.agent.generate("resources", state).artifact["test"]
        )
        valid_test["total_points"] = 1
        valid_test["questions"][0]["id"] = "duplicado"
        incomplete_test = deepcopy(valid_test)
        missing_outcome = incomplete_test["questions"].pop()["outcome_id"]

        class FakeResponses:
            def __init__(self):
                self.calls = []
                self.payloads = [incomplete_test, valid_test]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps(
                        {"artifact": self.payloads.pop(0)}
                    ),
                    id=f"response-{len(self.calls)}",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        fake_responses = FakeResponses()
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=fake_responses)
        )
        with patch.dict(
            environ,
            {
                "OPENAI_API_KEY": "test-key",
                "COERIA_OPENAI_VALIDATION_RETRIES": "1",
            },
            clear=False,
        ):
            result = agent.generate("resources", state)

        retry_context = json.loads(fake_responses.calls[1]["input"])
        self.assertIn(
            missing_outcome,
            retry_context["automatic_validation_feedback"]["validation_error"],
        )
        expected_total = sum(
            question["points"] for question in result.artifact["test"]["questions"]
        )
        self.assertEqual(result.artifact["test"]["total_points"], expected_total)
        self.assertEqual(
            [
                question["id"]
                for question in result.artifact["test"]["questions"]
            ],
            [
                f"Q{index}"
                for index in range(
                    1,
                    len(result.artifact["test"]["questions"]) + 1,
                )
            ],
        )
        outcome_schema = fake_responses.calls[0]["text"]["format"]["schema"][
            "properties"
        ]["artifact"]["properties"]["questions"]["items"]["properties"][
            "outcome_id"
        ]
        self.assertEqual(
            set(outcome_schema["enum"]),
            {item["id"] for item in state["learning_outcomes"]},
        )
        _validate_artifact("resources", result.artifact, state)

    def test_scoped_practical_repairs_coverage_and_weights_without_retry(self) -> None:
        state = create_session(
            self.course,
            resource_types=[RESOURCE_PRACTICAL],
            agent=self.agent,
        )
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)
        state["resource_generation_scope"] = RESOURCE_PRACTICAL
        practical = deepcopy(
            self.agent.generate("resources", state).artifact["practical_activity"]
        )
        missing_outcome = state["learning_outcomes"][1]["id"]
        for step in practical["steps"]:
            step["outcome_ids"] = [
                outcome_id
                for outcome_id in step["outcome_ids"]
                if outcome_id != missing_outcome
            ]
        practical["steps"][0]["outcome_ids"].append("RA-inexistente")
        practical["steps"][0]["order"] = 99
        practical["criteria"][0]["weight"] = 60
        practical["criteria"][1]["weight"] = 0

        class FakeResponses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": practical}),
                    id="response-practical",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        fake_responses = FakeResponses()
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=fake_responses)
        )
        with patch.dict(
            environ,
            {
                "OPENAI_API_KEY": "test-key",
                "COERIA_OPENAI_VALIDATION_RETRIES": "2",
            },
            clear=False,
        ):
            result = agent.generate("resources", state)

        self.assertEqual(len(fake_responses.calls), 1)
        repaired = result.artifact["practical_activity"]
        covered = {
            outcome_id
            for step in repaired["steps"]
            for outcome_id in step["outcome_ids"]
        }
        expected = {item["id"] for item in state["learning_outcomes"]}
        self.assertEqual(covered, expected)
        self.assertNotIn(
            "RA-inexistente",
            [
                outcome_id
                for step in repaired["steps"]
                for outcome_id in step["outcome_ids"]
            ],
        )
        self.assertEqual(
            [step["order"] for step in repaired["steps"]],
            list(range(1, len(repaired["steps"]) + 1)),
        )
        added_step = next(
            step
            for step in repaired["steps"]
            if step["outcome_ids"] == [missing_outcome]
            and missing_outcome in step["instruction"]
        )
        self.assertTrue(added_step["instruction"])
        weights = [item["weight"] for item in repaired["criteria"]]
        self.assertEqual(sum(weights), 100)
        self.assertTrue(all(weight > 0 for weight in weights))
        practical_schema = fake_responses.calls[0]["text"]["format"]["schema"][
            "properties"
        ]["artifact"]
        outcome_schema = practical_schema["properties"]["steps"]["items"][
            "properties"
        ]["outcome_ids"]["items"]
        self.assertEqual(set(outcome_schema["enum"]), expected)
        self.assertTrue(result.metadata["guardrail_corrections"])
        _validate_artifact("resources", result.artifact, state)

    def test_learning_outcome_level_must_match_its_verb(self) -> None:
        state = create_session(self.course, agent=self.agent)
        invalid_artifact = deepcopy(state["learning_outcomes"])
        invalid_artifact[0]["action_verb"] = "identificar"
        invalid_artifact[0]["statement"] = "Identificar conceitos fundamentais."
        invalid_artifact[0]["taxonomy_level"] = "Abstrato expandido"

        with self.assertRaisesRegex(AgentGenerationError, "nível e verbo compatíveis"):
            _validate_artifact("learning_outcomes", invalid_artifact, state)

        invalid_ids = deepcopy(state["learning_outcomes"])
        invalid_ids[0]["id"] = "1"
        with self.assertRaisesRegex(AgentGenerationError, "IDs RA1, RA2"):
            _validate_artifact("learning_outcomes", invalid_ids, state)

        schema = _schema_for("learning_outcomes", state)
        item_properties = schema["properties"]["artifact"]["items"]["properties"]
        self.assertEqual(
            item_properties["taxonomy_level"]["enum"],
            ["Uni-estrutural", "Multi-estrutural", "Relacional", "Abstrato expandido"],
        )

    def test_learning_outcome_generation_canonicalizes_level_from_verb(self) -> None:
        state = create_session(self.course, agent=self.agent)
        generated = deepcopy(state["learning_outcomes"])
        generated[0]["action_verb"] = "analisar"
        generated[0]["statement"] = "Analisar conceitos fundamentais."
        generated[0]["taxonomy_level"] = "Uni-estrutural"
        generated[0]["id"] = "resultado-um"

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": generated}),
                    id="response-outcomes",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        responses = FakeResponses()
        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=responses)
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = agent.generate("learning_outcomes", state)

        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(
            [item["id"] for item in result.artifact],
            [f"RA{index + 1}" for index in range(len(result.artifact))],
        )
        self.assertEqual(result.artifact[0]["taxonomy_level"], "Relacional")
        self.assertEqual(
            result.artifact[0]["taxonomy_level"],
            taxonomy_level_for_verb("SOLO", result.artifact[0]["action_verb"]),
        )
        self.assertEqual(len(result.metadata["guardrail_corrections"]), 1)
        correction = result.metadata["guardrail_corrections"][0]
        self.assertEqual(correction["outcome_id"], "RA1")
        self.assertEqual(
            correction["changes"]["id"],
            {"received": "resultado-um", "used": "RA1"},
        )
        self.assertEqual(
            correction["changes"]["taxonomy_level"],
            {"received": "Uni-estrutural", "used": "Relacional"},
        )

    def test_assessment_guardrail_keeps_valid_teaching_and_outcome_links(self) -> None:
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
                        [outcome["id"]]
                        if index == 0
                        else [next_outcome, outcome["id"]]
                    ),
                    "teaching_activity_ids": [
                        activity["id"]
                        for activity in state["teaching_activities"]
                        if set(activity.get("outcome_ids", []))
                        & (
                            {outcome["id"]}
                            if index == 0
                            else {next_outcome, outcome["id"]}
                        )
                    ],
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

        for index, item in enumerate(result.artifact, start=1):
            self.assertEqual(item["id"], f"TA{index}")
            self.assertTrue(item["teaching_activity_ids"])
            self.assertNotIn("outcome_id", item)
            self.assertTrue(item["outcome_ids"])
            self.assertEqual(item["assessment_purpose"], "Formativa")
        self.assertTrue(result.metadata["guardrail_corrections"])

    def test_teaching_guardrail_uses_biggs_identifiers(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        generated = deepcopy(state["teaching_activities"])
        for index, item in enumerate(generated, start=1):
            item["id"] = f"A{index}"

        class FakeResponses:
            def create(self, **_kwargs):
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": generated}),
                    id="teaching-response",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=FakeResponses())
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = agent.generate("teaching_activities", state)

        self.assertEqual(
            [item["id"] for item in result.artifact],
            [f"AE{index}" for index in range(1, len(generated) + 1)],
        )
        self.assertTrue(result.metadata["guardrail_corrections"])

    def test_alignment_synthesis_is_derived_from_approved_evidence(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        rows = derive_alignment_rows(state)

        self.assertEqual(len(rows), len(state["learning_outcomes"]))
        self.assertTrue(all(row["content_ids"] for row in rows))
        self.assertTrue(all(row["teaching_activity_ids"] for row in rows))
        self.assertTrue(all(row["assessment_ids"] for row in rows))
        self.assertTrue(all(row["status"] == "Coerente" for row in rows))

    def test_alignment_requires_a_direct_result_to_assessment_link(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        outcome_id = state["learning_outcomes"][0]["id"]
        for item in state["assessment_activities"]:
            item["outcome_ids"] = [
                identifier
                for identifier in item["outcome_ids"]
                if identifier != outcome_id
            ]

        row = next(
            item for item in derive_alignment_rows(state)
            if item["outcome_id"] == outcome_id
        )
        self.assertEqual(row["assessment_ids"], [])
        self.assertEqual(row["status"], "Requer revisão")
        self.assertIn("ligação direta", row["rationale"])

    def test_assessment_rejects_a_result_without_a_shared_teaching_activity(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        assessments = deepcopy(state["assessment_activities"])
        teaching_activity = state["teaching_activities"][0]
        unsupported_outcome = next(
            item["id"]
            for item in state["learning_outcomes"]
            if item["id"] not in teaching_activity["outcome_ids"]
        )
        assessments[0]["teaching_activity_ids"] = [teaching_activity["id"]]
        assessments[0]["outcome_ids"] = [unsupported_outcome]
        with self.assertRaisesRegex(AgentGenerationError, "não é desenvolvido"):
            _validate_artifact("assessment_activities", assessments, state)

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


    def test_gpt_4o_mini_critic_omits_reasoning_parameter(self) -> None:
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "passed": True,
                        "findings": [],
                        "revision_instructions": "",
                    }
                ),
                id="response-critic",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                ),
            )

        critic = OpenAIPedagogicalCritic(
            model="gpt-4o-mini",
            client_factory=lambda: SimpleNamespace(
                responses=SimpleNamespace(create=create)
            ),
        )
        state = {
            "course": {"taxonomy_type": "SOLO"},
        }
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = critic.review(
                "curriculum_analysis",
                state,
                {"contents": []},
            )

        self.assertTrue(result.passed)
        self.assertEqual(calls[0]["model"], "gpt-4o-mini")
        self.assertNotIn("reasoning", calls[0])
        finding_schema = calls[0]["text"]["format"]["schema"]["properties"][
            "findings"
        ]["items"]
        self.assertIn("target", finding_schema["properties"])
        self.assertIn("target", finding_schema["required"])
        context = json.loads(calls[0]["input"])
        self.assertIn("available_finding_targets", context)

    def test_default_openai_profile_prioritises_cost(self) -> None:
        cleared_configuration = {
            f"{prefix}_{suffix}": ""
            for prefix in ("COERIA", "AGIR_SOLO", "PRISM")
            for suffix in (
                "OPENAI_MODEL",
                "OPENAI_RESOURCE_MODEL",
                "OPENAI_REASONING_EFFORT",
            )
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

        self.assertEqual(DEFAULT_MODEL, "gpt-4o-mini")
        self.assertEqual(DEFAULT_RESOURCE_MODEL, "gpt-4o-mini")
        self.assertEqual(generator.model, "gpt-4o-mini")
        self.assertEqual(generator.resource_model, "gpt-4o-mini")
        self.assertEqual(generator.reasoning_effort, "minimal")
        self.assertEqual(critic.model, "gpt-4o-mini")
        self.assertEqual(critic.reasoning_effort, "minimal")
        self.assertNotIn(
            "resources", AgenticPedagogicalTeam.DEFAULT_CRITIC_STAGES
        )
        self.assertEqual(
            AgenticPedagogicalTeam.DEFAULT_CRITIC_STAGES[:3],
            (
                "learning_outcomes",
                "teaching_activities",
                "assessment_activities",
            ),
        )

    def test_curricular_relations_are_explicit_and_many_to_many(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(5):
            state = review_current_stage(state, "approve", agent=self.agent)

        self.assertGreaterEqual(len(state["learning_outcomes"]), 4)
        selected_taxonomy = state["course"]["taxonomy_type"]
        self.assertTrue(
            all(
                taxonomy_verb_allowed(
                    selected_taxonomy,
                    item["taxonomy_level"],
                    item["action_verb"],
                )
                for item in state["learning_outcomes"]
            )
        )
        self.assertTrue(
            any(
                len(item["teaching_activity_ids"]) > 1
                for item in state["assessment_activities"]
            )
        )
        teaching_ids = {item["id"] for item in state["teaching_activities"]}
        self.assertTrue(
            all(
                item["teaching_activity_ids"]
                and set(item["teaching_activity_ids"]) <= teaching_ids
                for item in state["assessment_activities"]
            )
        )
        alignment_rows = derive_alignment_rows(state)
        self.assertTrue(all(row["content_ids"] for row in alignment_rows))
        self.assertTrue(all(row["assessment_ids"] for row in alignment_rows))
        self.assertTrue(all(row["teaching_activity_ids"] for row in alignment_rows))

    def test_teaching_and_assessment_identifiers_are_unambiguous(self) -> None:
        state = create_session(self.course, agent=self.agent)
        for _ in range(3):
            state = review_current_stage(state, "approve", agent=self.agent)

        teaching_ids = [item["id"] for item in state["teaching_activities"]]
        assessment_ids = [item["id"] for item in state["assessment_activities"]]
        self.assertEqual(
            teaching_ids,
            [f"AE{index}" for index in range(1, len(teaching_ids) + 1)],
        )
        self.assertEqual(
            assessment_ids,
            [f"TA{index}" for index in range(1, len(assessment_ids) + 1)],
        )
        self.assertTrue(set(teaching_ids).isdisjoint(assessment_ids))
        self.assertTrue(
            all(item["teaching_activity_ids"] for item in state["assessment_activities"])
        )
        self.assertTrue(
            all(
                "outcome_id" not in item and item["outcome_ids"]
                for item in state["assessment_activities"]
            )
        )

        invalid_teaching = deepcopy(state["teaching_activities"])
        invalid_teaching[0]["id"] = "A1"
        with self.assertRaisesRegex(AgentGenerationError, "IDs AE1"):
            _validate_artifact("teaching_activities", invalid_teaching, state)

        invalid_assessment = deepcopy(state["assessment_activities"])
        invalid_assessment[0]["id"] = "A1"
        with self.assertRaisesRegex(AgentGenerationError, "IDs TA1"):
            _validate_artifact("assessment_activities", invalid_assessment, state)

        unlinked_assessment = deepcopy(state["assessment_activities"])
        unlinked_assessment[0]["teaching_activity_ids"] = []
        with self.assertRaisesRegex(
            AgentGenerationError,
            "atividades de ensino-aprendizagem",
        ):
            _validate_artifact("assessment_activities", unlinked_assessment, state)

    def test_bloom_is_exclusive_and_assessments_are_never_mixed(self) -> None:
        course = CourseInput.create(
            "Programação com Bloom",
            self.course.source_text,
            taxonomy_type="Bloom",
        )
        state = create_session(course, agent=self.agent)
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)

        self.assertTrue(all("taxonomy" not in item for item in state["learning_outcomes"]))
        self.assertTrue(
            all(
                taxonomy_verb_allowed(
                    "Bloom", item["taxonomy_level"], item["action_verb"]
                )
                for item in state["learning_outcomes"]
            )
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
        self.assertTrue(is_learning_outcome_id("RA1"))
        self.assertTrue(is_learning_outcome_id("ra2"))
        self.assertFalse(is_learning_outcome_id("RA0"))
        self.assertTrue(
            has_single_action_verb(
                "Analisar os dados recolhidos.", "analisar", "SOLO"
            )
        )
        self.assertTrue(
            has_single_action_verb(
                "Reconhecer como construir topologias simples.",
                "reconhecer",
                "SOLO",
            )
        )
        self.assertTrue(
            has_single_action_verb(
                "Explicar como configurar uma interface de rede.",
                "explicar",
                "SOLO",
            )
        )
        self.assertFalse(
            has_single_action_verb(
                "Analisar e comparar os dados recolhidos.", "analisar", "SOLO"
            )
        )
        self.assertFalse(
            has_single_action_verb(
                "Interpretar endereços IP e construir topologias simples.",
                "interpretar",
                "SOLO",
            )
        )
        self.assertFalse(
            has_single_action_verb(
                "Interpretar endereços IP e construir topologias simples.",
                "definir",
                "SOLO",
            )
        )

    def test_curriculum_validation_rejects_missing_outcome_links(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state = review_current_stage(state, "approve", agent=self.agent)
        curriculum = deepcopy(state["curriculum_analysis"])
        missing_outcome = state["learning_outcomes"][-1]["id"]
        for content in curriculum["contents"]:
            content["outcome_ids"] = [
                identifier
                for identifier in content.get("outcome_ids", [])
                if identifier != missing_outcome
            ]

        with self.assertRaisesRegex(AgentGenerationError, "resultados de aprendizagem"):
            _validate_artifact("curriculum_analysis", curriculum, state)

    def test_schemas_follow_the_outcomes_first_sequence(self) -> None:
        state = create_session(self.course, agent=self.agent)
        schema = _schema_for("learning_outcomes", state)
        properties = schema["properties"]["artifact"]["items"]["properties"]

        self.assertIn("analisar", properties["action_verb"]["enum"])
        self.assertEqual(properties["id"]["pattern"], "^RA[1-9][0-9]*$")
        self.assertNotIn("content_links", properties)
        self.assertNotIn("objective_ids", properties)

        state = review_current_stage(state, "approve", agent=self.agent)
        curriculum_schema = _schema_for("curriculum_analysis", state)
        allowed_outcomes = {item["id"] for item in state["learning_outcomes"]}
        curriculum_properties = curriculum_schema["properties"]["artifact"]["properties"]
        outcome_items = curriculum_properties["contents"]["items"]["properties"][
            "outcome_ids"
        ]["items"]
        self.assertEqual(set(outcome_items["enum"]), allowed_outcomes)
        self.assertNotIn("objectives", curriculum_properties)
        self.assertNotIn("summary", curriculum_properties)
        self.assertNotIn("themes", curriculum_properties)
        self.assertEqual(
            curriculum_schema["properties"]["artifact"]["required"],
            ["contents"],
        )

        state = review_current_stage(state, "approve", agent=self.agent)
        teaching_schema = _schema_for("teaching_activities", state)
        teaching_properties = teaching_schema["properties"]["artifact"]["items"][
            "properties"
        ]
        self.assertEqual(
            teaching_properties["id"]["pattern"],
            "^AE[1-9][0-9]*$",
        )

        state = review_current_stage(state, "approve", agent=self.agent)
        assessment_schema = _schema_for("assessment_activities", state)
        assessment_properties = assessment_schema["properties"]["artifact"]["items"][
            "properties"
        ]
        self.assertEqual(
            assessment_properties["id"]["pattern"],
            "^TA[1-9][0-9]*$",
        )
        self.assertEqual(
            set(assessment_properties["teaching_activity_ids"]["items"]["enum"]),
            {item["id"] for item in state["teaching_activities"]},
        )
        self.assertNotIn("outcome_id", assessment_properties)
        self.assertEqual(
            set(assessment_properties["outcome_ids"]["items"]["enum"]),
            {item["id"] for item in state["learning_outcomes"]},
        )

        for _ in range(1):
            state = review_current_stage(state, "approve", agent=self.agent)
        design_schema = _schema_for("pedagogical_design", state)
        lesson_schema = design_schema["properties"]["artifact"]["properties"][
            "lessons"
        ]["items"]
        lesson_properties = lesson_schema[
            "properties"
        ]
        self.assertEqual(
            set(lesson_properties["component_ids"]["items"]["enum"]),
            {
                item["id"]
                for stage in ("teaching_activities", "assessment_activities")
                for item in state[stage]
            },
        )
        self.assertEqual(
            set(lesson_schema["required"]),
            {"duration_minutes", "session_type", "component_ids", "notes"},
        )

        state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["current_stage"], "resources")

    def test_complete_lesson_proposal_receives_explicit_previous_context(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state["course"]["contact_hours"] = 6
        state["course"]["autonomous_hours"] = 18
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)
        current_draft = deepcopy(state["pedagogical_design"])
        current_draft["lessons"][0]["notes"] = "Decisão atual do docente."
        state["pedagogical_design"] = current_draft
        generated = self.agent.generate("pedagogical_design", state).artifact
        for lesson in generated["lessons"]:
            lesson["duration_minutes"] = 30
            lesson["component_ids"] = []
        received_minutes = sum(
            lesson["duration_minutes"] for lesson in generated["lessons"]
        )
        self.assertNotEqual(received_minutes, 360)

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps({"artifact": generated}),
                    id="lesson-response",
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )

        responses = FakeResponses()
        openai_agent = OpenAIPedagogicalAgent(
            client_factory=lambda: SimpleNamespace(responses=responses)
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            proposed = request_ai_assistance(
                state,
                "pedagogical_design",
                [],
                "Toda a etapa",
                "Reorganizar as aulas com base nos artefactos anteriores.",
                agent=openai_agent,
            )

        request_context = json.loads(responses.calls[0]["input"])
        brief = request_context["lesson_planning_brief"]
        expected_components = {
            item["id"]
            for stage in ("teaching_activities", "assessment_activities")
            for item in state[stage]
        }
        self.assertEqual(
            request_context["current_stage_artifact_read_only"],
            current_draft,
        )
        self.assertEqual(
            brief["duration_targets"],
            {
                "contact_minutes_for_lessons": 360,
                "autonomous_work_minutes_context_only": 1080,
            },
        )
        self.assertEqual(
            {item["id"] for item in brief["component_catalogue"]},
            expected_components,
        )
        self.assertEqual(
            {item["outcome_id"] for item in brief["alignment_chains"]},
            {item["id"] for item in state["learning_outcomes"]},
        )
        self.assertTrue(
            all(item["teaching_activity_ids"] for item in brief["alignment_chains"])
        )
        self.assertTrue(
            all(item["assessment_task_ids"] for item in brief["alignment_chains"])
        )
        proposal = proposed["ai_proposals"][-1]
        self.assertEqual(
            sum(
                lesson["duration_minutes"]
                for lesson in proposal["after"]["lessons"]
            ),
            360,
        )
        self.assertTrue(
            all(not lesson["component_ids"] for lesson in proposal["after"]["lessons"])
        )
        self.assertEqual(len(responses.calls), 1)
        correction = proposal["metadata"]["guardrail_corrections"][0]
        self.assertEqual(correction["received_total"], received_minutes)
        self.assertEqual(correction["used_total"], 360)

    def test_complete_ai_lesson_proposal_uses_contact_time_and_visible_notes(self) -> None:
        state = create_session(self.course, agent=self.agent)
        state["course"]["contact_hours"] = 4
        for _ in range(4):
            state = review_current_stage(state, "approve", agent=self.agent)
        state["_ai_assistance_request"] = {
            "mode": "complete_stage_proposal",
            "current_artifact": deepcopy(state["pedagogical_design"]),
        }
        invalid_notes = deepcopy(state["pedagogical_design"])
        invalid_notes["lessons"][0]["notes"] = ""
        with self.assertRaisesRegex(AgentGenerationError, "foco curricular"):
            _validate_artifact("pedagogical_design", invalid_notes, state)

        invalid_duration = deepcopy(state["pedagogical_design"])
        invalid_duration["lessons"][0]["duration_minutes"] += 1
        with self.assertRaisesRegex(AgentGenerationError, "horas de contacto"):
            _validate_artifact("pedagogical_design", invalid_duration, state)

        optional_components = deepcopy(state["pedagogical_design"])
        for lesson in optional_components["lessons"]:
            lesson["component_ids"] = []
        _validate_artifact("pedagogical_design", optional_components, state)

        state.pop("_ai_assistance_request")
        with self.assertRaisesRegex(AgentGenerationError, "horas de contacto"):
            _validate_artifact("pedagogical_design", invalid_duration, state)

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
