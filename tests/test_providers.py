import json
import unittest
from os import environ
from unittest.mock import patch

from prism.agents import IAeduPedagogicalAgent, build_pedagogical_team
from prism.assistance import IAeduInitialFormAssistant, build_initial_form_assistant
from prism.providers import (
    AI_PROVIDER_IAEDU,
    IAeduResponsesAdapter,
    IAeduStreamingClient,
    _extract_json_object,
    validate_ai_provider,
)


class ProviderTests(unittest.TestCase):
    def test_provider_choice_is_normalized_and_validated(self) -> None:
        self.assertEqual(validate_ai_provider("iaEDU"), "IAedu")
        self.assertEqual(validate_ai_provider("openai"), "OpenAI")
        with self.assertRaises(ValueError):
            validate_ai_provider("outro")

    def test_iaedu_json_can_be_extracted_from_markdown_or_prose(self) -> None:
        self.assertEqual(
            json.loads(_extract_json_object('```json\n{"artifact": []}\n```')),
            {"artifact": []},
        )
        self.assertEqual(
            json.loads(_extract_json_object('Resposta: {"passed": true}.')),
            {"passed": True},
        )

    def test_streaming_client_sends_required_multipart_fields_and_joins_tokens(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self):
                return iter([
                    b'{"type":"token","content":"{\\"artifact\\":"}',
                    b'{"type":"token","content":"[]}"}',
                    b'{"type":"done"}',
                ])

        client = IAeduStreamingClient(
            endpoint="https://example.invalid/stream",
            api_key="test-secret",
            channel_id="test-channel",
            thread_id="test-thread",
            max_retries=0,
        )
        with patch("requests.post", return_value=FakeResponse()) as post:
            result = client.complete("Pedido de teste")

        self.assertEqual(json.loads(result), {"artifact": []})
        call = post.call_args
        self.assertEqual(call.kwargs["headers"], {"x-api-key": "test-secret"})
        self.assertNotIn("Content-Type", call.kwargs["headers"])
        self.assertEqual(call.kwargs["files"]["channel_id"], (None, "test-channel"))
        self.assertEqual(call.kwargs["files"]["thread_id"], (None, "test-thread"))
        self.assertEqual(call.kwargs["files"]["message"], (None, "Pedido de teste"))
        self.assertIn("user_info", call.kwargs["files"])

    def test_responses_adapter_preserves_the_structured_interface(self) -> None:
        class FakeClient:
            def complete(self, message: str) -> str:
                self.message = message
                return '```json\n{"artifact": [{"id": "C1"}]}\n```'

        fake_client = FakeClient()
        adapter = IAeduResponsesAdapter(fake_client)
        response = adapter.responses.create(
            model="ignored",
            instructions="Instruções",
            input='{"course": {}}',
            text={"format": {"schema": {"type": "object"}}},
        )

        self.assertEqual(
            json.loads(response.output_text),
            {"artifact": [{"id": "C1"}]},
        )
        self.assertIn("Esquema JSON obrigatório", fake_client.message)
        self.assertEqual(response.usage.total_tokens, 0)

    def test_iaedu_factories_select_the_same_provider_for_all_agents(self) -> None:
        team = build_pedagogical_team(AI_PROVIDER_IAEDU)
        assistant = build_initial_form_assistant(AI_PROVIDER_IAEDU)

        self.assertIsInstance(team.generator, IAeduPedagogicalAgent)
        self.assertEqual(team.critic.api_key_env, "IAEDU_API_KEY")
        self.assertIsInstance(assistant, IAeduInitialFormAssistant)

    def test_iaedu_key_is_read_only_from_the_environment(self) -> None:
        with patch.dict(environ, {"IAEDU_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "IAEDU_API_KEY"):
                IAeduStreamingClient.from_environment()


if __name__ == "__main__":
    unittest.main()
