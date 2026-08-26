import base64
import json
import unittest
from copy import deepcopy
from io import BytesIO

from PIL import Image

from prism.agents import (
    _canonicalize_resource_visuals,
    _source_image_text_input,
    _upstream_context,
)
from prism.models import RESOURCE_PRESENTATION


class SourceImageSelectionTests(unittest.TestCase):
    def test_all_document_images_reach_resource_context(self) -> None:
        state = {
            "course": {"unit_name": "UC", "taxonomy_type": "SOLO"},
            "feedback": {},
            "resource_types": [RESOURCE_PRESENTATION],
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
                {
                    "id": "upload-local",
                    "origin_type": "user_uploaded",
                    "source_file": "imagem-local.png",
                    "filename": "imagem-local.png",
                    "media_type": "image/png",
                    "width_px": 800,
                    "height_px": 450,
                },
            ],
            "ai_image_generation_enabled": False,
        }

        context = _upstream_context(state, "resources")

        catalogue = context["source_image_catalogue"]
        self.assertEqual(len(catalogue), 2)
        self.assertEqual(
            [item["id"] for item in catalogue],
            ["document-selected", "document-not-selected"],
        )
        self.assertEqual(catalogue[0]["candidate_kind"], "composite_render")
        self.assertIn("apoio.pdf", catalogue[0]["description"])
        self.assertNotIn("thumbnail_base64", catalogue[0])
        self.assertNotIn("data_base64", catalogue[0])

    def test_document_candidate_is_sent_as_text_without_image_bytes(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (160, 90), (30, 100, 160)).save(
            image_buffer, format="PNG"
        )
        encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        request_input = _source_image_text_input(
            {
                "source_image_catalogue": [
                    {
                        "id": "document-selected",
                        "source_file": "apoio.pdf",
                        "source_location": "Página 2",
                        "media_type": "image/png",
                        "description": "Diagrama da estrutura do conceito.",
                        "thumbnail_media_type": "image/png",
                        "thumbnail_base64": encoded,
                        "data_base64": encoded,
                    }
                ]
            }
        )

        self.assertIsInstance(request_input, str)
        request_payload = json.loads(request_input)
        candidate = request_payload["source_image_catalogue"][0]
        self.assertEqual(candidate["id"], "document-selected")
        self.assertEqual(candidate["description"], "Diagrama da estrutura do conceito.")
        self.assertNotIn("thumbnail_base64", candidate)
        self.assertNotIn("data_base64", candidate)
        self.assertNotIn(encoded, request_input)

    def test_document_candidate_is_not_forced_when_agent_returns_diagram(self) -> None:
        state = {
            "resource_types": [RESOURCE_PRESENTATION],
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
        self.assertEqual(slide["visual_mode"], "diagrama")
        self.assertEqual(slide["visual_asset_id"], "")
        self.assertFalse(any(correction.get("reason") for correction in corrections))

        artifact["presentation_outline"][1].update(
            {
                "visual_mode": "documento",
                "visual_asset_id": "document-selected",
                "visual_prompt": "",
            }
        )
        normalized, _corrections = _canonicalize_resource_visuals(
            deepcopy(artifact), state
        )

        selected_slide = normalized["presentation_outline"][1]
        self.assertEqual(selected_slide["visual_mode"], "documento")
        self.assertEqual(selected_slide["visual_asset_id"], "document-selected")
        self.assertIn("apoio.pdf", selected_slide["visual_source"])
        self.assertIn("Página 5", selected_slide["visual_source"])


if __name__ == "__main__":
    unittest.main()
