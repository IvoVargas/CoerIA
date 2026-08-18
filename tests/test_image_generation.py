import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from io import BytesIO

from prism.image_generation import (
    OpenAIImageGenerator,
    build_image_prompt,
    enrich_presentation_with_ai_images,
)


class _FakeImages:
    def __init__(self, encoded: str) -> None:
        self.encoded = encoded
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=self.encoded)]
        )


class _FakeClient:
    def __init__(self, encoded: str) -> None:
        self.images = _FakeImages(encoded)


class ImageGenerationTests(unittest.TestCase):
    def _encoded_png(self) -> str:
        buffer = BytesIO()
        Image.new("RGB", (320, 180), (30, 90, 150)).save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _state(self):
        return {
            "course": {
                "unit_name": "Programação Aplicada",
                "audience": "Licenciatura",
            },
            "ai_image_generation_enabled": True,
        }

    def _artifact(self):
        return {
            "presentation_outline": [
                {
                    "title": "Capa",
                    "outcome_id": "",
                    "visual_mode": "diagrama",
                    "visual_asset_id": "",
                    "visual_prompt": "",
                    "visual_title": "Percurso",
                    "visual_items": ["A", "B"],
                    "visual_source": "Diagrama nativo.",
                    "alt_text": "Diagrama de capa.",
                },
                {
                    "title": "Conceito",
                    "outcome_id": "RA1",
                    "visual_mode": "ia",
                    "visual_asset_id": "",
                    "visual_prompt": "Representar um processo em três etapas, sem texto.",
                    "visual_title": "Processo principal",
                    "visual_items": ["Entrada", "Transformação", "Resultado"],
                    "visual_source": "Imagem proposta para geração por IA.",
                    "alt_text": "Processo representado visualmente.",
                },
            ]
        }

    def test_prompt_contains_course_and_specific_instruction(self) -> None:
        prompt = build_image_prompt(self._state(), self._artifact()["presentation_outline"][1], 2)
        self.assertIn("Programação Aplicada", prompt)
        self.assertIn("RA1", prompt)
        self.assertIn("Representar um processo", prompt)
        self.assertIn("Evita usar texto", prompt)

    def test_generated_asset_records_provider_model_and_prompt(self) -> None:
        fake_client = _FakeClient(self._encoded_png())
        generator = OpenAIImageGenerator(
            model="gpt-image-test",
            client_factory=lambda: fake_client,
        )
        with patch.dict(
            "os.environ",
            {"COERIA_OPENAI_IMAGE_MAX_PER_PRESENTATION": "2"},
            clear=False,
        ):
            artifact, assets, records = enrich_presentation_with_ai_images(
                self._state(),
                self._artifact(),
                generator=generator,
            )

        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset["origin_type"], "ai_generated")
        self.assertEqual(asset["provider"], "OpenAI Image API")
        self.assertEqual(asset["model"], "gpt-image-test")
        self.assertTrue(asset["prompt"])
        self.assertEqual(asset["size"], "1536x864")
        self.assertEqual(asset["quality"], "low")
        self.assertFalse(asset["approved"])
        slide = artifact["presentation_outline"][1]
        self.assertEqual(slide["visual_mode"], "ia")
        self.assertEqual(slide["visual_asset_id"], asset["id"])
        self.assertEqual(records[0]["status"], "generated")
        call = fake_client.images.calls[0]
        self.assertEqual(call["model"], "gpt-image-test")
        self.assertEqual(call["size"], "1536x864")
        self.assertEqual(call["quality"], "low")
        self.assertEqual(call["output_format"], "png")

    def test_generation_without_authorization_falls_back_to_diagram(self) -> None:
        state = self._state()
        state["ai_image_generation_enabled"] = False
        artifact, assets, records = enrich_presentation_with_ai_images(
            state, self._artifact()
        )
        self.assertEqual(assets, [])
        self.assertEqual(records[0]["status"], "not_authorized")
        slide = artifact["presentation_outline"][1]
        self.assertEqual(slide["visual_mode"], "diagrama")
        self.assertEqual(slide["visual_asset_id"], "")


if __name__ == "__main__":
    unittest.main()
