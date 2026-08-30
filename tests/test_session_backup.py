from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from prism.application_service import ApplicationService
from prism.image_utils import build_thumbnail
from prism.models import CourseInput
from prism.persistence import SQLiteSessionStore
from prism.session_backup import (
    BACKUP_ATTACHMENT_INDEX_NAME,
    BACKUP_MANIFEST_NAME,
    BACKUP_READABLE_STATE_NAME,
    BACKUP_README_NAME,
    BACKUP_STATE_NAME,
    LEGACY_BACKUP_STATE_NAME,
    capture_source_attachments,
    create_session_backup,
    read_session_backup,
)
from prism.workflow import SCHEMA_VERSION, create_session


def _png_bytes(colour: tuple[int, int, int] = (25, 120, 135)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _image_asset(data: bytes, *, generated: bool = False) -> dict:
    return {
        "id": "generated-image-1" if generated else "document-image-1",
        "origin_type": "ai_generated" if generated else "document",
        "filename": "diagrama.png" if generated else "figura.png",
        "media_type": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "source_file": "geração por IA" if generated else "01_apoio.txt",
        "source_location": "Slide 2" if generated else "Página 1",
        "alt_text": "Diagrama de exemplo" if generated else "Figura documental",
        **build_thumbnail(data),
    }


def _attachment_metadata(items: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in item.items() if key != "data_base64"}
        for item in items
    ]


def _stored_session(service: ApplicationService, tmp_path: Path) -> dict:
    state = create_session(
        CourseInput.create(
            "Introdução à Psicologia",
            "Conceitos, métodos de investigação e teorias psicológicas.",
            isced_f_code="0313",
            isced_f_name="Psicologia",
            general_aims="Compreender a Psicologia e os seus campos de aplicação.",
        )
    )
    source_path = tmp_path / "01_apoio.txt"
    source_path.write_text(
        "Texto integral do documento de apoio para consulta manual.",
        encoding="utf-8",
    )
    state["source_original_text"] = (
        "[Ficheiro: 01_apoio.txt]\nTexto integral do documento de apoio."
    )
    state["learning_outcomes"] = [
        {
            "id": "RA1",
            "statement": "Analisar conceitos fundamentais da Psicologia.",
            "action_verb": "Analisar",
            "taxonomy_level": "Relacional - SOLO 4",
            "outcome_type": "Conhecimentos",
        }
    ]
    state["source_attachments"] = capture_source_attachments([str(source_path)])
    state["source_images"] = [_image_asset(_png_bytes())]
    state["generated_images"] = [_image_asset(_png_bytes((180, 80, 50)), generated=True)]
    state["session_id"] = service.store.save(
        state,
        owner_id=service.owner_id,
    )
    return state


def _legacy_v1_backup(state: dict) -> bytes:
    state_bytes = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest = {
        "format": "coeria-session-backup",
        "format_version": 1,
        "source_session_id": state["session_id"],
        "state_file": LEGACY_BACKUP_STATE_NAME,
        "state_bytes": len(state_bytes),
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            BACKUP_MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        )
        archive.writestr(LEGACY_BACKUP_STATE_NAME, state_bytes)
    return buffer.getvalue()


def test_backup_and_restore_preserve_state_as_a_new_owned_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    original_service = ApplicationService(store, owner_id="D01")
    restore_service = ApplicationService(store, owner_id="D02")
    original = _stored_session(original_service, tmp_path)
    with sqlite3.connect(tmp_path / "coeria.db") as connection:
        stored_before = connection.execute(
            "SELECT updated_at, state_json FROM sessions WHERE session_id = ?",
            (original["session_id"],),
        ).fetchone()
    temporary_paths: list[Path] = []
    real_create_backup = create_session_backup

    def tracked_create_backup(state: dict) -> str:
        path = Path(real_create_backup(state))
        temporary_paths.append(path)
        return str(path)

    monkeypatch.setattr(
        "prism.application_service.create_session_backup",
        tracked_create_backup,
    )
    real_save = store.save

    def reject_source_session_write(*_args, **_kwargs) -> str:
        raise AssertionError("Descarregar o backup não pode chamar store.save().")

    monkeypatch.setattr(store, "save", reject_source_session_write)

    backup_data, backup_filename = original_service.backup_session(
        original["session_id"]
    )
    monkeypatch.setattr(store, "save", real_save)
    restored = restore_service.restore_session_backup(backup_data)
    with sqlite3.connect(tmp_path / "coeria.db") as connection:
        stored_after = connection.execute(
            "SELECT updated_at, state_json FROM sessions WHERE session_id = ?",
            (original["session_id"],),
        ).fetchone()

    assert backup_filename.endswith(".coeria-backup.zip")
    assert stored_after == stored_before
    assert temporary_paths and all(not path.exists() for path in temporary_paths)
    assert restored["session_id"] != original["session_id"]
    assert restored["course"] == original["course"]
    assert restored["source_attachments"] == _attachment_metadata(
        original["source_attachments"]
    )
    assert restored["source_images"] == original["source_images"]
    assert restored["generated_images"] == original["generated_images"]
    assert restored["restored_from_backup"]["source_session_id"] == original["session_id"]
    assert any("cópia de segurança" in item["event"].lower() for item in restored["audit"])
    assert store.load(restored["session_id"], owner_id="D01") is None
    assert store.load(restored["session_id"], owner_id="D02") is not None
    assert store.load(original["session_id"], owner_id="D01") is not None


def test_same_backup_can_be_restored_more_than_once_without_overwriting(
    tmp_path: Path,
) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    original = _stored_session(service, tmp_path)
    backup_data, _ = service.backup_session(original["session_id"])

    first = service.restore_session_backup(backup_data)
    second = service.restore_session_backup(backup_data)

    assert first["session_id"] != second["session_id"]
    assert len(service.list_sessions()) == 3


def test_backup_contains_readable_json_and_real_attachment_files(
    tmp_path: Path,
) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    state = _stored_session(service, tmp_path)
    backed_up = service.load_session(
        state["session_id"],
        include_source_attachments=True,
    )
    backup_data, backup_filename = service.backup_session(state["session_id"])

    decoded, manifest = read_session_backup(backup_data)

    assert backup_filename.endswith(".coeria-backup.zip")
    assert decoded["course"] == backed_up["course"]
    assert decoded["audit"] == backed_up["audit"]
    assert _attachment_metadata(decoded["source_attachments"]) == (
        _attachment_metadata(backed_up["source_attachments"])
    )
    assert decoded["source_attachments"][0]["data_base64"]
    assert manifest["format"] == "coeria-session-backup"
    assert manifest["format_version"] == 2
    assert manifest["source_session_id"] == state["session_id"]
    assert manifest["unit_name"] == "Introdução à Psicologia"
    assert manifest["attachment_count"] == 3
    assert len(manifest["state_sha256"]) == 64

    with zipfile.ZipFile(BytesIO(backup_data), "r") as archive:
        names = set(archive.namelist())
        readable_raw = archive.read(BACKUP_READABLE_STATE_NAME)
        technical_raw = archive.read(BACKUP_STATE_NAME)
        readable = json.loads(readable_raw.decode("utf-8"))
        attachment_index = json.loads(
            archive.read(BACKUP_ATTACHMENT_INDEX_NAME).decode("utf-8")
        )

        assert BACKUP_README_NAME in names
        assert b"\n  \"sobre_esta_copia\"" in readable_raw
        assert readable["unidade_curricular"]["nome_unidade_curricular"] == (
            "Introdução à Psicologia"
        )
        assert readable["unidade_curricular"]["codigo_isced_f"] == "0313"
        assert readable["unidade_curricular"]["area_isced_f"] == "Psicologia"
        assert readable["unidade_curricular"]["objetivos_gerais"] == (
            "Compreender a Psicologia e os seus campos de aplicação."
        )
        assert readable["fontes"]["texto_processado"]
        assert "conteudos_curriculares" in readable["etapas"]
        assert readable["etapas"]["pressupostos_para_resultados_opcionais"] == (
            backed_up["learning_outcome_assumptions"]
        )
        assert readable["etapas"]["resultados_de_aprendizagem"][0][
            "enunciado"
        ] == "Analisar conceitos fundamentais da Psicologia."
        assert "data_base64" not in readable_raw.decode("utf-8")
        assert "thumbnail_base64" not in readable_raw.decode("utf-8")
        assert "data_base64" not in technical_raw.decode("utf-8")
        assert len(attachment_index["anexos"]) == 3

        indexed_paths = {item["ficheiro"] for item in attachment_index["anexos"]}
        assert indexed_paths.issubset(names)
        source_entry = next(
            item
            for item in attachment_index["anexos"]
            if item["categoria"] == "fonte_original"
        )
        assert archive.read(source_entry["ficheiro"]).decode("utf-8") == (
            "Texto integral do documento de apoio para consulta manual."
        )


def test_capture_source_attachments_keeps_original_name_and_bytes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "00_programa UC.txt"
    source_path.write_text("Conteúdo integral legível.", encoding="utf-8")

    captured = capture_source_attachments(str(source_path))

    assert len(captured) == 1
    assert captured[0]["filename"] == "programa UC.txt"
    assert captured[0]["source_file"] == "00_programa UC.txt"
    assert base64.b64decode(captured[0]["data_base64"]) == source_path.read_bytes()
    assert captured[0]["sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_session_creation_and_initial_edit_preserve_then_remove_source_file(
    tmp_path: Path,
) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    source_path = tmp_path / "00_referencia.txt"
    source_path.write_text(
        "Documento de referência integral com conteúdo curricular suficiente.",
        encoding="utf-8",
    )
    form = {
        "unit_name": "Introdução à Psicologia",
        "source_text": (
            "Texto base introduzido diretamente pelo docente para caracterizar "
            "a unidade curricular."
        ),
        "audience": "Licenciatura",
        "program_type": "Licenciatura",
        "duration_hours": 24,
        "taxonomy_type": "SOLO",
        "semester": "1.º semestre",
        "resource_types": ["Apresentação PowerPoint"],
    }

    created = service.start_session(form, [str(source_path)])

    assert len(created["source_attachments"]) == 1
    assert created["source_attachments"][0]["filename"] == "referencia.txt"
    assert "data_base64" not in created["source_attachments"][0]
    created_with_attachments = service.load_session(
        created["session_id"],
        include_source_attachments=True,
    )
    assert base64.b64decode(
        created_with_attachments["source_attachments"][0]["data_base64"]
    ) == source_path.read_bytes()
    with sqlite3.connect(tmp_path / "coeria.db") as connection:
        stored_json = connection.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?",
            (created["session_id"],),
        ).fetchone()[0]
        stored_attachment_count = connection.execute(
            "SELECT COUNT(*) FROM session_attachments WHERE session_id = ?",
            (created["session_id"],),
        ).fetchone()[0]
    assert "data_base64" not in stored_json
    assert stored_attachment_count == 1

    backup_data, _ = service.backup_session(created["session_id"])
    with zipfile.ZipFile(BytesIO(backup_data), "r") as archive:
        source_names = [
            name for name in archive.namelist() if name.startswith("anexos/fontes/")
        ]
        assert len(source_names) == 1
        assert archive.read(source_names[0]) == source_path.read_bytes()

    updated = service.update_session_initial_data(
        created,
        service.restored_initial_fields(created),
        removed_source_files=["00_referencia.txt"],
    )

    assert updated["source_attachments"] == []
    assert "00_referencia.txt" not in updated["source_original_text"]
    with sqlite3.connect(tmp_path / "coeria.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_attachments WHERE session_id = ?",
            (updated["session_id"],),
        ).fetchone()[0] == 0


def test_restore_accepts_legacy_v1_backup(tmp_path: Path) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    original = _stored_session(service, tmp_path)

    restored = service.restore_session_backup(_legacy_v1_backup(original))

    assert restored["session_id"] != original["session_id"]
    assert restored["course"] == original["course"]
    assert restored["source_images"] == original["source_images"]
    assert restored["restored_from_backup"]["format_version"] == 1


def test_restore_rejects_a_tampered_state(tmp_path: Path) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    state = _stored_session(service, tmp_path)
    backup_path = create_session_backup(state)
    with zipfile.ZipFile(backup_path, "r") as archive:
        archived_files = {
            name: archive.read(name)
            for name in archive.namelist()
        }
    session = json.loads(archived_files[BACKUP_STATE_NAME].decode("utf-8"))
    session["course"]["unit_name"] = "Sessão adulterada"
    archived_files[BACKUP_STATE_NAME] = json.dumps(
        session,
        ensure_ascii=False,
    ).encode("utf-8")
    tampered_buffer = BytesIO()
    with zipfile.ZipFile(tampered_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, file_data in archived_files.items():
            archive.writestr(name, file_data)

    with pytest.raises(ValueError, match="dimensão|integridade"):
        service.restore_session_backup(tampered_buffer.getvalue())


@pytest.mark.parametrize("invalid_data", [b"", "não é um zip".encode("utf-8")])
def test_restore_rejects_invalid_files(
    tmp_path: Path,
    invalid_data: bytes,
) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )

    with pytest.raises(ValueError, match="cópia de segurança válida"):
        service.restore_session_backup(invalid_data)


def test_restore_rejects_a_backup_from_a_future_schema(tmp_path: Path) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    state = _stored_session(service, tmp_path)
    state["schema_version"] = SCHEMA_VERSION + 1
    backup_data = Path(create_session_backup(state)).read_bytes()

    with pytest.raises(ValueError, match="versão mais recente"):
        service.restore_session_backup(backup_data)
