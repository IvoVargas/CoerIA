import base64
import unittest
from copy import deepcopy
from io import BytesIO

from PIL import Image

from prism.agents import (
    _canonicalize_resource_visuals,
    _selected_source_image_multimodal_input,
    _upstream_context,
)
from prism.models import RESOURCE_PRESENTATION


class SourceImageSelectionTests(unittest.TestCase):
    def test_only_human_selected_document_images_reach_resource_context(self) -> None:
        state = {
            "course": {"unit_name": "UC", "taxonomy_type": "SOLO"},
            "feedback": {},
            "resource_types": [RESOURCE_PRESENTATION],
            "selected_source_image_ids": ["document-selected"],
            "source_images": [
                {
                    "id": "document-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 2",
                    "filename": "figura.png",
                    "media_type": "image/png",
                    "candidate_kind": "composite_render",
                    "width_px": 900,
                    "height_px": 500,
                },
                {
                    "id": "document-not-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 4",
                    "filename": "outra.png",
                    "media_type": "image/png",
                    "candidate_kind": "embedded",
                    "width_px": 800,
                    "height_px": 600,
                },
            ],
            "ai_image_generation_enabled": False,
        }

        context = _upstream_context(state, "resources")

        catalogue = context["source_image_catalogue"]
        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0]["id"], "document-selected")
        self.assertEqual(catalogue[0]["candidate_kind"], "composite_render")

    def test_selected_thumbnail_is_sent_as_multimodal_openai_input(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (160, 90), (30, 100, 160)).save(
            image_buffer, format="PNG"
        )
        encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        state = {
            "selected_source_image_ids": ["document-selected"],
            "source_images": [
                {
                    "id": "document-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 2",
                    "media_type": "image/png",
                    "thumbnail_media_type": "image/png",
                    "thumbnail_base64": encoded,
                }
            ],
        }

        request_input = _selected_source_image_multimodal_input(
            state, {"source_image_catalogue": [{"id": "document-selected"}]}
        )

        self.assertIsNotNone(request_input)
        content = request_input[0]["content"]
        self.assertTrue(
            any(
                item.get("type") == "input_text"
                and "ID=document-selected" in item.get("text", "")
                for item in content
            )
        )
        image_parts = [item for item in content if item.get("type") == "input_image"]
        self.assertEqual(len(image_parts), 1)
        self.assertTrue(image_parts[0]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(image_parts[0]["detail"], "low")

    def test_human_selected_image_is_used_even_if_agent_returns_diagram(self) -> None:
        state = {
            "resource_types": [RESOURCE_PRESENTATION],
            "selected_source_image_ids": ["document-selected"],
            "source_images": [
                {
                    "id": "document-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 5",
                }
            ],
            "learning_outcomes": [{"id": "A1", "theme": "Tema"}],
            "teaching_activities": [],
            "assessment_activities": [],
            "ai_image_generation_enabled": False,
        }
        artifact = {
            "presentation_outline": [
                {
                    "title": "Capa",
                    "bullets": ["Introdução"],
                    "outcome_id": "",
                    "visual_mode": "diagrama",
                    "visual_asset_id": "",
                    "visual_prompt": "",
                    "visual_kind": "capa",
                    "visual_title": "Capa",
                    "visual_items": ["Programa", "Resultados"],
                    "visual_source": "Diagrama nativo.",
                    "alt_text": "Capa.",
                },
                {
                    "title": "Conteúdo",
                    "bullets": ["Ponto 1", "Ponto 2"],
                    "outcome_id": "A1",
                    "visual_mode": "diagrama",
                    "visual_asset_id": "",
                    "visual_prompt": "",
                    "visual_kind": "conceito",
                    "visual_title": "Tema",
                    "visual_items": ["Conceito", "Aplicação"],
                    "visual_source": "Diagrama nativo.",
                    "alt_text": "Diagrama do conteúdo.",
                },
                {
                    "title": "Síntese",
                    "bullets": ["Conclusão"],
                    "outcome_id": "",
                    "visual_mode": "diagrama",
                    "visual_asset_id": "",
                    "visual_prompt": "",
                    "visual_kind": "sintese",
                    "visual_title": "Síntese",
                    "visual_items": ["Rever", "Aplicar"],
                    "visual_source": "Diagrama nativo.",
                    "alt_text": "Síntese.",
                },
            ]
        }

        normalized, corrections = _canonicalize_resource_visuals(
            deepcopy(artifact), state
        )

        slide = normalized["presentation_outline"][1]
        self.assertEqual(slide["visual_mode"], "documento")
        self.assertEqual(slide["visual_asset_id"], "document-selected")
        self.assertIn("apoio.pdf", slide["visual_source"])
        self.assertIn("Página 5", slide["visual_source"])
        self.assertTrue(
            any(
                correction.get("reason")
                == "imagem_documental_selecionada_pelo_docente"
                for correction in corrections
            )
        )


if __name__ == "__main__":
    unittest.main()
