"""Extração segura de texto dos ficheiros fornecidos pelo docente."""

from __future__ import annotations

import base64
import mimetypes
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile

from .branding import config_value


SUPPORTED_SOURCE_SUFFIXES = {".txt", ".md", ".tex", ".pdf", ".docx", ".pptx"}
DIRECT_SOURCE_MARKER = "[Texto introduzido pelo docente]"
DEFAULT_MAX_SOURCE_CHARS = 120_000
DEFAULT_MAX_RAW_SOURCE_CHARS = 2_000_000
DEFAULT_MAX_FILE_BYTES = 12 * 1024 * 1024
DEFAULT_MAX_EXTRACTED_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_EXTRACTED_IMAGES = 30


class SourceIngestionError(ValueError):
    """Erro compreensível durante a leitura de uma fonte documental."""


def _configured_limit(suffix: str, default: int) -> int:
    name = f"COERIA_{suffix}"
    raw = config_value(suffix, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise SourceIngestionError(f"A variável {name} deve ser um número inteiro.") from error
    if value <= 0:
        raise SourceIngestionError(f"A variável {name} deve ser superior a zero.")
    return value


def _read_plain_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise SourceIngestionError(
            "A leitura de PDF requer a dependência pypdf. Reinstale os requisitos."
        ) from error

    try:
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except Exception as error:
        raise SourceIngestionError(f"Não foi possível extrair texto de {path.name}.") from error


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as error:
        raise SourceIngestionError(
            "A leitura de DOCX requer a dependência python-docx. Reinstale os requisitos."
        ) from error

    try:
        document = Document(str(path))
        parts = [paragraph.text.strip() for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(part for part in parts if part)
    except Exception as error:
        raise SourceIngestionError(f"Não foi possível extrair texto de {path.name}.") from error


def _read_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
    except ImportError as error:
        raise SourceIngestionError(
            "A leitura de PPTX requer a dependência python-pptx. Reinstale os requisitos."
        ) from error

    try:
        presentation = Presentation(str(path))
        parts: list[str] = []
        for index, slide in enumerate(presentation.slides, start=1):
            slide_text = [shape.text.strip() for shape in slide.shapes if hasattr(shape, "text")]
            if any(slide_text):
                parts.append(f"Slide {index}\n" + "\n".join(text for text in slide_text if text))
        return "\n\n".join(parts)
    except Exception as error:
        raise SourceIngestionError(f"Não foi possível extrair texto de {path.name}.") from error


def _image_media_type(filename: str) -> str:
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _source_image_asset(
    *,
    data: bytes,
    source_file: str,
    filename: str,
    location: str = "",
) -> dict[str, Any] | None:
    """Normaliza uma imagem documental para persistência no estado da sessão."""

    if not data or len(data) > DEFAULT_MAX_EXTRACTED_IMAGE_BYTES:
        return None

    digest = sha256(
        source_file.encode("utf-8")
        + b"\0"
        + location.encode("utf-8")
        + b"\0"
        + data
    ).hexdigest()[:20]

    return {
        "id": f"document-{digest}",
        "origin_type": "document",
        "source_file": source_file,
        "source_location": location,
        "filename": Path(filename).name or f"imagem-{digest}.bin",
        "media_type": _image_media_type(filename),
        "data_base64": base64.b64encode(data).decode("ascii"),
        "alt_text": "",
        "approved": False,
    }


def _extract_pdf_images(path: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise SourceIngestionError(
            "A extração de imagens de PDF requer a dependência pypdf. "
            "Reinstale os requisitos."
        ) from error

    assets: list[dict[str, Any]] = []

    try:
        reader = PdfReader(str(path))

        for page_index, page in enumerate(reader.pages, start=1):
            try:
                page_images = list(page.images)
            except Exception:
                continue

            for image_index, image in enumerate(page_images, start=1):
                try:
                    filename = str(
                        getattr(image, "name", "")
                        or f"imagem-{image_index}.bin"
                    )

                    asset = _source_image_asset(
                        data=bytes(image.data),
                        source_file=path.name,
                        filename=filename,
                        location=f"Página {page_index}",
                    )
                except Exception:
                    continue

                if asset is not None:
                    assets.append(asset)

                    if len(assets) >= DEFAULT_MAX_EXTRACTED_IMAGES:
                        return assets

        return assets

    except Exception:
        return []


def _extract_docx_images(path: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []

    try:
        with ZipFile(path) as archive:
            media_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("word/media/")
                and not name.endswith("/")
            )

            for media_name in media_names[:DEFAULT_MAX_EXTRACTED_IMAGES]:
                asset = _source_image_asset(
                    data=archive.read(media_name),
                    source_file=path.name,
                    filename=Path(media_name).name,
                )

                if asset is not None:
                    assets.append(asset)

        return assets

    except (BadZipFile, KeyError, OSError):
        return []


def _extract_pptx_images(path: Path) -> list[dict[str, Any]]:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as error:
        raise SourceIngestionError(
            "A extração de imagens de PPTX requer a dependência python-pptx. "
            "Reinstale os requisitos."
        ) from error

    assets: list[dict[str, Any]] = []

    def visit_shapes(shapes: Any, slide_index: int) -> bool:
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                if visit_shapes(shape.shapes, slide_index):
                    return True
                continue

            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue

            image = shape.image

            asset = _source_image_asset(
                data=bytes(image.blob),
                source_file=path.name,
                filename=str(
                    image.filename or f"imagem.{image.ext}"
                ),
                location=f"Slide {slide_index}",
            )

            if asset is not None:
                assets.append(asset)

                if len(assets) >= DEFAULT_MAX_EXTRACTED_IMAGES:
                    return True

        return False

    try:
        presentation = Presentation(str(path))

        for slide_index, slide in enumerate(
            presentation.slides,
            start=1,
        ):
            if visit_shapes(slide.shapes, slide_index):
                break

        return assets

    except Exception:
        return []


def extract_file_images(
    path_value: str | Path,
) -> list[dict[str, Any]]:
    """Extrai imagens raster de fontes documentais com proveniência rastreável."""

    path = Path(path_value)

    if not path.is_file():
        raise SourceIngestionError(
            f"O ficheiro {path.name or path} não está disponível."
        )

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf_images(path)

    if suffix == ".docx":
        return _extract_docx_images(path)

    if suffix == ".pptx":
        return _extract_pptx_images(path)

    return []


def extract_source_images(
    file_paths: str | Path | Iterable[str | Path] | None = None,
) -> list[dict[str, Any]]:
    """Extrai e desduplica imagens dos documentos carregados como referência."""

    assets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for path_value in _normalise_paths(file_paths):
        for asset in extract_file_images(path_value):
            asset_id = str(asset["id"])

            if asset_id in seen_ids:
                continue

            seen_ids.add(asset_id)
            assets.append(asset)

            if len(assets) >= DEFAULT_MAX_EXTRACTED_IMAGES:
                return assets

    return assets


def extract_file_text(path_value: str | Path) -> str:
    path = Path(path_value)
    if not path.is_file():
        raise SourceIngestionError(f"O ficheiro {path.name or path} não está disponível.")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        formats = ", ".join(sorted(SUPPORTED_SOURCE_SUFFIXES))
        raise SourceIngestionError(f"Formato não suportado. Utilize: {formats}.")

    max_bytes = _configured_limit("MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)
    if path.stat().st_size > max_bytes:
        raise SourceIngestionError(
            f"O ficheiro {path.name} excede o limite de {max_bytes // (1024 * 1024)} MB."
        )

    if suffix in {".txt", ".md", ".tex"}:
        text = _read_plain_text(path)
    elif suffix == ".pdf":
        text = _read_pdf(path)
    elif suffix == ".docx":
        text = _read_docx(path)
    else:
        text = _read_pptx(path)

    clean = text.strip()
    if not clean:
        raise SourceIngestionError(
            f"Não foi encontrado texto utilizável em {path.name}. PDFs digitalizados podem exigir OCR."
        )
    return clean


def _normalise_paths(file_paths: str | Path | Iterable[str | Path] | None) -> list[str | Path]:
    if file_paths is None:
        return []
    if isinstance(file_paths, (str, Path)):
        return [file_paths]
    return list(file_paths)


def _combine_source_text(
    source_text: str,
    file_paths: str | Path | Iterable[str | Path] | None = None,
) -> str:
    parts: list[str] = []
    direct = (source_text or "").strip()
    if direct:
        parts.append(DIRECT_SOURCE_MARKER + "\n" + direct)

    for path_value in _normalise_paths(file_paths):
        path = Path(path_value)
        parts.append(f"[Ficheiro: {path.name}]\n{extract_file_text(path)}")

    return "\n\n".join(parts).strip()


def build_raw_source_text(
    source_text: str,
    file_paths: str | Path | Iterable[str | Path] | None = None,
) -> str:
    """Combina fontes extensas antes da eventual redução automática por IA."""

    combined = _combine_source_text(source_text, file_paths)
    max_chars = _configured_limit(
        "MAX_RAW_SOURCE_CHARS", DEFAULT_MAX_RAW_SOURCE_CHARS
    )
    if len(combined) > max_chars:
        raise SourceIngestionError(
            f"As fontes contêm {len(combined):,} caracteres e excedem o limite absoluto "
            f"de ingestão de {max_chars:,}. Remova documentos redundantes ou aumente "
            "COERIA_MAX_RAW_SOURCE_CHARS de forma consciente."
        )
    return combined


def build_source_text(
    source_text: str,
    file_paths: str | Path | Iterable[str | Path] | None = None,
) -> str:
    """Combina fontes respeitando o orçamento normal do contexto do pipeline.

    Mantém-se como API compatível para validações/testes. A aplicação usa
    :func:`build_raw_source_text` e reduz automaticamente fontes extensas antes
    de iniciar o fluxo pedagógico.
    """

    combined = build_raw_source_text(source_text, file_paths)
    max_chars = _configured_limit("MAX_SOURCE_CHARS", DEFAULT_MAX_SOURCE_CHARS)
    if len(combined) > max_chars:
        raise SourceIngestionError(
            f"As fontes contêm {len(combined):,} caracteres e excedem o limite de "
            f"{max_chars:,}."
        )
    return combined


def recover_direct_source_text(combined_text: str) -> str:
    """Recupera o texto direto de estados antigos com etiquetas de proveniência.

    Sessões novas guardam o valor original separadamente. Esta função existe
    para que sessões criadas antes dessa alteração não apresentem as etiquetas
    internas nem o conteúdo extraído dos ficheiros no campo do docente.
    """

    text = (combined_text or "").strip()
    if not text.startswith(DIRECT_SOURCE_MARKER):
        return "" if text.startswith("[Ficheiro: ") else text

    direct = text[len(DIRECT_SOURCE_MARKER) :].lstrip("\r\n")
    file_marker = re.search(r"\r?\n\r?\n\[Ficheiro: [^\]]+\]\r?\n", direct)
    if file_marker:
        direct = direct[: file_marker.start()]
    return direct.strip()
