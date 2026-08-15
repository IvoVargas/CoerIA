import json
import unittest
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from os import environ
from unittest.mock import patch

from docx import Document
from pptx import Presentation

from prism.agents import GenerationResult
from prism.exporter import export_resource_package
from prism.models import CourseInput, SUPPORTED_RESOURCE_TYPES
from prism.quality import evaluate_quality
from prism.workflow import create_session, create_test_agent, review_current_stage


class ResourceGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.course = CourseInput.create(
            unit_name="Programação Aplicada",
            source_text=(
                "Algoritmos e estruturas de controlo. Funções e modularidade. "
                "Testes automatizados e resolução de problemas aplicados."
            ),
            audience="Licenciatura",
            duration_hours=20,
            bibliography=(
                "Biggs, J., & Tang, C. (2011). Teaching for Quality Learning at University.\n"
                "Anderson, L. W., & Krathwohl, D. R. (2001). A Taxonomy for Learning."
            ),
        )
        self.agent = create_test_agent()

    def _resource_state(self):
        state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(7):
            state = review_current_stage(state, "approve", agent=self.agent)
        self.assertEqual(state["current_stage"], "resources")
        return state

    def test_every_selected_resource_is_generated_and_validated(self) -> None:
        state = self._resource_state()
        resources = state["resources"]
        self.assertTrue(resources["presentation_outline"])
        self.assertTrue(
            all(
                slide.get("visual_kind")
                and slide.get("visual_title")
                and 2 <= len(slide.get("visual_items", [])) <= 4
                and slide.get("visual_source")
                and slide.get("alt_text")
                for slide in resources["presentation_outline"]
            )
        )
        self.assertTrue(resources["lesson_worksheet"]["sections"])
        self.assertTrue(resources["test"]["questions"])
        self.assertTrue(resources["practical_activity"]["steps"])
        self.assertTrue(resources["quality"]["passed"])
        self.assertEqual(resources["quality"]["status"], "OK")

    def test_quality_validation_is_independent_from_the_generator(self) -> None:
        state = self._resource_state()
        tampered = deepcopy(state)
        tampered["teaching_activities"].pop()
        report = evaluate_quality(tampered, tampered["resources"])
        self.assertFalse(report["passed"])
        self.assertGreater(report["summary"]["errors"], 0)

    def test_quality_rejects_an_incomplete_visual_specification(self) -> None:
        state = self._resource_state()
        tampered = deepcopy(state)
        tampered["resources"]["presentation_outline"][1]["alt_text"] = ""
        report = evaluate_quality(tampered, tampered["resources"])
        visual_check = next(
            item for item in report["checks"] if item["id"] == "presentation_visuals"
        )
        self.assertFalse(report["passed"])
        self.assertEqual(visual_check["status"], "error")

    def test_resources_with_blocking_quality_errors_cannot_be_approved(self) -> None:
        state = self._resource_state()
        state["resources"]["quality"]["passed"] = False
        with self.assertRaises(ValueError):
            review_current_stage(state, "approve", agent=self.agent)

    def test_resource_quality_failure_triggers_a_bounded_automatic_revision(self) -> None:
        alignment_state = create_session(
            self.course,
            resource_types=list(SUPPORTED_RESOURCE_TYPES),
            agent=self.agent,
        )
        for _ in range(6):
            alignment_state = review_current_stage(
                alignment_state, "approve", agent=self.agent
            )
        valid_state = review_current_stage(
            deepcopy(alignment_state), "approve", agent=self.agent
        )
        valid_artifact = deepcopy(valid_state["resources"])
        valid_artifact.pop("quality", None)
        invalid_artifact = deepcopy(valid_artifact)
        invalid_artifact["presentation_outline"][1]["outcome_id"] = "RA_INEXISTENTE"

        class SequenceAgent:
            def __init__(self):
                self.artifacts = [invalid_artifact, valid_artifact]
                self.calls = 0

            def generate(self, stage, state):
                self.calls += 1
                return GenerationResult(
                    artifact=self.artifacts.pop(0),
                    metadata={"provider": "teste", "model": "n/a"},
                )

        agent = SequenceAgent()
        with patch.dict(
            environ,
            {"COERIA_RESOURCE_QUALITY_MAX_REVISIONS": "1"},
            clear=False,
        ):
            result = review_current_stage(
                alignment_state, "approve", agent=agent
            )

        self.assertEqual(agent.calls, 2)
        self.assertTrue(result["resources"]["quality"]["passed"])
        self.assertTrue(
            any(
                "reformulados automaticamente" in item["event"]
                for item in result["audit"]
            )
        )

    def test_completed_session_exports_a_complete_zip_package(self) -> None:
        state = review_current_stage(self._resource_state(), "approve", agent=self.agent)
        self.assertEqual(state["current_stage"], "final_validation")
        state = review_current_stage(state, "approve", agent=self.agent)
        package_path = Path(export_resource_package(state))
        try:
            with zipfile.ZipFile(package_path) as package:
                names = set(package.namelist())
                program_name = next(
                    name for name in names if name.endswith("_programa_uc.docx")
                )
                presentation_name = next(
                    name for name in names if name.endswith("_apresentacao.pptx")
                )
                self.assertTrue(any(name.endswith("_ficha_aula.docx") for name in names))
                self.assertTrue(any(name.endswith("_teste.docx") for name in names))
                self.assertTrue(any(name.endswith("_atividade_pratica.docx") for name in names))
                self.assertIn("matriz_alinhamento.csv", names)
                self.assertIn("rastreabilidade.csv", names)
                self.assertIn("manifesto.json", names)
                manifest = json.loads(package.read("manifesto.json"))
                self.assertEqual(manifest["application"], "CoerIA")
                self.assertIn("programas de unidades curriculares", manifest["application_name"])
                self.assertEqual(manifest["ai_provider"], "OpenAI")
                self.assertEqual(set(manifest["selected_resources"]), set(SUPPORTED_RESOURCE_TYPES))
                self.assertEqual(manifest["primary_product"], program_name)
                program = Document(BytesIO(package.read(program_name)))
                program_text = "\n".join(
                    [paragraph.text for paragraph in program.paragraphs]
                    + [cell.text for table in program.tables for row in table.rows for cell in row.cells]
                )
                self.assertIn("Programa da Unidade Curricular", program_text)
                self.assertIn("Taxonomia selecionada", program_text)
                self.assertIn("Matriz de alinhamento", program_text)
                self.assertIn("Teaching for Quality Learning", program_text)
                self.assertNotIn("Learning outcomes", program_text)
                presentation = Presentation(BytesIO(package.read(presentation_name)))
                self.assertGreaterEqual(len(presentation.slides), 3)
                for slide in presentation.slides:
                    self.assertGreaterEqual(len(slide.shapes), 5)
                    slide_text = "\n".join(
                        shape.text for shape in slide.shapes if hasattr(shape, "text_frame")
                    )
                    self.assertIn("Fonte visual:", slide_text)
                    descriptions = [
                        properties.get("descr", "")
                        for shape in slide.shapes
                        for properties in shape._element.xpath(".//p:cNvPr")
                    ]
                    self.assertTrue(any(description.strip() for description in descriptions))
        finally:
            package_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
