"""Extração segura de texto dos ficheiros fornecidos pelo docente."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .branding import config_value


SUPPORTED_SOURCE_SUFFIXES = {".txt", ".md", ".tex", ".pdf", ".docx", ".pptx"}
DIRECT_SOURCE_MARKER = "[Texto introduzido pelo docente]"
DEFAULT_MAX_SOURCE_CHARS = 120_000
DEFAULT_MAX_FILE_BYTES = 12 * 1024 * 1024


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


def build_source_text(
    source_text: str,
    file_paths: str | Path | Iterable[str | Path] | None = None,
) -> str:
    """Combina texto direto e documentos, preservando a origem de cada excerto."""

    parts: list[str] = []
    direct = (source_text or "").strip()
    if direct:
        parts.append(DIRECT_SOURCE_MARKER + "\n" + direct)

    for path_value in _normalise_paths(file_paths):
        path = Path(path_value)
        parts.append(f"[Ficheiro: {path.name}]\n{extract_file_text(path)}")

    combined = "\n\n".join(parts).strip()
    max_chars = _configured_limit("MAX_SOURCE_CHARS", DEFAULT_MAX_SOURCE_CHARS)
    if len(combined) > max_chars:
        raise SourceIngestionError(
            f"As fontes contêm {len(combined):,} caracteres e excedem o limite de "
            f"{max_chars:,}. Reduza ou divida os documentos."
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
