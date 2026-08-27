from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest

from prism.agents import CritiqueResult, GenerationResult
from prism.application_service import ApplicationService
from prism.models import CourseInput, RESOURCE_TEST
from prism.persistence import SQLiteSessionStore
from prism.presentation import render_current_artifact
from prism.source_reduction import SourceReductionResult, reduce_source_text
from prism.workflow import (
    STAGE_ORDER,
    ai_review_is_current,
    create_session,
    decide_ai_proposal,
    navigate_to_stage,
    reopen_completed_manual_session,
    request_ai_assistance,
    restore_stage_version,
    review_current_stage,
    save_manual_draft,
    update_manual_resource_settings,
    version_restore_impact,
    verify_stage_with_ai,
)


def _course() -> CourseInput:
    return CourseInput.create(
        "Programação",
        "Fundamentos de programação, algoritmos, estruturas de controlo e testes.",
        taxonomy_type="SOLO",
    )


class OutcomeProposalAgent:
    def generate(self, stage: str, state: dict) -> GenerationResult:
        assert stage == "learning_outcomes"
        return GenerationResult(
            artifact=[
                {
                    "id": "1",
                    "outcome_type": "Conhecimento teórico",
                    "theme": "Algoritmos",
                    "taxonomy_level": "Uni-estrutural",
                    "action_verb": "Identificar",
                    "statement": "Identificar os elementos fundamentais de um algoritmo.",
                }
            ],
            metadata={"provider": "Teste", "model": "fake", "total_tokens": 3},
        )


class LocalizedOutcomeAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, stage: str, state: dict) -> GenerationResult:
        raise AssertionError("A geração da etapa inteira não pode ser executada.")

    def propose(
        self,
        stage: str,
        state: dict,
        scope_path: list[str | int],
        scope_label: str,
        instruction: str,
        current_value: object,
    ) -> GenerationResult:
        self.calls.append(
            {
                "stage": stage,
                "scope_path": scope_path,
                "scope_label": scope_label,
                "instruction": instruction,
                "current_value": current_value,
            }
        )
        return GenerationResult(
            artifact="Analisar algoritmos através de exemplos concretos.",
            metadata={"provider": "Teste", "model": "fragment-fake"},
        )


class WarningCritic:
    def review(self, stage: str, state: dict, artifact: object) -> CritiqueResult:
        return CritiqueResult(
            passed=True,
            findings=[
                {
                    "severity": "warning",
                    "criterion": "Clareza",
                    "message": "Pode concretizar melhor o contexto.",
                }
            ],
            revision_instructions="Opcional: concretizar o contexto.",
            metadata={"provider": "Teste", "model": "critic-fake"},
        )


def test_new_session_is_manual_first_and_does_not_build_an_ai_team() -> None:
    with patch("prism.workflow.build_pedagogical_team") as factory:
        state = create_session(_course(), ai_provider="OpenAI")

    factory.assert_not_called()
    assert state["status"] == "drafting"
    assert state["current_stage"] == "learning_outcomes"
    assert state["orchestration"]["mode"] == "manual-first"
    assert all(stage in state for stage in STAGE_ORDER[:-1])


def test_all_stages_can_be_opened_without_generation_or_validation() -> None:
    state = create_session(_course())
    for stage in STAGE_ORDER[:-1]:
        state = navigate_to_stage(state, stage)
        assert state["current_stage"] == stage
        assert state["status"] == "drafting"


def test_earlier_edit_preserves_later_work_and_marks_it_for_review() -> None:
    state = create_session(_course())
    design = {
        "strategy": "Prática orientada.",
        "sequence": [{"outcome_id": "RA1", "focus": "Aplicação"}],
    }
    state = save_manual_draft(state, "pedagogical_design", design)
    preserved = deepcopy(state["pedagogical_design"])

    state = save_manual_draft(
        state,
        "learning_outcomes",
        OutcomeProposalAgent().generate("learning_outcomes", state).artifact,
    )

    assert state["pedagogical_design"] == preserved
    assert state["stage_statuses"]["pedagogical_design"] == "needs_review"


def test_historical_version_becomes_active_without_creating_a_new_version() -> None:
    state = create_session(_course())
    version_one = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos de um algoritmo.",
        }
    ]
    version_two = deepcopy(version_one)
    version_two[0]["statement"] = "Identificar os elementos essenciais de um algoritmo."
    state = save_manual_draft(state, "learning_outcomes", version_one)
    state = save_manual_draft(state, "learning_outcomes", version_two)
    curriculum = deepcopy(state["curriculum_analysis"])
    curriculum["summary"] = "Rascunho curricular posterior."
    state = save_manual_draft(state, "curriculum_analysis", curriculum)
    state["final_validation"] = {"passed": True, "checks": []}
    state["versions"]["final_validation"] = [deepcopy(state["final_validation"])]
    state["active_versions"]["final_validation"] = 1
    state["status"] = "completed"
    state["current_stage"] = "final_validation"

    impact = version_restore_impact(state, "learning_outcomes::0")
    restored = restore_stage_version(
        state,
        "learning_outcomes::0",
    )

    assert impact["version_number"] == 1
    assert impact["was_completed"] is True
    assert "curriculum_analysis" in impact["affected_stages"]
    assert restored["learning_outcomes"] == version_one
    assert restored["versions"]["learning_outcomes"][1] == version_two
    assert len(restored["versions"]["learning_outcomes"]) == 2
    assert len(restored["generation_metadata"]["learning_outcomes"]) == 2
    assert restored["active_versions"]["learning_outcomes"] == 1
    assert restored["stage_statuses"]["curriculum_analysis"] == "needs_review"
    assert restored["status"] == "drafting"
    assert "final_validation" not in restored
    assert any("novamente ativa a versão 1" in item["event"] for item in restored["audit"])
    assert "versão 1" in render_current_artifact(restored)


def test_active_and_derived_versions_cannot_be_restored() -> None:
    state = create_session(_course())
    version = OutcomeProposalAgent().generate("learning_outcomes", state).artifact
    state = save_manual_draft(state, "learning_outcomes", version)

    with pytest.raises(ValueError, match="já é a versão ativa"):
        restore_stage_version(
            state,
            "learning_outcomes::0",
        )
    with pytest.raises(ValueError, match="recalculada"):
        version_restore_impact(state, "final_validation::0")


def test_ai_assistance_requires_an_explicit_acceptance() -> None:
    state = create_session(_course())
    proposed = request_ai_assistance(
        state,
        "learning_outcomes",
        [],
        "Toda a etapa",
        "Propor um resultado inicial.",
        agent=OutcomeProposalAgent(),
    )

    assert proposed["learning_outcomes"] == []
    assert proposed["ai_proposals"][-1]["status"] == "pending"
    assert proposed["ai_proposals"][-1]["after"][0]["id"] == "RA1"

    accepted = decide_ai_proposal(proposed, proposed["ai_proposals"][-1]["id"], True)
    assert accepted["learning_outcomes"][0]["id"] == "RA1"
    assert accepted["ai_proposals"][-1]["status"] == "accepted"
    assert accepted["generation_metadata"]["learning_outcomes"][-1]["human_approved"]


def test_full_outcome_proposal_remaps_downstream_references_after_compaction() -> None:
    state = create_session(_course())
    outcomes = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar os elementos de um algoritmo.",
        },
        {
            "id": "RA3",
            "outcome_type": "Conhecimento teórico",
            "theme": "Testes",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar os resultados de testes.",
        },
    ]
    state["learning_outcomes"] = deepcopy(outcomes)
    state["curriculum_analysis"]["contents"] = [
        {"id": "C1", "title": "Testes", "description": "Testes", "outcome_ids": ["RA3"]}
    ]
    state["teaching_activities"] = [
        {"id": "AE1", "outcome_ids": ["RA3"], "activity": "Analisar casos."}
    ]
    state["assessment_activities"] = [
        {"id": "TA1", "outcome_ids": ["RA3"], "task": "Resolver um caso."}
    ]
    state["pedagogical_design"] = {
        "strategy": "Prática orientada.",
        "sequence": [{"outcome_id": "RA3", "focus": "Testes"}],
    }
    state["resources"]["test"]["questions"] = [
        {"id": "Q1", "outcome_ids": ["RA3"], "question": "Analise o caso."}
    ]

    class CompactOutcomeProposalAgent:
        def generate(self, stage: str, _state: dict) -> GenerationResult:
            assert stage == "learning_outcomes"
            compacted = deepcopy(outcomes)
            compacted[1]["id"] = "RA2"
            return GenerationResult(
                artifact=compacted,
                metadata={"provider": "Teste", "model": "compact-fake"},
            )

    proposed = request_ai_assistance(
        state,
        "learning_outcomes",
        [],
        "Toda a etapa",
        "Compactar os identificadores.",
        agent=CompactOutcomeProposalAgent(),
    )
    accepted = decide_ai_proposal(
        proposed,
        proposed["ai_proposals"][-1]["id"],
        True,
    )

    assert [item["id"] for item in accepted["learning_outcomes"]] == ["RA1", "RA2"]
    assert accepted["curriculum_analysis"]["contents"][0]["outcome_ids"] == ["RA2"]
    assert accepted["teaching_activities"][0]["outcome_ids"] == ["RA2"]
    assert accepted["assessment_activities"][0]["outcome_ids"] == ["RA2"]
    assert accepted["pedagogical_design"]["sequence"][0]["outcome_id"] == "RA2"
    assert accepted["resources"]["test"]["questions"][0]["outcome_ids"] == ["RA2"]


def test_localized_assistance_generates_only_the_selected_fragment() -> None:
    state = create_session(_course())
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "outcome_type": "Conhecimento teórico",
            "theme": "Variáveis",
            "taxonomy_level": "Uni-estrutural",
            "action_verb": "Identificar",
            "statement": "Identificar variáveis num programa.",
        },
        {
            "id": "RA2",
            "outcome_type": "Conhecimento teórico",
            "theme": "Algoritmos",
            "taxonomy_level": "Relacional",
            "action_verb": "Analisar",
            "statement": "Analisar algoritmos.",
        },
    ]
    agent = LocalizedOutcomeAgent()

    proposed = request_ai_assistance(
        state,
        "learning_outcomes",
        [1, "statement"],
        "Linha 2 — campo Resultado de aprendizagem",
        "Clarificar o enunciado.",
        agent=agent,
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["current_value"] == "Analisar algoritmos."
    assert proposed["ai_proposals"][-1]["after"] == (
        "Analisar algoritmos através de exemplos concretos."
    )
    accepted = decide_ai_proposal(proposed, proposed["ai_proposals"][-1]["id"], True)
    assert accepted["learning_outcomes"][0] == state["learning_outcomes"][0]
    assert accepted["learning_outcomes"][1]["statement"].endswith("concretos.")


def test_ai_proposal_applies_selected_cells_in_a_single_version() -> None:
    state = create_session(_course())
    current = {
        "id": "RA1",
        "outcome_type": "Conhecimento teórico",
        "theme": "Algoritmos",
        "taxonomy_level": "Relacional",
        "action_verb": "Analisar",
        "statement": "Analisar algoritmos.",
    }
    proposed_row = {
        **current,
        "theme": "Algoritmos eficientes",
        "statement": "Analisar algoritmos através de exemplos concretos.",
    }
    state["learning_outcomes"] = [current]
    state["ai_proposals"] = [
        {
            "id": "P1",
            "stage": "learning_outcomes",
            "scope_path": [0],
            "scope_label": "Linha 1 (RA1)",
            "instruction": "Melhorar a linha.",
            "before": current,
            "after": proposed_row,
            "status": "pending",
            "metadata": {"provider": "Teste"},
        }
    ]

    accepted = decide_ai_proposal(
        state,
        "P1",
        True,
        [
            {"key": "change-1", "accept": False},
            {
                "key": "change-2",
                "accept": True,
                "value": "Analisar algoritmos com casos reais.",
            },
        ],
    )

    assert accepted["learning_outcomes"][0]["theme"] == "Algoritmos"
    assert accepted["learning_outcomes"][0]["statement"].endswith("casos reais.")
    assert accepted["ai_proposals"][-1]["status"] == "partially_accepted"
    assert len(accepted["versions"]["learning_outcomes"]) == 1


def test_rejected_ai_assistance_does_not_change_the_draft() -> None:
    state = create_session(_course())
    proposed = request_ai_assistance(
        state,
        "learning_outcomes",
        [],
        "Toda a etapa",
        "Propor um resultado inicial.",
        agent=OutcomeProposalAgent(),
    )
    rejected = decide_ai_proposal(proposed, proposed["ai_proposals"][-1]["id"], False)

    assert rejected["learning_outcomes"] == []
    assert rejected["ai_proposals"][-1]["status"] == "rejected"


def test_stale_ai_proposal_cannot_overwrite_newer_manual_work() -> None:
    state = create_session(_course())
    proposed = request_ai_assistance(
        state,
        "learning_outcomes",
        [],
        "Toda a etapa",
        "Propor um resultado inicial.",
        agent=OutcomeProposalAgent(),
    )
    changed = deepcopy(proposed)
    changed["learning_outcomes"] = [{"id": "RA-MANUAL"}]

    with pytest.raises(ValueError, match="alterado depois desta proposta"):
        decide_ai_proposal(changed, proposed["ai_proposals"][-1]["id"], True)


def test_stage_ai_review_is_saved_but_does_not_block_navigation() -> None:
    state = create_session(_course())
    reviewed = verify_stage_with_ai(state, "learning_outcomes", critic=WarningCritic())

    assert reviewed["status"] == "drafting"
    review = reviewed["ai_reviews"]["learning_outcomes"][-1]
    assert review["non_blocking"]
    assert ai_review_is_current(reviewed, "learning_outcomes", review)
    assert navigate_to_stage(reviewed, "curriculum_analysis")["current_stage"] == "curriculum_analysis"

    changed = save_manual_draft(
        reviewed,
        "learning_outcomes",
        [{"id": "RA1", "statement": "Identificar elementos de um algoritmo."}],
    )
    assert not ai_review_is_current(changed, "learning_outcomes", review)


def test_ai_review_discards_deterministic_coverage_claims() -> None:
    class DeterministicHallucinationCritic:
        def review(self, stage, state, artifact):
            return CritiqueResult(
                passed=False,
                findings=[
                    {
                        "severity": "blocking",
                        "criterion": "assessment_coverage",
                        "message": "RA1, RA2, RA3, RA4 e RA5 estão em falta.",
                    },
                    {
                        "severity": "warning",
                        "criterion": "Clareza pedagógica",
                        "message": "Explicitar melhor a transição entre atividades.",
                    },
                ],
                revision_instructions="Rever a cobertura e a transição.",
                metadata={"provider": "Teste", "model": "critic-fake"},
            )

    reviewed = verify_stage_with_ai(
        create_session(_course()),
        "resources",
        critic=DeterministicHallucinationCritic(),
    )
    review = reviewed["ai_reviews"]["resources"][-1]

    assert [item["criterion"] for item in review["findings"]] == [
        "Clareza pedagógica"
    ]
    assert review["passed"]
    assert review["metadata"]["ignored_deterministic_findings"][0][
        "criterion"
    ] == "assessment_coverage"


def test_resource_selection_can_change_without_generation() -> None:
    state = navigate_to_stage(create_session(_course()), "resources")
    updated = update_manual_resource_settings(state, [RESOURCE_TEST])

    assert updated["resource_types"] == [RESOURCE_TEST]
    assert updated["resources"]["selected_types"] == [RESOURCE_TEST]
    assert updated["resources"]["test"]["questions"] == []


def test_resource_selection_is_restricted_to_the_resources_stage() -> None:
    with pytest.raises(ValueError, match="pertence à etapa Recursos educativos"):
        update_manual_resource_settings(create_session(_course()), [RESOURCE_TEST])


def test_final_deterministic_validation_is_mandatory() -> None:
    state = navigate_to_stage(create_session(_course()), "final_validation")
    assert not state["final_validation"]["passed"]
    with pytest.raises(ValueError, match="problemas bloqueantes"):
        review_current_stage(state, "approve")


def test_reopening_unchanged_final_validation_does_not_create_a_version() -> None:
    state = navigate_to_stage(create_session(_course()), "final_validation")
    initial_versions = len(state["versions"]["final_validation"])
    state = navigate_to_stage(state, "learning_outcomes")
    state = navigate_to_stage(state, "final_validation")

    assert len(state["versions"]["final_validation"]) == initial_versions


def test_completed_manual_session_cannot_be_reopened_by_navigation_click() -> None:
    state = create_session(_course())
    state["status"] = "completed"
    state["current_stage"] = "final_validation"

    with pytest.raises(ValueError, match="modo de consulta"):
        navigate_to_stage(state, "learning_outcomes")

    reopened = reopen_completed_manual_session(
        state,
        "learning_outcomes",
        "Corrigir um resultado após revisão.",
    )
    assert reopened["status"] == "drafting"
    assert reopened["current_stage"] == "learning_outcomes"
    assert reopened["stage_statuses"]["final_validation"] == "pending"


def test_long_sources_can_start_manual_authoring_without_ai_reduction() -> None:
    source = "Conteúdo curricular. " * 8_000
    with patch("prism.source_reduction._provider_client") as provider:
        result = reduce_source_text(source, provider="OpenAI", allow_ai=False)

    provider.assert_not_called()
    assert result.text == source.strip()
    assert result.metadata["deferred"] is True


def test_initial_data_update_preserves_artifacts_and_requires_review(tmp_path) -> None:
    service = ApplicationService(SQLiteSessionStore(tmp_path / "initial-edit.db"))
    state = create_session(_course())
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "statement": "Analisar estruturas de controlo.",
            "verb": "Analisar",
            "level": "Relacional - SOLO 4",
            "outcome_type": "Conhecimentos",
        }
    ]
    state["stage_statuses"]["learning_outcomes"] = "draft"
    state["current_stage"] = "resources"
    state["ai_proposals"] = [{"id": "P1", "status": "pending"}]
    state = service._persist(state)
    original_outcomes = deepcopy(state["learning_outcomes"])
    form = service.restored_initial_fields(state)
    form["unit_name"] = "Programação corrigida"

    updated = service.update_session_initial_data(state, form)

    assert updated["course"]["unit_name"] == "Programação corrigida"
    assert updated["learning_outcomes"] == original_outcomes
    assert updated["current_stage"] == "resources"
    assert updated["stage_statuses"]["learning_outcomes"] == "needs_review"
    assert updated["stage_statuses"]["final_validation"] == "pending"
    assert updated["status"] == "drafting"
    assert updated["ai_proposals"][0]["status"] == "superseded"
    assert updated["audit"][-1]["stage"] == "Dados iniciais"
    assert service.load_session(updated["session_id"])["course"]["unit_name"] == (
        "Programação corrigida"
    )


def test_deferred_source_reduction_runs_before_first_ai_request(
    tmp_path,
) -> None:
    state = create_session(_course())
    state["source_original_text"] = "Fonte extensa original."
    state["source_reduction"] = {"deferred": True}
    service = ApplicationService(SQLiteSessionStore(tmp_path / "reduction.db"))
    state = service._persist(state)
    reduced = SourceReductionResult(
        "Fonte reduzida.",
        {"applied": True, "deferred": False, "original_chars": 23},
    )

    with patch("prism.application_service.reduce_source_text", return_value=reduced) as reducer:
        prepared = service._prepare_source_for_ai(state)

    assert reducer.call_count == 1
    assert reducer.call_args.kwargs["allow_ai"] is True
    assert prepared["course"]["source_text"] == "Fonte reduzida."
    assert prepared["source_original_text"] == "Fonte extensa original."
    assert service.load_session(state["session_id"])["source_reduction"]["deferred"] is True
