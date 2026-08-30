import json
import sys
import unittest
from os import environ
from types import SimpleNamespace
from unittest.mock import patch

from prism.assistance import OpenAIInitialFormAssistant, validate_initial_fields
from prism.models import CourseInput, SEMESTER_OPTIONS


class InitialAssistanceTests(unittest.TestCase):
    def test_semester_is_limited_to_the_two_supported_options(self) -> None:
        self.assertEqual(
            SEMESTER_OPTIONS,
            ("1.º semestre", "2.º semestre"),
        )
        with self.assertRaisesRegex(ValueError, "1.º semestre.*2.º semestre"):
            CourseInput.create(
                "Introdução à Programação",
                "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
                semester="Anual",
            )

    def test_initial_validation_rejects_an_unknown_semester(self) -> None:
        result = validate_initial_fields(
            {
                "unit_name": "Introdução à Programação",
                "source_text": (
                    "Algoritmos, variáveis, estruturas de controlo, funções e testes."
                ),
                "audience": "Licenciatura",
                "program_type": "Licenciatura",
                "duration_hours": 18,
                "taxonomy_type": "SOLO",
                "semester": "3.º semestre",
            }
        )

        self.assertFalse(result["valid"])
        self.assertIn("1.º semestre", result["issues"][0])
        self.assertEqual(result["results"][0]["target"], "semester")
        self.assertEqual(result["results"][0]["kind"], "issue")

    def test_semester_cannot_be_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "1.º semestre.*2.º semestre"):
            CourseInput.create(
                "Introdução à Programação",
                "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
                semester="",
            )

    def test_validation_does_not_require_the_api(self) -> None:
        result = validate_initial_fields(
            {
                "unit_name": "Introdução às Pescas",
                "source_text": (
                    "Ecossistemas, técnicas de captura e sustentabilidade dos "
                    "recursos pesqueiros."
                ),
                "audience": "Licenciatura",
                "program_type": "Licenciatura",
                "duration_hours": 18,
                "taxonomy_type": "SOLO",
                "semester": "1.º semestre",
            }
        )
        self.assertTrue(result["valid"])


    def test_gpt_4o_mini_initial_assistance_omits_reasoning_parameter(self) -> None:
        proposal = {
            "unit_name": "Introdução às Pescas",
            "audience": "Licenciatura",
            "duration_hours": 18,
            "source_text": (
                "Ecossistemas aquáticos, técnicas de captura e gestão sustentável "
                "dos recursos pesqueiros em contextos costeiros e oceânicos."
            ),
            "program_name": "Ciências do Mar",
            "program_type": "Licenciatura",
            "academic_year": "1.º ano",
            "semester": "1.º semestre",
            "cnaef_code": "624",
            "cnaef_name": "Pescas",
            "isced_f_code": "0831",
            "isced_f_name": "Pescas",
            "ects_credits": 6,
            "contact_hours": 45,
            "autonomous_hours": 117,
            "explanation": (
                "CNAEF 624 corresponde a Design e ISCED-F 0831 corresponde a "
                "Contabilidade."
            ),
        }

        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=json.dumps(proposal))

        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = OpenAIInitialFormAssistant(
                model="gpt-4o-mini",
                client_factory=lambda: SimpleNamespace(
                    responses=SimpleNamespace(create=create)
                ),
            ).propose({"taxonomy_type": "SOLO"})

        self.assertEqual(result["unit_name"], "Introdução às Pescas")
        self.assertEqual(calls[0]["model"], "gpt-4o-mini")
        self.assertNotIn("reasoning", calls[0])
        proposal_schema = calls[0]["text"]["format"]["schema"]
        self.assertNotIn("audience", proposal_schema["properties"])
        self.assertNotIn("audience", proposal_schema["required"])
        self.assertNotIn("general_aims", proposal_schema["properties"])
        self.assertNotIn("general_aims", proposal_schema["required"])
        self.assertIn("cnaef_code", proposal_schema["properties"])
        self.assertNotIn("cnaef_name", proposal_schema["properties"])
        self.assertIn("cnaef_code", proposal_schema["required"])
        self.assertNotIn("cnaef_name", proposal_schema["required"])
        self.assertIn("481", proposal_schema["properties"]["cnaef_code"]["enum"])
        self.assertIn("isced_f_code", proposal_schema["properties"])
        self.assertNotIn("isced_f_name", proposal_schema["properties"])
        self.assertIn("isced_f_code", proposal_schema["required"])
        self.assertNotIn("isced_f_name", proposal_schema["required"])
        self.assertIn("0613", proposal_schema["properties"]["isced_f_code"]["enum"])
        request_context = json.loads(calls[0]["input"])
        self.assertEqual(request_context["classification_catalogs"]["CNAEF"]["624"], "Pescas")
        self.assertEqual(
            request_context["classification_catalogs"]["ISCED-F 2013"]["0831"],
            "Pescas",
        )
        self.assertIn("CNAEF 624 — Pescas", result["explanation"])
        self.assertIn("ISCED-F 0831 — Pescas", result["explanation"])
        self.assertNotIn(proposal["explanation"], result["explanation"])

    def test_requested_proposal_preserves_the_exclusive_taxonomy(self) -> None:
        proposal = {
            "unit_name": "Introdução às Pescas",
            "audience": "Licenciatura",
            "duration_hours": 18,
            "source_text": (
                "1. Ecossistemas aquáticos. 2. Técnicas de captura. "
                "3. Gestão sustentável dos recursos pesqueiros."
            ),
            "program_name": "Ciências do Mar",
            "program_type": "Licenciatura",
            "academic_year": "1.º ano",
            "semester": "1.º semestre",
            "cnaef_code": "624",
            "cnaef_name": "Pescas",
            "isced_f_code": "0831",
            "isced_f_name": "Pescas",
            "ects_credits": 6,
            "contact_hours": 45,
            "autonomous_hours": 117,
            "explanation": (
                "Proposta baseada nos dados disponíveis; valores institucionais "
                "devem ser confirmados."
            ),
        }

        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(
                responses=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        output_text=json.dumps(proposal)
                    )
                )
            )
        )
        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIInitialFormAssistant().propose(
                {"taxonomy_type": "Bloom", "unit_name": "Introdução às Pescas"}
            )

        self.assertEqual(result["taxonomy_type"], "Bloom")
        self.assertEqual(result["unit_name"], "Introdução às Pescas")
        self.assertTrue(result["source_text"].startswith("1. Ecossistemas"))
        for field in (
            "program_name",
            "program_type",
            "academic_year",
            "semester",
            "cnaef_code",
            "cnaef_name",
            "isced_f_code",
            "isced_f_name",
        ):
            self.assertTrue(result[field])
        for field in (
            "ects_credits",
            "contact_hours",
            "autonomous_hours",
        ):
            self.assertGreater(result[field], 0)

    def test_requested_proposal_only_fills_empty_fields(self) -> None:
        proposal = {
            "unit_name": "Nome proposto pela IA",
            "audience": "Público proposto pela IA",
            "duration_hours": 30,
            "source_text": "Conteúdos programáticos propostos para o campo vazio.",
            "program_name": "Curso proposto",
            "program_type": "Licenciatura",
            "academic_year": "2.º ano",
            "semester": "2.º semestre",
            "cnaef_code": "624",
            "cnaef_name": "Pescas",
            "isced_f_code": "0831",
            "isced_f_name": "Pescas",
            "ects_credits": 6,
            "contact_hours": 45,
            "autonomous_hours": 117,
            "explanation": "Foram preenchidos apenas os campos vazios.",
        }
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(
                responses=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        output_text=json.dumps(proposal)
                    )
                )
            )
        )
        original = {
            "taxonomy_type": "SOLO",
            "unit_name": "Nome introduzido pelo docente",
            "audience": "Público definido pelo docente",
            "duration_hours": 20,
            "source_text": "",
        }

        with patch.dict(environ, {"OPENAI_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIInitialFormAssistant().propose(original)

        self.assertEqual(result["unit_name"], original["unit_name"])
        self.assertNotIn("audience", result)
        self.assertNotIn("duration_hours", result)
        self.assertEqual(result["source_text"], proposal["source_text"])

    def test_short_generated_source_text_is_repaired_automatically(self) -> None:
        valid_proposal = {
            "unit_name": "Introdução à Programação",
            "audience": "Estudantes de licenciatura",
            "duration_hours": 30,
            "source_text": (
                "Fundamentos de algoritmia e programação; tipos de dados, variáveis, "
                "estruturas de controlo, funções, coleções, teste e depuração de "
                "programas através de exercícios progressivos e problemas aplicados."
            ),
            "program_name": "Engenharia Informática",
            "program_type": "Licenciatura",
            "academic_year": "1.º ano",
            "semester": "1.º semestre",
            "cnaef_code": "481",
            "cnaef_name": "Ciências informáticas",
            "isced_f_code": "0613",
            "isced_f_name": "Desenvolvimento e análise de software e aplicações",
            "ects_credits": 6,
            "contact_hours": 60,
            "autonomous_hours": 102,
            "explanation": "Os valores institucionais devem ser confirmados.",
        }
        invalid_proposal = {**valid_proposal, "source_text": "Programação básica."}

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []
                self.proposals = [invalid_proposal, valid_proposal]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps(self.proposals.pop(0))
                )

        fake_responses = FakeResponses()
        fake_module = SimpleNamespace(
            OpenAI=lambda **_kwargs: SimpleNamespace(responses=fake_responses)
        )
        environment = {
            "OPENAI_API_KEY": "test-key",
            "AGIR_SOLO_OPENAI_VALIDATION_RETRIES": "1",
        }
        with patch.dict(environ, environment), patch.dict(
            sys.modules, {"openai": fake_module}
        ):
            result = OpenAIInitialFormAssistant().propose(
                {
                    "taxonomy_type": "SOLO",
                    "unit_name": "Introdução à Programação",
                }
            )

        self.assertGreaterEqual(len(result["source_text"]), 40)
        self.assertEqual(len(fake_responses.calls), 2)
        repair_context = json.loads(fake_responses.calls[1]["input"])
        self.assertIn("mínimo de 40 caracteres", repair_context[
            "automatic_validation_feedback"
        ])


if __name__ == "__main__":
    unittest.main()
