"""Fornecedores de IA e adaptador de streaming do IAedu."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .branding import config_value


AI_PROVIDER_OPENAI = "OpenAI"
AI_PROVIDER_IAEDU = "IAedu"
AI_PROVIDER_CHOICES = (AI_PROVIDER_OPENAI, AI_PROVIDER_IAEDU)

DEFAULT_IAEDU_ENDPOINT = (
    "https://api.iaedu.pt/agent-chat//api/v1/agent/"
    "cmor5objoex9gfp01vm7p95jh/stream"
)
DEFAULT_IAEDU_CHANNEL_ID = "cmr3ugyxf3ahjke0190ik6n4z"


def validate_ai_provider(value: str | None) -> str:
    candidate = str(value or AI_PROVIDER_OPENAI).strip().casefold()
    for provider in AI_PROVIDER_CHOICES:
        if candidate == provider.casefold():
            return provider
    raise ValueError("O fornecedor de IA deve ser OpenAI ou IAedu.")


def configured_ai_provider() -> str:
    return validate_ai_provider(config_value("AI_PROVIDER", AI_PROVIDER_OPENAI))


def _extract_json_object(text: str) -> str:
    """Extrai um objeto JSON de uma resposta eventualmente envolvida em Markdown."""

    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("O IAedu não devolveu um objeto JSON.")
        candidate = candidate[start : end + 1]
        payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("O IAedu não devolveu um objeto JSON na raiz.")
    return json.dumps(payload, ensure_ascii=False)


@dataclass(slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class StructuredProviderResponse:
    output_text: str
    id: str
    usage: ProviderUsage


class IAeduStreamingClient:
    """Cliente mínimo para o endpoint multipart com tokens JSON por linha."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        channel_id: str,
        timeout_seconds: float = 120,
        max_retries: int = 2,
        thread_id: str | None = None,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.channel_id = channel_id.strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.thread_id = thread_id or str(uuid4())
        if not self.endpoint or not self.api_key or not self.channel_id:
            raise ValueError(
                "A configuração IAedu requer endpoint, API key e channel ID."
            )

    @classmethod
    def from_environment(cls) -> "IAeduStreamingClient":
        api_key = os.getenv("IAEDU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "IAEDU_API_KEY não está disponível. Configure-a como variável de "
                "ambiente do utilizador e reinicie a aplicação."
            )
        return cls(
            endpoint=config_value("IAEDU_ENDPOINT", DEFAULT_IAEDU_ENDPOINT),
            api_key=api_key,
            channel_id=config_value("IAEDU_CHANNEL_ID", DEFAULT_IAEDU_CHANNEL_ID),
            timeout_seconds=float(config_value("IAEDU_TIMEOUT_SECONDS", "120")),
            max_retries=int(config_value("IAEDU_MAX_RETRIES", "2")),
        )

    def complete(self, message: str) -> str:
        try:
            import requests
        except ImportError as error:
            raise RuntimeError(
                "A integração IAedu requer a biblioteca requests."
            ) from error

        files = {
            "channel_id": (None, self.channel_id),
            "thread_id": (None, self.thread_id),
            "user_info": (None, json.dumps({"application": "CoerIA"})),
            "message": (None, message),
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with requests.post(
                    self.endpoint,
                    headers={"x-api-key": self.api_key},
                    files=files,
                    stream=True,
                    timeout=(10, self.timeout_seconds),
                ) as response:
                    response.raise_for_status()
                    tokens: list[str] = []
                    api_errors: list[str] = []
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if event.get("type") == "token" and "content" in event:
                            tokens.append(str(event["content"]))
                        elif event.get("type") in {"error", "failed"}:
                            api_errors.append(str(event.get("content", event)))
                    if api_errors:
                        raise RuntimeError("; ".join(api_errors))
                    content = "".join(tokens).strip()
                    if not content:
                        raise RuntimeError("O IAedu terminou sem devolver conteúdo.")
                    return content
            except Exception as error:
                last_error = error
                if attempt == self.max_retries:
                    break
        raise RuntimeError(f"Falha na comunicação com o IAedu: {last_error}")


class IAeduResponsesAdapter:
    """Expõe a interface mínima usada pelo pipeline estruturado existente."""

    def __init__(self, client: IAeduStreamingClient | None = None) -> None:
        self.client = client or IAeduStreamingClient.from_environment()
        self.responses = self

    def create(
        self,
        *,
        instructions: str,
        input: str,
        text: dict[str, Any],
        **_kwargs: Any,
    ) -> StructuredProviderResponse:
        response_format = text.get("format", {})
        schema = response_format.get("schema", {})
        message = (
            f"{instructions}\n\n"
            "Responde apenas com JSON válido, sem Markdown nem texto adicional.\n"
            "Esquema JSON obrigatório:\n"
            f"{json.dumps(schema, ensure_ascii=False)}\n\n"
            "Dados de entrada:\n"
            f"{input}"
        )
        content = self.client.complete(message)
        return StructuredProviderResponse(
            output_text=_extract_json_object(content),
            id=f"iaedu-{uuid4()}",
            usage=ProviderUsage(),
        )
