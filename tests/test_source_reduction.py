import json
import unittest
from os import environ
from types import SimpleNamespace
from unittest.mock import patch

from prism.source_reduction import reduce_source_text


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["input"])
        text = payload["text"]
        # Mantém uma pequena amostra identificável de cada bloco para provar
        # que a redução percorre todos os fragmentos em vez de truncar o fim.
        marker = text[:80].replace("\n", " ").strip()
        return SimpleNamespace(
            output_text=json.dumps(
                {"items": [f"Informação curricular preservada: {marker}"]},
                ensure_ascii=False,
            ),
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


class SourceReductionTests(unittest.TestCase):
    def test_short_source_is_not_sent_to_ai(self) -> None:
        with patch.dict(environ, {"COERIA_MAX_SOURCE_CHARS": "1000"}, clear=False):
            result = reduce_source_text("Conteúdo curricular suficientemente curto.", provider="OpenAI")

        self.assertFalse(result.metadata["applied"])
        self.assertEqual(result.text, "Conteúdo curricular suficientemente curto.")

    def test_large_source_is_reduced_in_multiple_chunks_with_metadata(self) -> None:
        client = _FakeClient()
        source = (
            "[Ficheiro: programa.pdf]\n" + "Tópico A e conteúdo detalhado. " * 180 +
            "\n\n[Ficheiro: manual.docx]\n" + "Tópico B e procedimento relevante. " * 180
        )
        with (
            patch.dict(
                environ,
                {
                    "COERIA_MAX_SOURCE_CHARS": "1800",
                    "COERIA_SOURCE_REDUCTION_CHUNK_CHARS": "1200",
                    "COERIA_SOURCE_REDUCTION_MAX_PASSES": "3",
                },
                clear=False,
            ),
            patch(
                "prism.source_reduction._provider_client",
                return_value=(client, "gpt-4o-mini", "OpenAI"),
            ),
        ):
            result = reduce_source_text(source, provider="OpenAI")

        self.assertTrue(result.metadata["applied"])
        self.assertLessEqual(len(result.text), 1800)
        self.assertGreater(len(client.responses.calls), 1)
        self.assertEqual(result.metadata["provider"], "OpenAI")
        self.assertEqual(result.metadata["model"], "gpt-4o-mini")
        self.assertEqual(result.metadata["total_tokens"], 15 * len(client.responses.calls))
        self.assertIn("Fonte reduzida", result.text)
        self.assertEqual(
            [item["source"] for item in result.metadata["sources"]],
            ["Ficheiro: programa.pdf", "Ficheiro: manual.docx"],
        )
        self.assertTrue(
            all(item["original_chars"] > 0 for item in result.metadata["sources"])
        )
        self.assertTrue(
            all(item["initial_chunks"] >= 1 for item in result.metadata["sources"])
        )

    def test_reduced_markers_keep_source_identity_across_multiple_passes(self) -> None:
        client = _FakeClient()
        source = (
            "[Ficheiro: fonte-a.pdf]\n" + "Modelo Mayer multimédia. " * 120
            + "\n\n[Ficheiro: fonte-b.pdf]\n" + "Carga cognitiva Sweller. " * 120
        )
        with (
            patch.dict(
                environ,
                {
                    "COERIA_MAX_SOURCE_CHARS": "250",
                    "COERIA_SOURCE_REDUCTION_CHUNK_CHARS": "500",
                    "COERIA_SOURCE_REDUCTION_MAX_PASSES": "3",
                },
                clear=False,
            ),
            patch(
                "prism.source_reduction._provider_client",
                return_value=(client, "gpt-4o-mini", "OpenAI"),
            ),
        ):
            try:
                result = reduce_source_text(source, provider="OpenAI")
            except Exception:
                # O fake pode não comprimir o suficiente para o limite minúsculo;
                # interessa-nos garantir que todas as chamadas continuam etiquetadas.
                result = None

        labels = [
            json.loads(call["input"])["source"]
            for call in client.responses.calls
        ]
        self.assertIn("Ficheiro: fonte-a.pdf", labels)
        self.assertIn("Ficheiro: fonte-b.pdf", labels)
        self.assertNotIn("Fonte documental", labels)
        if result is not None:
            self.assertEqual(len(result.metadata["sources"]), 2)


if __name__ == "__main__":
    unittest.main()
