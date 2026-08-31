"""Cópias de segurança portáteis e legíveis de uma sessão CoerIA."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import re
import unicodedata
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any

from .branding import APP_VERSION, config_value
from .image_utils import ImageValidationError, build_thumbnail
from .ingestion import (
    configured_max_file_bytes,
    configured_max_total_upload_bytes,
    source_file_names,
)


BACKUP_FORMAT = "coeria-session-backup"
BACKUP_FORMAT_VERSION = 2
LEGACY_BACKUP_FORMAT_VERSION = 1
BACKUP_MANIFEST_NAME = "manifest.json"
BACKUP_STATE_NAME = "estado_tecnico.json"
LEGACY_BACKUP_STATE_NAME = "estado_sessao.json"
BACKUP_READABLE_STATE_NAME = "sessao.json"
BACKUP_ATTACHMENT_INDEX_NAME = "anexos/indice.json"
BACKUP_README_NAME = "LEIA-ME.txt"
DEFAULT_SESSION_BACKUP_MAX_BYTES = 240 * 1024 * 1024
DEFAULT_SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES = 384 * 1024 * 1024

ATTACHMENT_COLLECTIONS = {
    "source_attachments": ("fonte_original", "anexos/fontes"),
    "source_images": ("imagem_documental", "anexos/imagens_documentais"),
    "generated_images": (
        "imagem_da_apresentacao",
        "anexos/imagens_da_apresentacao",
    ),
}

HUMAN_KEY_LABELS = {
    "unit_name": "nome_unidade_curricular",
    "audience": "publico_alvo",
    "duration_hours": "duracao_horas",
    "taxonomy_type": "taxonomia",
    "program_name": "curso_ou_formacao",
    "program_type": "tipo_formacao",
    "academic_year": "ano_letivo",
    "semester": "semestre",
    "cnaef_code": "codigo_cnaef",
    "cnaef_name": "area_cnaef",
    "isced_f_code": "codigo_isced_f",
    "isced_f_name": "area_isced_f",
    "ects_credits": "creditos_ects",
    "contact_hours": "horas_contacto",
    "autonomous_hours": "horas_trabalho_autonomo",
    "general_aims": "objetivos_gerais",
    "bibliography": "bibliografia",
    "learning_outcomes": "resultados_de_aprendizagem",
    "curriculum_analysis": "conteudos_curriculares",
    "teaching_activities": "atividades_de_ensino_aprendizagem",
    "assessment_activities": "tarefas_e_criterios_de_avaliacao",
    "pedagogical_design": "planeamento_das_aulas",
    "resources": "recursos_educativos",
    "final_validation": "validacao_final",
    "statement": "enunciado",
    "action_verb": "verbo_acao",
    "taxonomy_level": "nivel_taxonomico",
    "outcome_type": "tipo_resultado",
    "rationale": "fundamentacao",
    "content_links": "ligacoes_a_conteudos",
    "content_id": "id_conteudo",
    "importance": "importancia",
    "contents": "conteudos",
    "title": "titulo",
    "description": "descricao",
    "outcome_id": "id_resultado_aprendizagem",
    "outcome_ids": "ids_resultados_aprendizagem",
    "teaching_activity_ids": "ids_atividades_ensino_aprendizagem",
    "assessment_ids": "ids_tarefas_avaliacao",
    "activity": "atividade",
    "learning_context": "contexto_aprendizagem",
    "practice": "pratica",
    "support": "acompanhamento",
    "feedback_strategy": "estrategia_feedback",
    "work_type": "modalidade_trabalho",
    "assessment_purpose": "finalidade_avaliacao",
    "criteria": "criterios",
    "criterion": "criterio",
    "weight_percent": "ponderacao_percentagem",
    "strategy": "estrategia",
    "sequence": "sequencia",
    "lessons": "aulas",
    "duration_minutes": "duracao_minutos",
    "session_type": "tipo_sessao",
    "component_ids": "ids_atividades_ou_avaliacao",
    "notes": "texto_opcional",
    "focus": "foco",
    "teaching_activity": "atividade_ensino_aprendizagem",
    "assessment": "tarefa_avaliacao",
    "resource_types": "tipos_de_recurso",
    "resource_scopes": "ambitos_dos_recursos",
    "selected_resource_types": "tipos_de_recurso_selecionados",
    "presentation_outline": "apresentacao",
    "lesson_presentations": "apresentacoes_das_aulas",
    "lesson_number": "numero_da_aula",
    "lesson_plan": "plano_de_aulas",
    "assessment_grid": "grelha_de_avaliacao",
    "assessment_task_id": "id_tarefa_avaliacao",
    "tests": "testes",
    "lesson_sheet": "ficha_de_aula",
    "test": "teste",
    "practical_activity": "atividade_pratica",
    "slides": "diapositivos",
    "slide_number": "numero_diapositivo",
    "visual_mode": "modo_visual",
    "visual_asset_id": "id_imagem_associada",
    "visual_prompt": "prompt_visual",
    "alt_text": "texto_alternativo",
    "instructions": "instrucoes",
    "questions": "questoes",
    "question": "questao",
    "answer_key": "chave_correcao",
    "points": "pontos",
    "content": "conteudo",
    "materials": "materiais",
    "deliverables": "entregaveis",
    "duration_minutes": "duracao_minutos",
    "created_at": "criado_em",
    "updated_at": "atualizado_em",
    "timestamp": "data_hora",
    "stage": "etapa",
    "event": "evento",
    "feedback": "detalhe",
    "provider": "fornecedor",
    "model": "modelo",
    "status": "estado",
}


def _configured_positive_limit(name: str, default: int) -> int:
    try:
        value = int(config_value(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def configured_session_backup_max_bytes() -> int:
    """Limite do ficheiro ZIP recebido pela aplicação."""

    return _configured_positive_limit(
        "SESSION_BACKUP_MAX_BYTES",
        DEFAULT_SESSION_BACKUP_MAX_BYTES,
    )


def configured_session_backup_max_uncompressed_bytes() -> int:
    """Limite do conteúdo descomprimido, protegendo contra ZIP bombs."""

    return _configured_positive_limit(
        "SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES",
        DEFAULT_SESSION_BACKUP_MAX_UNCOMPRESSED_BYTES,
    )


def _safe_backup_stem(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").lower()
    return normalized[:60] or "sessao"


def _original_upload_name(value: str) -> str:
    filename = Path(value).name
    prefix, separator, remainder = filename.partition("_")
    if separator and len(prefix) == 2 and prefix.isdigit() and remainder:
        return remainder
    return filename


def _safe_attachment_filename(value: str, fallback: str) -> str:
    filename = Path(str(value or "")).name
    suffix = Path(filename).suffix.lower()
    stem = filename[: -len(suffix)] if suffix else filename
    safe_stem = _safe_backup_stem(stem or fallback)
    safe_suffix = re.sub(r"[^a-z0-9.]", "", suffix)[:12]
    return f"{safe_stem}{safe_suffix}"


def capture_source_attachments(
    source_files: list[str] | str | None,
) -> list[dict[str, Any]]:
    """Conserva os ficheiros de origem para os incluir em backups futuros."""

    if not source_files:
        return []
    paths = [source_files] if isinstance(source_files, str) else list(source_files)
    maximum_file = configured_max_file_bytes()
    maximum_total = configured_max_total_upload_bytes()
    captured: list[dict[str, Any]] = []
    total_bytes = 0
    for item in paths:
        path = Path(item)
        if not path.is_file():
            raise ValueError(f"O anexo {path.name or item} já não está disponível.")
        size_bytes = path.stat().st_size
        if size_bytes > maximum_file:
            raise ValueError(
                f"O anexo {path.name} excede o limite de "
                f"{maximum_file // (1024 * 1024)} MB."
            )
        total_bytes += size_bytes
        if total_bytes > maximum_total:
            raise ValueError(
                "O conjunto dos anexos excede o limite de "
                f"{maximum_total // (1024 * 1024)} MB."
            )
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        identifier_digest = hashlib.sha256(
            path.name.encode("utf-8") + b"\0" + data
        ).hexdigest()
        original_name = _original_upload_name(path.name)
        media_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        captured.append(
            {
                "id": f"source-{identifier_digest[:20]}",
                "source_file": path.name,
                "filename": original_name,
                "media_type": media_type,
                "size_bytes": len(data),
                "sha256": digest,
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    return captured


def _decode_asset_data(asset: dict[str, Any]) -> bytes | None:
    encoded = str(asset.pop("data_base64", "") or "").strip()
    data_url = str(asset.pop("data_url", "") or "").strip()
    asset.pop("thumbnail_base64", None)
    if not encoded and data_url.startswith("data:") and "," in data_url:
        encoded = data_url.split(",", 1)[1]
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError("A sessão contém um anexo com dados inválidos.") from error


def _extract_backup_attachments(
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, bytes]]]:
    technical_state = deepcopy(state)
    index_entries: list[dict[str, Any]] = []
    archive_files: list[tuple[str, bytes]] = []
    for collection, (category, directory) in ATTACHMENT_COLLECTIONS.items():
        assets = technical_state.get(collection, [])
        if not isinstance(assets, list):
            continue
        for item_index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            data = _decode_asset_data(asset)
            if data is None:
                raise ValueError(
                    "Não foi possível incluir um dos anexos da sessão na cópia."
                )
            original_name = str(
                asset.get("filename")
                or asset.get("source_file")
                or f"anexo-{item_index + 1}"
            )
            safe_name = _safe_attachment_filename(
                original_name,
                f"anexo-{item_index + 1}",
            )
            archive_path = f"{directory}/{item_index + 1:03d}_{safe_name}"
            checksum = hashlib.sha256(data).hexdigest()
            asset["backup_file"] = archive_path
            entry = {
                "categoria": category,
                "ficheiro": archive_path,
                "nome_original": _original_upload_name(original_name),
                "tipo_media": str(
                    asset.get("media_type") or "application/octet-stream"
                ),
                "bytes": len(data),
                "sha256": checksum,
                "colecao_estado": collection,
                "indice_estado": item_index,
            }
            for key, label in (
                ("source_file", "ficheiro_origem"),
                ("source_location", "localizacao_origem"),
                ("alt_text", "texto_alternativo"),
            ):
                value = str(asset.get(key, "") or "").strip()
                if value:
                    entry[label] = value
            index_entries.append(entry)
            archive_files.append((archive_path, data))

    preserved_source_files = {
        str(item.get("source_file", "")).strip()
        for item in technical_state.get("source_attachments", [])
        if isinstance(item, dict)
    }
    unavailable_sources = [
        name
        for name in source_file_names(str(technical_state.get("source_original_text", "")))
        if name not in preserved_source_files
    ]
    attachment_index = {
        "versao": 1,
        "anexos": index_entries,
        "fontes_originais_indisponiveis": unavailable_sources,
    }
    return technical_state, attachment_index, archive_files


def _human_readable_state(
    state: dict[str, Any],
    attachment_index: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    course = deepcopy(state.get("course", {}))
    processed_source = str(course.pop("source_text", "") or "")
    return {
        "sobre_esta_copia": {
            "descricao": (
                "Conteúdo legível da sessão CoerIA. Os textos podem ser consultados "
                "e copiados sem abrir a aplicação."
            ),
            "criada_em": created_at,
            "versao_coeria": APP_VERSION,
            "sessao_origem": str(state.get("session_id", "")),
            "nota": (
                "Os nomes de alguns campos refletem a estrutura interna usada pelos "
                "editores da aplicação."
            ),
        },
        "unidade_curricular": _humanize_keys(course),
        "fontes": {
            "texto_introduzido_pelo_docente": str(
                state.get("source_input_text", "") or ""
            ),
            "texto_processado": processed_source,
            "anexos": deepcopy(attachment_index.get("anexos", [])),
            "fontes_originais_indisponiveis": deepcopy(
                attachment_index.get("fontes_originais_indisponiveis", [])
            ),
        },
        "etapas": {
            "pressupostos_para_resultados_opcionais": deepcopy(
                state.get("learning_outcome_assumptions", [])
            ),
            "resultados_de_aprendizagem": _humanize_keys(
                state.get("learning_outcomes", [])
            ),
            "conteudos_curriculares": _humanize_keys(
                state.get("curriculum_analysis", {})
            ),
            "atividades_de_ensino_aprendizagem": _humanize_keys(
                state.get("teaching_activities", [])
            ),
            "tarefas_e_criterios_de_avaliacao": _humanize_keys(
                state.get("assessment_activities", [])
            ),
            "organizacao_da_sequencia_pedagogica": _humanize_keys(
                state.get("pedagogical_design", {})
            ),
            "recursos_educativos": _humanize_keys(state.get("resources", {})),
            "validacao_final": _humanize_keys(
                state.get("final_validation", {})
            ),
        },
        "versoes": _humanize_keys(state.get("versions", {})),
        "rastreabilidade": _humanize_keys(state.get("audit", [])),
    }


def _humanize_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_humanize_keys(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    return {
        HUMAN_KEY_LABELS.get(str(key), str(key)): _humanize_keys(item)
        for key, item in value.items()
    }


def _readme_text(attachment_index: dict[str, Any]) -> str:
    missing_sources = attachment_index.get("fontes_originais_indisponiveis", [])
    missing_note = "Nenhuma."
    if missing_sources:
        missing_note = "\n".join(f"- {name}" for name in missing_sources)
    return (
        "CÓPIA DE SEGURANÇA DE UMA SESSÃO COERIA\n"
        "========================================\n\n"
        "sessao.json\n"
        "  Versão legível dos dados, etapas, recursos, versões e rastreabilidade.\n"
        "  Pode abrir este ficheiro num editor de texto e copiar os conteúdos.\n\n"
        "anexos/\n"
        "  Ficheiros originais preservados e imagens existentes na sessão.\n"
        "  O ficheiro anexos/indice.json descreve a origem de cada elemento.\n\n"
        "estado_tecnico.json e manifest.json\n"
        "  Ficheiros necessários ao restauro automático. Não os altere.\n\n"
        "As chaves de API não são incluídas nesta cópia.\n\n"
        "Fontes originais referenciadas por sessões antigas mas não disponíveis:\n"
        f"{missing_note}\n"
    )


def _json_bytes(value: Any, *, indent: int | None = 2) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=False,
        indent=indent,
        separators=None if indent is not None else (",", ":"),
    ).encode("utf-8")


def create_session_backup(state: dict[str, Any]) -> str:
    """Cria um ZIP restaurável, legível e com anexos extraídos."""

    if not isinstance(state, dict):
        raise ValueError("Não foi possível preparar a cópia da sessão.")
    created_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    technical_state, attachment_index, attachment_files = (
        _extract_backup_attachments(state)
    )
    technical_bytes = _json_bytes(technical_state)
    readable_bytes = _json_bytes(
        _human_readable_state(technical_state, attachment_index, created_at)
    )
    index_bytes = _json_bytes(attachment_index)
    readme_bytes = _readme_text(attachment_index).encode("utf-8")
    archived_files = [
        (BACKUP_STATE_NAME, technical_bytes),
        (BACKUP_READABLE_STATE_NAME, readable_bytes),
        (BACKUP_ATTACHMENT_INDEX_NAME, index_bytes),
        (BACKUP_README_NAME, readme_bytes),
        *attachment_files,
    ]
    total_uncompressed = sum(len(data) for _, data in archived_files)
    maximum_uncompressed = configured_session_backup_max_uncompressed_bytes()
    if total_uncompressed > maximum_uncompressed:
        raise ValueError(
            "A sessão excede o limite da cópia de segurança "
            f"({maximum_uncompressed // (1024 * 1024)} MB descomprimidos)."
        )

    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": APP_VERSION,
        "created_at": created_at,
        "source_session_id": str(state.get("session_id", "")),
        "unit_name": str(state.get("course", {}).get("unit_name", "")),
        "state_file": BACKUP_STATE_NAME,
        "state_bytes": len(technical_bytes),
        "state_sha256": hashlib.sha256(technical_bytes).hexdigest(),
        "readable_file": BACKUP_READABLE_STATE_NAME,
        "readable_bytes": len(readable_bytes),
        "readable_sha256": hashlib.sha256(readable_bytes).hexdigest(),
        "attachment_index_file": BACKUP_ATTACHMENT_INDEX_NAME,
        "attachment_index_bytes": len(index_bytes),
        "attachment_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "readme_file": BACKUP_README_NAME,
        "readme_bytes": len(readme_bytes),
        "readme_sha256": hashlib.sha256(readme_bytes).hexdigest(),
        "attachment_count": len(attachment_files),
    }
    manifest_bytes = _json_bytes(manifest)
    archived_files.insert(0, (BACKUP_MANIFEST_NAME, manifest_bytes))
    unit_stem = _safe_backup_stem(str(manifest["unit_name"]))
    session_stem = _safe_backup_stem(str(manifest["source_session_id"]))[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with NamedTemporaryFile(
        prefix=f"coeria_backup_{unit_stem}_{session_stem}_",
        suffix=f"_{timestamp}.coeria-backup.zip",
        delete=False,
    ) as temporary_file:
        destination = Path(temporary_file.name)
    try:
        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for archive_path, file_data in archived_files:
                archive.writestr(archive_path, file_data)
        maximum_backup = configured_session_backup_max_bytes()
        if destination.stat().st_size > maximum_backup:
            raise ValueError(
                "A cópia de segurança excede o limite de "
                f"{maximum_backup // (1024 * 1024)} MB."
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)


def _safe_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and "\\" not in value
        and not path.is_absolute()
        and ".." not in path.parts
        and all(part not in ("", ".") for part in path.parts)
    )


def _verify_declared_file(
    manifest: dict[str, Any],
    prefix: str,
    data: bytes,
) -> None:
    if manifest.get(f"{prefix}_bytes") != len(data):
        raise ValueError("A dimensão de um ficheiro não corresponde ao manifesto.")
    expected = str(manifest.get(f"{prefix}_sha256", ""))
    actual = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise ValueError("A integridade da cópia de segurança não pôde ser confirmada.")


def _read_json_object(data: bytes, error_message: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_message) from error
    if not isinstance(value, dict):
        raise ValueError(error_message)
    return value


def _restore_v2_attachments(
    archive: zipfile.ZipFile,
    state: dict[str, Any],
    attachment_index: dict[str, Any],
) -> set[str]:
    entries = attachment_index.get("anexos", [])
    if not isinstance(entries, list):
        raise ValueError("O índice de anexos é inválido.")
    expected_paths: set[str] = set()
    restored_targets: set[tuple[str, int]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("O índice de anexos é inválido.")
        archive_path = str(entry.get("ficheiro", ""))
        collection = str(entry.get("colecao_estado", ""))
        item_index = entry.get("indice_estado")
        if (
            not _safe_archive_path(archive_path)
            or not archive_path.startswith("anexos/")
            or collection not in ATTACHMENT_COLLECTIONS
            or not isinstance(item_index, int)
            or item_index < 0
            or archive_path in expected_paths
            or (collection, item_index) in restored_targets
        ):
            raise ValueError("O índice de anexos é inválido.")
        assets = state.get(collection)
        if (
            not isinstance(assets, list)
            or item_index >= len(assets)
            or not isinstance(assets[item_index], dict)
        ):
            raise ValueError("Um anexo não corresponde ao estado da sessão.")
        data = archive.read(archive_path)
        if entry.get("bytes") != len(data):
            raise ValueError("A dimensão de um anexo não corresponde ao índice.")
        expected_checksum = str(entry.get("sha256", ""))
        if not hmac.compare_digest(
            expected_checksum,
            hashlib.sha256(data).hexdigest(),
        ):
            raise ValueError("A integridade de um anexo não pôde ser confirmada.")
        asset = assets[item_index]
        asset["data_base64"] = base64.b64encode(data).decode("ascii")
        asset.pop("backup_file", None)
        if collection in ("source_images", "generated_images"):
            try:
                asset.update(build_thumbnail(data))
            except ImageValidationError as error:
                raise ValueError(
                    "A cópia de segurança contém um anexo de imagem inválido."
                ) from error
        expected_paths.add(archive_path)
        restored_targets.add((collection, item_index))
    return expected_paths


def read_session_backup(data: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valida backups v1/v2 e reconstitui o estado integral da sessão."""

    if not isinstance(data, bytes) or not data:
        raise ValueError("Selecione uma cópia de segurança válida.")
    maximum_backup = configured_session_backup_max_bytes()
    if len(data) > maximum_backup:
        raise ValueError(
            "A cópia de segurança excede o limite de "
            f"{maximum_backup // (1024 * 1024)} MB."
        )

    try:
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if len(entries) != len(names) or BACKUP_MANIFEST_NAME not in names:
                raise ValueError("A cópia de segurança contém entradas inválidas.")
            if any(
                entry.is_dir()
                or entry.flag_bits & 0x1
                or not _safe_archive_path(entry.filename)
                for entry in entries
            ):
                raise ValueError("A cópia de segurança contém entradas inválidas.")
            maximum_uncompressed = configured_session_backup_max_uncompressed_bytes()
            if sum(entry.file_size for entry in entries) > maximum_uncompressed:
                raise ValueError(
                    "A sessão excede o limite de restauro "
                    f"({maximum_uncompressed // (1024 * 1024)} MB descomprimidos)."
                )
            manifest_info = archive.getinfo(BACKUP_MANIFEST_NAME)
            if manifest_info.file_size > 64 * 1024:
                raise ValueError("O manifesto da cópia de segurança é inválido.")
            manifest = _read_json_object(
                archive.read(BACKUP_MANIFEST_NAME),
                "O manifesto da cópia de segurança é inválido.",
            )
            if manifest.get("format") != BACKUP_FORMAT:
                raise ValueError("O ficheiro não pertence ao formato de backup do CoerIA.")
            version = manifest.get("format_version")
            if version not in (LEGACY_BACKUP_FORMAT_VERSION, BACKUP_FORMAT_VERSION):
                raise ValueError("A versão do formato de backup não é suportada.")

            if version == LEGACY_BACKUP_FORMAT_VERSION:
                if names != {BACKUP_MANIFEST_NAME, LEGACY_BACKUP_STATE_NAME}:
                    raise ValueError(
                        "A cópia de segurança não contém a estrutura esperada do CoerIA."
                    )
                if manifest.get("state_file") != LEGACY_BACKUP_STATE_NAME:
                    raise ValueError("O manifesto referencia um estado inválido.")
                state_bytes = archive.read(LEGACY_BACKUP_STATE_NAME)
                _verify_declared_file(manifest, "state", state_bytes)
                state = _read_json_object(
                    state_bytes,
                    "A cópia de segurança contém um estado JSON inválido.",
                )
                return state, manifest

            required_names = {
                BACKUP_MANIFEST_NAME,
                BACKUP_STATE_NAME,
                BACKUP_READABLE_STATE_NAME,
                BACKUP_ATTACHMENT_INDEX_NAME,
                BACKUP_README_NAME,
            }
            if not required_names.issubset(names):
                raise ValueError(
                    "A cópia de segurança não contém a estrutura esperada do CoerIA."
                )
            if (
                manifest.get("state_file") != BACKUP_STATE_NAME
                or manifest.get("readable_file") != BACKUP_READABLE_STATE_NAME
                or manifest.get("attachment_index_file")
                != BACKUP_ATTACHMENT_INDEX_NAME
                or manifest.get("readme_file") != BACKUP_README_NAME
            ):
                raise ValueError("O manifesto referencia ficheiros inválidos.")
            state_bytes = archive.read(BACKUP_STATE_NAME)
            readable_bytes = archive.read(BACKUP_READABLE_STATE_NAME)
            index_bytes = archive.read(BACKUP_ATTACHMENT_INDEX_NAME)
            readme_bytes = archive.read(BACKUP_README_NAME)
            _verify_declared_file(manifest, "state", state_bytes)
            _verify_declared_file(manifest, "readable", readable_bytes)
            _verify_declared_file(manifest, "attachment_index", index_bytes)
            _verify_declared_file(manifest, "readme", readme_bytes)
            state = _read_json_object(
                state_bytes,
                "A cópia de segurança contém um estado JSON inválido.",
            )
            _read_json_object(
                readable_bytes,
                "A cópia de segurança contém um JSON de consulta inválido.",
            )
            attachment_index = _read_json_object(
                index_bytes,
                "A cópia de segurança contém um índice de anexos inválido.",
            )
            attachment_paths = _restore_v2_attachments(
                archive,
                state,
                attachment_index,
            )
            if names != required_names | attachment_paths:
                raise ValueError("A cópia de segurança contém ficheiros inesperados.")
            if manifest.get("attachment_count") != len(attachment_paths):
                raise ValueError("A contagem de anexos não corresponde ao manifesto.")
            return state, manifest
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError(
            "O ficheiro não é uma cópia de segurança válida do CoerIA."
        ) from error
