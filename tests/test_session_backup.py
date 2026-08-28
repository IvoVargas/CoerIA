from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from prism.application_service import ApplicationService
from prism.models import CourseInput
from prism.persistence import SQLiteSessionStore
from prism.session_backup import (
    BACKUP_MANIFEST_NAME,
    BACKUP_STATE_NAME,
    create_session_backup,
    read_session_backup,
)
from prism.workflow import SCHEMA_VERSION, create_session


def _stored_session(service: ApplicationService) -> dict:
    state = create_session(
        CourseInput.create(
            "Introdução à Psicologia",
            "Conceitos, métodos de investigação e teorias psicológicas.",
        )
    )
    state["source_images"] = [
        {
            "id": "document-image-1",
            "data_url": "data:image/png;base64,aW1hZ2Vt",
            "source_file": "apoio.pdf",
        }
    ]
    state["session_id"] = service.store.save(
        state,
        owner_id=service.owner_id,
    )
    return state


def test_backup_and_restore_preserve_state_as_a_new_owned_session(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    original_service = ApplicationService(store, owner_id="D01")
    restore_service = ApplicationService(store, owner_id="D02")
    original = _stored_session(original_service)

    backup_path, backed_up = original_service.backup_session(
        original["session_id"]
    )
    backup_data = Path(backup_path).read_bytes()
    restored = restore_service.restore_session_backup(backup_data)

    assert backed_up["session_id"] == original["session_id"]
    assert restored["session_id"] != original["session_id"]
    assert restored["course"] == original["course"]
    assert restored["source_images"] == original["source_images"]
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
    original = _stored_session(service)
    backup_path, _ = service.backup_session(original["session_id"])
    backup_data = Path(backup_path).read_bytes()

    first = service.restore_session_backup(backup_data)
    second = service.restore_session_backup(backup_data)

    assert first["session_id"] != second["session_id"]
    assert len(service.list_sessions()) == 3


def test_backup_manifest_and_checksum_describe_the_complete_state(
    tmp_path: Path,
) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    state = _stored_session(service)
    backup_path, backed_up = service.backup_session(state["session_id"])

    decoded, manifest = read_session_backup(Path(backup_path).read_bytes())

    assert decoded == backed_up
    assert manifest["format"] == "coeria-session-backup"
    assert manifest["format_version"] == 1
    assert manifest["source_session_id"] == state["session_id"]
    assert manifest["unit_name"] == "Introdução à Psicologia"
    assert len(manifest["state_sha256"]) == 64


def test_restore_rejects_a_tampered_state(tmp_path: Path) -> None:
    service = ApplicationService(
        SQLiteSessionStore(tmp_path / "coeria.db"),
        owner_id="D01",
    )
    state = _stored_session(service)
    backup_path = create_session_backup(state)
    with zipfile.ZipFile(backup_path, "r") as archive:
        manifest = archive.read(BACKUP_MANIFEST_NAME)
        session = json.loads(archive.read(BACKUP_STATE_NAME).decode("utf-8"))
    session["course"]["unit_name"] = "Sessão adulterada"
    tampered_buffer = BytesIO()
    with zipfile.ZipFile(tampered_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BACKUP_MANIFEST_NAME, manifest)
        archive.writestr(
            BACKUP_STATE_NAME,
            json.dumps(session, ensure_ascii=False).encode("utf-8"),
        )

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
    state = _stored_session(service)
    state["schema_version"] = SCHEMA_VERSION + 1
    backup_data = Path(create_session_backup(state)).read_bytes()

    with pytest.raises(ValueError, match="versão mais recente"):
        service.restore_session_backup(backup_data)
