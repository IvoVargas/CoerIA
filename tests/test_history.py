import unittest
from copy import deepcopy

import app
from prism.models import CourseInput
from prism.workflow import create_session, create_test_agent, review_current_stage


class HistoryViewTests(unittest.TestCase):
    def test_all_generated_versions_can_be_consulted(self) -> None:
        course = CourseInput.create(
            unit_name="Programação",
            source_text=(
                "Algoritmos, variáveis e ciclos. Funções, testes e resolução "
                "de problemas."
            ),
            audience="Licenciatura",
            duration_hours=12,
        )
        agent = create_test_agent()
        state = create_session(course, agent=agent)
        state = review_current_stage(state, "approve", agent=agent)
        state = review_current_stage(state, "approve", agent=agent)
        approved_state = deepcopy(state)
        state = review_current_stage(
            state,
            "revise",
            feedback="Reorganizar os temas antes da Taxonomia SOLO.",
            revision_stage="curriculum_analysis",
            agent=agent,
        )

        labelled_choices = app._history_choices(state)
        choices = [value for _label, value in labelled_choices]
        self.assertIn("curriculum_analysis::0", choices)
        self.assertIn("curriculum_analysis::1", choices)
        labels = {value: label for label, value in labelled_choices}
        self.assertIn("(ativa)", labels["curriculum_analysis::1"])
        self.assertIn("(ativa)", labels["learning_outcomes::0"])
        self.assertIn("(desatualizada)", labels["teaching_activities::0"])
        self.assertIn("versão 1", app.render_history_artifact("curriculum_analysis::0", state))
        self.assertIn("versão 2", app.render_history_artifact("curriculum_analysis::1", state))
        self.assertIn(
            "versão ativa aprovada",
            app.render_stage_artifact(approved_state, "curriculum_analysis"),
        )


if __name__ == "__main__":
    unittest.main()
