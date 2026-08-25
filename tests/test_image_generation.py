import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from io import BytesIO

from prism.image_generation import (
    OpenAIImageGenerator,
    build_image_prompt,
    build_uploaded_image_asset,
    enrich_presentation_with_ai_images,
    manual_editor_image_count,
    suggest_image_prompt,
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


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"prompt":"Representar um percurso visual com três objetos '
                'interligados, composição horizontal e sem texto."}'
            )
        )


class _FakePromptClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


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
        self.assertEqual(asset["image_mode"], "RGB")
        self.assertTrue(asset["thumbnail_base64"])
        self.assertEqual(asset["width_px"], 320)
        self.assertEqual(asset["height_px"], 180)
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

    def test_invalid_generated_bytes_fall_back_with_explicit_warning(self) -> None:
        encoded = base64.b64encode(b"isto-nao-e-uma-imagem").decode("ascii")
        fake_client = _FakeClient(encoded)
        generator = OpenAIImageGenerator(
            model="gpt-image-test",
            client_factory=lambda: fake_client,
        )
        artifact, assets, records = enrich_presentation_with_ai_images(
            self._state(),
            self._artifact(),
            generator=generator,
        )

        self.assertEqual(assets, [])
        self.assertEqual(records[0]["status"], "failed")
        slide = artifact["presentation_outline"][1]
        self.assertEqual(slide["visual_mode"], "diagrama")
        self.assertEqual(slide["visual_asset_id"], "")
        self.assertIn("Fallback para diagrama", slide["visual_warning"])
        self.assertIn("Pillow", slide["visual_warning"])

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

    def test_prompt_suggestion_uses_the_current_slide_context(self) -> None:
        fake_client = _FakePromptClient()
        state = self._state()
        state["ai_provider"] = "OpenAI"

        suggestion = suggest_image_prompt(
            state,
            self._artifact()["presentation_outline"][1],
            2,
            client_factory=lambda: fake_client,
        )

        self.assertIn("três objetos", suggestion)
        request = fake_client.responses.calls[0]
        self.assertIn("Conceito", request["input"])
        self.assertIn("RA1", request["input"])

    def test_uploaded_image_is_normalized_and_keeps_local_provenance(self) -> None:
        raw = base64.b64decode(self._encoded_png())

        asset = build_uploaded_image_asset(raw, "figura-local.png")

        self.assertEqual(asset["origin_type"], "user_uploaded")
        self.assertEqual(asset["source_file"], "figura-local.png")
        self.assertTrue(asset["data_base64"])
        self.assertTrue(asset["thumbnail_base64"])
        self.assertFalse(asset["approved"])

    def test_only_manual_editor_generations_count_towards_extra_limit(self) -> None:
        state = {
            "generated_images": [
                {"id": "automatic", "origin_type": "ai_generated"},
                {
                    "id": "manual-1",
                    "origin_type": "ai_generated",
                    "generation_mode": "manual_editor",
                },
            ]
        }

        self.assertEqual(manual_editor_image_count(state), 1)


if __name__ == "__main__":
    unittest.main()
