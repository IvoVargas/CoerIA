"""Assistência ao preenchimento inicial, sempre sujeita à decisão do docente."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from .agents import AgentGenerationError, DEFAULT_MODEL, supports_reasoning_effort
from .branding import config_value
from .curriculum import validate_taxonomy_choice
from .models import SEMESTER_OPTIONS, validate_semester
from .providers import (
    AI_PROVIDER_IAEDU,
    AI_PROVIDER_OPENAI,
    IAeduResponsesAdapter,
    validate_ai_provider,
)


PROPOSAL_FIELDS = (
    "unit_name",
    "source_text",
    "program_name",
    "program_type",
    "academic_year",
    "semester",
    "cnaef_code",
    "cnaef_name",
    "isced_f_code",
    "isced_f_name",
    "ects_credits",
    "contact_hours",
    "autonomous_hours",
)
NUMERIC_PROPOSAL_FIELDS = {
    "ects_credits",
    "contact_hours",
    "autonomous_hours",
}


def _field_is_empty(field: str, value: Any) -> bool:
    if field in NUMERIC_PROPOSAL_FIELDS:
        try:
            return float(value or 0) <= 0
        except (TypeError, ValueError):
            return True
    return not str(value or "").strip()


def _proposed_value_is_valid(field: str, value: Any) -> bool:
    if _field_is_empty(field, value):
        return False
    if field == "source_text":
        return len(str(value).strip()) >= 40
    if field == "semester":
        return str(value).strip() in SEMESTER_OPTIONS
    return True


def _merge_initial_proposal(
    original: dict[str, Any], proposal: dict[str, Any]
) -> dict[str, Any]:
    """Preenche apenas campos vazios e preserva os dados do docente."""

    merged: dict[str, Any] = {}
    fields_not_completed: list[str] = []
    for field in PROPOSAL_FIELDS:
        original_value = original.get(field)
        if not _field_is_empty(field, original_value):
            merged[field] = original_value
            continue
        proposed_value = proposal.get(field)
        merged[field] = proposed_value
        if not _proposed_value_is_valid(field, proposed_value):
            fields_not_completed.append(
                "source_text (mínimo de 40 caracteres)"
                if field == "source_text"
                else field
            )

    if fields_not_completed:
        raise AgentGenerationError(
            "A IA não conseguiu completar todos os campos vazios: "
            + ", ".join(fields_not_completed)
            + ". Volte a tentar ou forneça mais contexto."
        )
    merged["explanation"] = str(proposal.get("explanation", "")).strip() or (
        "Os campos vazios foram preenchidos com valores provisórios inferidos dos "
        "dados disponíveis."
    )
    return merged


def validate_initial_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Valida e sugere melhorias sem alterar os valores introduzidos."""

    issues: list[str] = []
    suggestions: list[str] = []
    results: list[dict[str, str]] = []

    def add_issue(message: str, target: str) -> None:
        issues.append(message)
        results.append({"kind": "issue", "message": message, "target": target})

    def add_suggestion(message: str, target: str) -> None:
        suggestions.append(message)
        results.append(
            {"kind": "suggestion", "message": message, "target": target}
        )

    unit_name = str(data.get("unit_name", "") or "").strip()
    source_text = str(data.get("source_text", "") or "").strip()
    bibliography = str(data.get("bibliography", "") or "").strip()

    if not unit_name:
        add_issue(
            "Indique o nome da unidade curricular ou ação de formação.",
            "unit_name",
        )
    if len(source_text) < 40:
        add_issue(
            "Acrescente informação de referência com pelo menos 40 caracteres.",
            "source_text",
        )
    if not str(data.get("program_type", "") or "").strip():
        add_suggestion(
            "Indique o tipo de formação para melhorar o enquadramento.",
            "program_type",
        )
    try:
        duration = float(data.get("duration_hours", 0) or 0)
        if duration <= 0:
            raise ValueError
    except (TypeError, ValueError):
        add_issue(
            "A soma das horas de contacto e do trabalho autónomo deve ser "
            "superior a zero.",
            "duration_hours",
        )
    try:
        validate_taxonomy_choice(str(data.get("taxonomy_type", "")))
    except ValueError as error:
        add_issue(str(error), "taxonomy_type")
    try:
        validate_semester(str(data.get("semester", "") or ""))
    except ValueError as error:
        add_issue(str(error), "semester")
    if not bibliography:
        add_suggestion(
            "Acrescente bibliografia fornecida ou validada pelo docente antes da exportação final.",
            "bibliography",
        )
    if not str(data.get("program_name", "") or "").strip():
        add_suggestion(
            "O curso ou formação é opcional, mas melhora o enquadramento.",
            "program_name",
        )

    return {
        "valid": not issues,
        "issues": issues,
        "suggestions": suggestions,
        "results": results,
    }


class OpenAIInitialFormAssistant:
    """Gera uma proposta inicial editável sem iniciar a sessão pedagógica."""

    def __init__(
        self,
        model: str | None = None,
        *,
        client_factory: Callable[[], Any] | None = None,
        provider_name: str = "OpenAI",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model or config_value("OPENAI_MODEL", DEFAULT_MODEL)
        self.timeout_seconds = float(config_value("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(config_value("OPENAI_MAX_RETRIES", "2"))
        self.max_output_tokens = int(
            config_value("OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS", "2500")
        )
        self.validation_retries = max(
            0, int(config_value("OPENAI_VALIDATION_RETRIES", "2"))
        )
        self.client_factory = client_factory
        self.provider_name = provider_name
        self.api_key_env = api_key_env

    def propose(self, data: dict[str, Any]) -> dict[str, Any]:
        if not os.getenv(self.api_key_env):
            raise AgentGenerationError(
                f"A proposta inicial por {self.provider_name} requer {self.api_key_env}."
            )
        OpenAI = None
        if self.client_factory is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise AgentGenerationError(
                    "A biblioteca OpenAI não está instalada."
                ) from error

        taxonomy_type = validate_taxonomy_choice(
            str(data.get("taxonomy_type", "SOLO"))
        )
        empty_fields = [
            field for field in PROPOSAL_FIELDS
            if _field_is_empty(field, data.get(field))
        ]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "unit_name": {"type": "string"},
                "source_text": {"type": "string"},
                "program_name": {"type": "string"},
                "program_type": {"type": "string"},
                "academic_year": {"type": "string"},
                "semester": {"type": "string", "enum": list(SEMESTER_OPTIONS)},
                "cnaef_code": {"type": "string"},
                "cnaef_name": {"type": "string"},
                "isced_f_code": {"type": "string"},
                "isced_f_name": {"type": "string"},
                "ects_credits": {"type": "number"},
                "contact_hours": {"type": "number"},
                "autonomous_hours": {"type": "number"},
                "explanation": {"type": "string"},
            },
            "required": [
                "unit_name",
                "source_text",
                "program_name",
                "program_type",
                "academic_year",
                "semester",
                "cnaef_code",
                "cnaef_name",
                "isced_f_code",
                "isced_f_name",
                "ects_credits",
                "contact_hours",
                "autonomous_hours",
                "explanation",
            ],
        }
        instructions = (
            "És um assistente de preenchimento de unidades curriculares. Responde em "
            "português europeu e completa uma proposta inicial a partir dos dados "
            "fornecidos. Preserva literalmente todos os campos que já tenham conteúdo. "
            "Preenche TODOS os campos indicados em fields_to_complete com valores "
            "concretos, coerentes e editáveis; não devolvas strings vazias nem valores "
            "numéricos iguais a zero. Quando source_text estiver em fields_to_complete, "
            "cria uma proposta estruturada de informação de referência com pelo menos "
            "200 caracteres; nunca devolvas apenas um título ou uma frase curta. "
            "Código e designação CNAEF, código e designação ISCED-F 2013, ECTS e "
            "horas podem ser estimativas provisórias, mas a explanation deve "
            "identificá-los claramente como dados a confirmar. No ISCED-F, prefere o "
            "código de área detalhada com quatro dígitos quando o contexto o permitir. "
            "Para semester, usa exatamente '1.º semestre' ou '2.º semestre'. "
            "A proposta será revista e aprovada pelo docente antes de ser usada. "
            f"A taxonomia escolhida é exclusivamente {taxonomy_type} e não deve ser "
            "alterada."
        )
        try:
            client = (
                self.client_factory()
                if self.client_factory is not None
                else OpenAI(
                    timeout=self.timeout_seconds,
                    max_retries=self.max_retries,
                )
            )
        except Exception as error:
            raise AgentGenerationError(
                f"Não foi possível gerar a proposta inicial. {error}"
            ) from error

        attempts = self.validation_retries + 1
        request_context: dict[str, Any] = {
            "current_fields": data,
            "fields_to_complete": empty_fields,
        }
        previous_proposal: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                request_options: dict[str, Any] = {
                    "model": self.model,
                    "instructions": instructions,
                    "input": json.dumps(request_context, ensure_ascii=False),
                    "max_output_tokens": self.max_output_tokens,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "coeria_initial_form",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                }
                if supports_reasoning_effort(self.model):
                    request_options["reasoning"] = {"effort": "low"}
                response = client.responses.create(**request_options)
                proposal = json.loads(response.output_text)
                previous_proposal = proposal
                merged = _merge_initial_proposal(data, proposal)
            except (AgentGenerationError, json.JSONDecodeError, KeyError, TypeError) as error:
                if attempt == attempts:
                    raise AgentGenerationError(
                        f"{error} A proposta foi repetida automaticamente {attempts} "
                        "vezes sem completar um formulário válido."
                    ) from error
                request_context = {
                    "current_fields": data,
                    "fields_to_complete": empty_fields,
                    "previous_proposal": previous_proposal,
                    "automatic_validation_feedback": str(error),
                    "instruction": (
                        "Corrige a proposta anterior e completa novamente todos os "
                        "campos indicados, respeitando os mínimos pedidos."
                    ),
                }
                continue
            except Exception as error:
                raise AgentGenerationError(
                    f"Não foi possível gerar a proposta inicial. {error}"
                ) from error

            merged["taxonomy_type"] = taxonomy_type
            return merged

        raise AgentGenerationError("Não foi possível gerar uma proposta inicial válida.")


class IAeduInitialFormAssistant(OpenAIInitialFormAssistant):
    """Preenchimento inicial através do agente IAedu selecionado."""

    def __init__(self) -> None:
        super().__init__(
            model=config_value("IAEDU_AGENT_NAME", "Agente IAedu"),
            client_factory=IAeduResponsesAdapter,
            provider_name="IAedu",
            api_key_env="IAEDU_API_KEY",
        )


def build_initial_form_assistant(provider: str | None) -> OpenAIInitialFormAssistant:
    selected = validate_ai_provider(provider)
    if selected == AI_PROVIDER_IAEDU:
        return IAeduInitialFormAssistant()
    if selected == AI_PROVIDER_OPENAI:
        return OpenAIInitialFormAssistant()
    raise AgentGenerationError("Fornecedor de IA não suportado.")
