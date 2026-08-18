"""Validação, normalização e miniaturas de imagens usadas pelo CoerIA."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageValidationError(ValueError):
    """Indica que os bytes não representam uma imagem raster utilizável."""


def _load_rgb_image(data: bytes) -> Image.Image:
    if not data:
        raise ImageValidationError("A imagem não contém dados.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = image.convert("RGB")
            return image.copy()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageValidationError(
            "Os bytes produzidos não correspondem a uma imagem PNG/JPEG válida."
        ) from error


def normalise_image_bytes(
    data: bytes,
    *,
    filename: str = "imagem",
    max_bytes: int = 5 * 1024 * 1024,
) -> dict[str, Any]:
    """Valida com Pillow e converte a imagem para PNG/JPEG RGB.

    PNG é preferido para diagramas e transparências já compostas sobre branco.
    Se o PNG ultrapassar o orçamento configurado, é usado JPEG RGB de qualidade
    elevada. O resultado volta a ser aberto pelo Pillow antes de ser aceite.
    """

    image = _load_rgb_image(data)
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageValidationError("A imagem tem dimensões inválidas.")

    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG", optimize=True)
    normalized = png_buffer.getvalue()
    media_type = "image/png"
    extension = ".png"

    if len(normalized) > max_bytes:
        jpeg_buffer = io.BytesIO()
        image.save(
            jpeg_buffer,
            format="JPEG",
            quality=88,
            optimize=True,
            progressive=True,
        )
        normalized = jpeg_buffer.getvalue()
        media_type = "image/jpeg"
        extension = ".jpg"

    if len(normalized) > max_bytes:
        raise ImageValidationError(
            f"A imagem normalizada excede o limite de {max_bytes // (1024 * 1024)} MB."
        )

    # Segunda abertura deliberada: garante que os bytes persistidos continuam
    # descodificáveis depois da conversão.
    verified = _load_rgb_image(normalized)
    if verified.size != (width, height):
        raise ImageValidationError("A imagem normalizada não preservou as dimensões.")

    stem = Path(filename).stem or "imagem"
    return {
        "data": normalized,
        "media_type": media_type,
        "filename": stem + extension,
        "width_px": width,
        "height_px": height,
        "mode": "RGB",
    }


def build_thumbnail(
    data: bytes,
    *,
    max_size: tuple[int, int] = (420, 260),
) -> dict[str, str]:
    """Cria miniatura JPEG compacta para seleção humana na interface."""

    image = _load_rgb_image(data)
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80, optimize=True)
    return {
        "thumbnail_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "thumbnail_media_type": "image/jpeg",
    }
