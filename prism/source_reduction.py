"""Redução automática de fontes extensas antes do fluxo pedagógico.

A redução é deliberadamente separada da análise curricular: serve apenas para
colocar documentos extensos dentro do orçamento de contexto do modelo sem
obrigar o docente a cortar ficheiros manualmente. O texto reduzido conserva a
proveniência por bloco e não deve introduzir factos ausentes das fontes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from .branding import config_value
from .ingestion import DEFAULT_MAX_SOURCE_CHARS
from .providers import (
    AI_PROVIDER_IAEDU,
    AI_PROVIDER_OPENAI,
    IAeduResponsesAdapter,
    validate_ai_provider,
)

DEFAULT_REDUCTION_CHUNK_CHARS = 80_000
DEFAULT_REDUCTION_MAX_OUTPUT_TOKENS = 2_200
DEFAULT_REDUCTION_MAX_PASSES = 3
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

ProgressCallback = Callable[[str], None]


class SourceReductionError(ValueError):
    """Erro compreensível durante a redução de fontes extensas."""


@dataclass(frozen=True)
class SourceReductionResult:
    text: str
    metadata: dict[str, Any]


def _positive_int(suffix: str, default: int) -> int:
    raw = config_value(suffix, str(default))
    name = f"COERIA_{suffix}"
    try:
        value = int(raw)
    except ValueError as error:
        raise SourceReductionError(f"A variável {name} deve ser um número inteiro.") from error
    if value <= 0:
        raise SourceReductionError(f"A variável {name} deve ser superior a zero.")
    return value


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    """Divide texto por parágrafos sem produzir blocos acima do limite."""

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    def flush() -> None:
        nonlocal current, current_size
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            flush()
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars])
                start += max_chars
            continue
        extra = len(paragraph) + (2 if current else 0)
        if current and current_size + extra > max_chars:
            flush()
        current.append(paragraph)
        current_size += len(paragraph) + (2 if len(current) > 1 else 0)
    flush()
    return chunks or [text[:max_chars]]


def _source_sections(text: str) -> list[tuple[str, str]]:
    """Recupera etiquetas de proveniência originais ou já reduzidas."""

    marker = re.compile(
        r"(?m)^\[(?P<label>Texto introduzido pelo docente|Ficheiro: [^\]]+|"
        r"Fonte reduzida: [^\]]+)\]\s*$"
    )
    matches = list(marker.finditer(text))
    if not matches:
        return [("Fonte documental", text.strip())]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        label = match.group("label")
        if label.startswith("Fonte reduzida: "):
            label = label[len("Fonte reduzida: ") :]
            label = re.sub(r"\s+— bloco \d+/\d+$", "", label).strip()
        sections.append((label, body))
    return sections or [("Fonte documental", text.strip())]


def _source_stats(text: str, chunk_chars: int) -> list[dict[str, Any]]:
    """Resume a representatividade documental antes da redução."""

    stats: list[dict[str, Any]] = []
    for label, body in _source_sections(text):
        stats.append(
            {
                "source": label,
                "original_chars": len(body),
                "initial_chunks": len(_split_paragraphs(body, chunk_chars)),
            }
        )
    return stats


def _build_chunks(text: str, max_chars: int) -> list[tuple[str, int, int, str]]:
    chunks: list[tuple[str, int, int, str]] = []
    for label, body in _source_sections(text):
        parts = _split_paragraphs(body, max_chars)
        total = len(parts)
        for index, part in enumerate(parts, start=1):
            chunks.append((label, index, total, part))
    return chunks


def _provider_client(provider: str) -> tuple[Any, str, str]:
    selected = validate_ai_provider(provider)
    if selected == AI_PROVIDER_IAEDU:
        if not os.getenv("IAEDU_API_KEY"):
            raise SourceReductionError(
                "As fontes são extensas e precisam de redução automática, mas "
                "IAEDU_API_KEY não está disponível."
            )
        return (
            IAeduResponsesAdapter(),
            config_value("IAEDU_AGENT_NAME", "Agente IAedu"),
            "IAedu Agent Chat API",
        )

    if selected == AI_PROVIDER_OPENAI:
        if not os.getenv("OPENAI_API_KEY"):
            raise SourceReductionError(
                "As fontes são extensas e precisam de redução automática, mas "
                "OPENAI_API_KEY não está disponível."
            )
        try:
            from openai import OpenAI
        except ImportError as error:
            raise SourceReductionError(
                "A redução automática de fontes requer a biblioteca OpenAI."
            ) from error
        client = OpenAI(
            timeout=float(config_value("OPENAI_TIMEOUT_SECONDS", "120")),
            max_retries=int(config_value("OPENAI_MAX_RETRIES", "2")),
        )
        return (
            client,
            config_value("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            "OpenAI",
        )

    raise SourceReductionError("Fornecedor de IA não suportado para redução de fontes.")


def _reduce_chunk(
    *,
    client: Any,
    model: str,
    source_label: str,
    chunk_index: int,
    chunk_total: int,
    text: str,
    max_output_tokens: int,
) -> tuple[list[str], dict[str, int]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["items"],
    }
    instructions = (
        "És um extrator fiel de informação curricular. Resume este fragmento para uso "
        "posterior numa análise curricular, privilegiando COBERTURA sobre estilo. Extrai "
        "tópicos e subtópicos, conceitos, definições, métodos, procedimentos, exemplos "
        "pedagogicamente relevantes, objetivos, requisitos, critérios e outras restrições "
        "presentes no fragmento. Preserva explicitamente conceitos distintivos, nomes de "
        "modelos, teorias, princípios, autores ou frameworks que apareçam na fonte; não os "
        "elimines apenas por não coincidirem com uma ficha curricular curta. Mantém "
        "terminologia técnica e relações importantes. Não inventes, não completes lacunas "
        "e não introduzas conhecimento externo. Cada item deve ser autónomo, específico e "
        "conciso; elimina apenas redundância, texto administrativo irrelevante e repetição. "
        "Responde em português europeu."
    )
    input_payload = {
        "source": source_label,
        "block": f"{chunk_index}/{chunk_total}",
        "text": text,
    }
    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=json.dumps(input_payload, ensure_ascii=False),
            max_output_tokens=max_output_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "coeria_source_reduction",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        payload = json.loads(response.output_text)
    except Exception as error:
        raise SourceReductionError(
            f"Não foi possível reduzir automaticamente as fontes extensas. {error}"
        ) from error

    raw_items = payload.get("items", [])
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items if isinstance(raw_items, list) else []:
        clean = re.sub(r"\s+", " ", str(item)).strip(" -•\t")
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            items.append(clean)
    if not items:
        raise SourceReductionError(
            "A redução automática terminou sem informação curricular utilizável."
        )

    usage = getattr(response, "usage", None)
    return items, {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def reduce_source_text(
    text: str,
    *,
    provider: str,
    progress_callback: ProgressCallback | None = None,
    allow_ai: bool = True,
) -> SourceReductionResult:
    """Reduz fontes acima do orçamento de contexto e devolve metadados auditáveis."""

    source = (text or "").strip()
    target_chars = _positive_int("MAX_SOURCE_CHARS", DEFAULT_MAX_SOURCE_CHARS)
    configured_chunk_chars = _positive_int(
        "SOURCE_REDUCTION_CHUNK_CHARS", DEFAULT_REDUCTION_CHUNK_CHARS
    )
    initial_sources = _source_stats(source, configured_chunk_chars)
    if len(source) <= target_chars:
        return SourceReductionResult(
            source,
            {
                "applied": False,
                "original_chars": len(source),
                "effective_chars": len(source),
                "target_chars": target_chars,
                "provider": "",
                "model": "",
                "passes": 0,
                "chunks": 0,
                "sources": initial_sources,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        )

    if not allow_ai:
        return SourceReductionResult(
            source,
            {
                "applied": False,
                "deferred": True,
                "reason": "Autoria manual; nenhuma redução por IA foi executada.",
                "original_chars": len(source),
                "effective_chars": len(source),
                "target_chars": target_chars,
                "provider": "",
                "model": "",
                "passes": 0,
                "chunks": 0,
                "sources": initial_sources,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        )

    chunk_chars = configured_chunk_chars
    max_output_tokens = _positive_int(
        "SOURCE_REDUCTION_MAX_OUTPUT_TOKENS",
        DEFAULT_REDUCTION_MAX_OUTPUT_TOKENS,
    )
    max_passes = _positive_int(
        "SOURCE_REDUCTION_MAX_PASSES", DEFAULT_REDUCTION_MAX_PASSES
    )
    sources = _source_stats(source, chunk_chars)
    client, model, provider_name = _provider_client(provider)
    original_chars = len(source)
    working = source
    total_chunks = 0
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    started_at = perf_counter()

    for pass_index in range(1, max_passes + 1):
        chunks = _build_chunks(working, chunk_chars)
        reduced_parts: list[str] = []
        for global_index, (label, index, total, chunk) in enumerate(chunks, start=1):
            if progress_callback is not None:
                progress_callback(
                    "A reduzir fontes extensas com IA "
                    f"(passagem {pass_index}, bloco {global_index}/{len(chunks)})…"
                )
            items, usage = _reduce_chunk(
                client=client,
                model=model,
                source_label=label,
                chunk_index=index,
                chunk_total=total,
                text=chunk,
                max_output_tokens=max_output_tokens,
            )
            total_chunks += 1
            for key in totals:
                totals[key] += usage[key]
            block_label = (
                f"[Fonte reduzida: {label} — bloco {index}/{total}]"
                if total > 1
                else f"[Fonte reduzida: {label}]"
            )
            reduced_parts.append(
                block_label + "\n" + "\n".join(f"- {item}" for item in items)
            )

        reduced = "\n\n".join(reduced_parts).strip()
        if not reduced or len(reduced) >= len(working):
            raise SourceReductionError(
                "A redução automática não conseguiu diminuir as fontes de forma segura. "
                "Remova documentos redundantes ou aumente COERIA_MAX_SOURCE_CHARS."
            )
        working = reduced
        if len(working) <= target_chars:
            return SourceReductionResult(
                working,
                {
                    "applied": True,
                    "original_chars": original_chars,
                    "effective_chars": len(working),
                    "target_chars": target_chars,
                    "provider": provider_name,
                    "model": model,
                    "passes": pass_index,
                    "chunks": total_chunks,
                    "sources": sources,
                    **totals,
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                },
            )

    raise SourceReductionError(
        f"As fontes foram reduzidas de {original_chars:,} para {len(working):,} caracteres, "
        f"mas continuam acima do limite de {target_chars:,}. Remova documentos redundantes "
        "ou ajuste COERIA_MAX_SOURCE_CHARS."
    )
