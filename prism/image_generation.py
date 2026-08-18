"""Geração controlada de imagens educativas para apresentações CoerIA."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from .branding import APP_NAME, config_value


DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1536x864"
DEFAULT_IMAGE_QUALITY = "low"
DEFAULT_MAX_IMAGES_PER_PRESENTATION = 2


class ImageGenerationError(RuntimeError):
    """Erro compreensível durante a geração de uma imagem por IA."""


def image_generation_enabled(state: dict[str, Any]) -> bool:
    return bool(state.get("ai_image_generation_enabled"))


def configured_max_images() -> int:
    try:
        return max(
            0,
            int(
                config_value(
                    "OPENAI_IMAGE_MAX_PER_PRESENTATION",
                    str(DEFAULT_MAX_IMAGES_PER_PRESENTATION),
                )
            ),
        )
    except (TypeError, ValueError):
        return DEFAULT_MAX_IMAGES_PER_PRESENTATION


def build_image_prompt(
    state: dict[str, Any],
    slide: dict[str, Any],
    slide_number: int,
) -> str:
    """Constrói a instrução final enviada ao modelo de imagem."""

    course = state.get("course", {})
    unit_name = str(course.get("unit_name", "unidade curricular")).strip()
    audience = str(course.get("audience", "ensino superior")).strip()
    title = str(slide.get("visual_title") or slide.get("title") or "").strip()
    items = [
        str(item).strip()
        for item in slide.get("visual_items", [])
        if str(item).strip()
    ]
    requested = str(slide.get("visual_prompt", "")).strip()
    outcome_id = str(slide.get("outcome_id", "")).strip()

    parts = [
        f"Cria uma ilustração educativa horizontal 16:9 para o slide {slide_number} "
        f"da unidade curricular «{unit_name}», destinada a {audience}.",
        "A imagem deve apoiar a compreensão pedagógica do conteúdo, ser sóbria, "
        "profissional e adequada ao ensino superior.",
        "Não incluas logótipos, marcas de água, interfaces, texto corrido, legendas "
        "longas nem informação factual que não esteja indicada na instrução.",
        "Evita usar texto dentro da própria imagem; privilegia representação visual, "
        "objetos, relações, processos ou metáforas visuais claras.",
    ]
    if outcome_id:
        parts.append(f"Resultado de aprendizagem associado: {outcome_id}.")
    if title:
        parts.append(f"Finalidade visual: {title}.")
    if items:
        parts.append("Elementos a representar: " + "; ".join(items[:4]) + ".")
    if requested:
        parts.append("Instrução específica do agente pedagógico: " + requested)
    return " ".join(parts)


class OpenAIImageGenerator:
    """Adaptador mínimo para a Image API, com resposta persistida em Base64."""

    provider_name = "OpenAI Image API"

    def __init__(
        self,
        *,
        model: str | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.model = model or config_value("OPENAI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
        self.size = config_value("OPENAI_IMAGE_SIZE", DEFAULT_IMAGE_SIZE)
        self.quality = config_value("OPENAI_IMAGE_QUALITY", DEFAULT_IMAGE_QUALITY)
        self.timeout_seconds = float(config_value("OPENAI_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(config_value("OPENAI_MAX_RETRIES", "2"))
        self.client_factory = client_factory

    def generate(
        self,
        *,
        prompt: str,
        slide_number: int,
        alt_text: str,
    ) -> dict[str, Any]:
        if self.client_factory is None and not os.getenv("OPENAI_API_KEY"):
            raise ImageGenerationError(
                "OPENAI_API_KEY não está disponível para gerar imagens por IA."
            )

        OpenAI = None
        if self.client_factory is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise ImageGenerationError(
                    "A geração de imagens requer a biblioteca OpenAI instalada."
                ) from error

        try:
            client = (
                self.client_factory()
                if self.client_factory is not None
                else OpenAI(
                    timeout=self.timeout_seconds,
                    max_retries=self.max_retries,
                )
            )
            response = client.images.generate(
                model=self.model,
                prompt=prompt,
                size=self.size,
                quality=self.quality,
                output_format="png",
                n=1,
            )
            data = getattr(response, "data", None) or []
            encoded = str(getattr(data[0], "b64_json", "") or "").strip() if data else ""
            if not encoded:
                raise ImageGenerationError("O fornecedor não devolveu dados de imagem.")
            # Garante que o conteúdo devolvido é Base64 válido antes de o persistir.
            base64.b64decode(encoded, validate=True)
        except ImageGenerationError:
            raise
        except Exception as error:
            raise ImageGenerationError(f"Falha na geração da imagem: {error}") from error

        identifier = f"ai-{uuid4().hex[:20]}"
        return {
            "id": identifier,
            "origin_type": "ai_generated",
            "provider": self.provider_name,
            "model": self.model,
            "prompt": prompt,
            "size": self.size,
            "quality": self.quality,
            "output_format": "png",
            "filename": f"coeria_slide_{slide_number}_ia.png",
            "media_type": "image/png",
            "data_base64": encoded,
            "alt_text": alt_text,
            "approved": False,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }


def enrich_presentation_with_ai_images(
    state: dict[str, Any],
    artifact: dict[str, Any],
    *,
    generator: OpenAIImageGenerator | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Gera apenas as imagens explicitamente propostas e autorizadas na sessão.

    Uma falha nunca bloqueia a apresentação: o slide regressa ao diagrama nativo.
    """

    slides = artifact.get("presentation_outline", [])
    if not isinstance(slides, list):
        return artifact, [], []

    generated_assets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    maximum = configured_max_images()
    enabled = image_generation_enabled(state)
    image_generator = generator or OpenAIImageGenerator()

    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict) or slide.get("visual_mode") != "ia":
            continue

        prompt = build_image_prompt(state, slide, index)
        if not enabled:
            slide["visual_mode"] = "diagrama"
            slide["visual_asset_id"] = ""
            slide["visual_source"] = (
                f"Diagrama nativo gerado pelo {APP_NAME}; a geração de imagens por IA "
                "não foi autorizada nesta sessão."
            )
            records.append(
                {
                    "slide": index,
                    "status": "not_authorized",
                    "prompt": prompt,
                }
            )
            continue

        if len(generated_assets) >= maximum:
            slide["visual_mode"] = "diagrama"
            slide["visual_asset_id"] = ""
            slide["visual_source"] = (
                f"Diagrama nativo gerado pelo {APP_NAME}; foi atingido o limite "
                "configurado de imagens geradas por IA."
            )
            records.append(
                {
                    "slide": index,
                    "status": "limit_reached",
                    "prompt": prompt,
                }
            )
            continue

        if progress_callback is not None:
            progress_callback(
                f"A gerar imagem por IA para o slide {index} de {len(slides)}…"
            )
        try:
            asset = image_generator.generate(
                prompt=prompt,
                slide_number=index,
                alt_text=str(slide.get("alt_text", "")).strip()
                or f"Imagem gerada por IA associada a {slide.get('visual_title', 'este slide')}.",
            )
        except ImageGenerationError as error:
            slide["visual_mode"] = "diagrama"
            slide["visual_asset_id"] = ""
            slide["visual_source"] = (
                f"Diagrama nativo gerado pelo {APP_NAME}; não foi possível obter "
                "a imagem por IA."
            )
            records.append(
                {
                    "slide": index,
                    "status": "failed",
                    "provider": image_generator.provider_name,
                    "model": image_generator.model,
                    "prompt": prompt,
                    "size": image_generator.size,
                    "quality": image_generator.quality,
                    "error": str(error),
                }
            )
            continue

        generated_assets.append(asset)
        slide["visual_asset_id"] = asset["id"]
        slide["visual_source"] = (
            f"Imagem gerada por IA — {asset['provider']}, modelo {asset['model']}."
        )
        records.append(
            {
                "slide": index,
                "status": "generated",
                "asset_id": asset["id"],
                "provider": asset["provider"],
                "model": asset["model"],
                "prompt": asset["prompt"],
                "size": asset["size"],
                "quality": asset["quality"],
            }
        )

    return artifact, generated_assets, records
