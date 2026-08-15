from pathlib import Path
import sqlite3

import pytest

from prism.persistence import SQLiteSessionStore


def test_default_database_path_can_be_configured_from_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configured_path = tmp_path / "coeria.db"
    monkeypatch.setenv("COERIA_DATABASE_PATH", str(configured_path))

    store = SQLiteSessionStore()

    assert store.database_path == configured_path
    assert configured_path.is_file()


def test_explicit_database_path_has_priority_over_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configured_path = tmp_path / "configured.db"
    explicit_path = tmp_path / "explicit.db"
    monkeypatch.setenv("COERIA_DATABASE_PATH", str(configured_path))

    store = SQLiteSessionStore(explicit_path)

    assert store.database_path == explicit_path
    assert explicit_path.is_file()
    assert not configured_path.exists()


def _minimal_state(title: str) -> dict:
    return {
        "course": {"unit_name": title},
        "current_stage": "contents",
        "status": "in_progress",
        "audit": [],
    }


def test_sessions_are_isolated_by_owner(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    first_id = store.save(_minimal_state("UC A"), owner_id="D01")
    second_id = store.save(_minimal_state("UC B"), owner_id="D02")

    assert [item["session_id"] for item in store.list_sessions(owner_id="D01")] == [
        first_id
    ]
    assert [item["session_id"] for item in store.list_sessions(owner_id="D02")] == [
        second_id
    ]
    assert store.load(first_id, owner_id="D02") is None
    assert store.load(first_id, owner_id="D01")["course"]["unit_name"] == "UC A"


def test_session_cannot_be_overwritten_by_another_owner(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "coeria.db")
    session_id = store.save(_minimal_state("UC A"), owner_id="D01")

    with pytest.raises(PermissionError):
        store.save(
            _minimal_state("Intrusão"),
            session_id=session_id,
            owner_id="D02",
        )

    assert store.load(session_id, owner_id="D01")["course"]["unit_name"] == "UC A"


def test_legacy_database_is_migrated_to_a_reserved_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                state_json TEXT NOT NULL
            );
            CREATE TABLE audit_events (
                session_id TEXT NOT NULL,
                event_index INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                stage TEXT NOT NULL,
                event TEXT NOT NULL,
                feedback TEXT NOT NULL,
                PRIMARY KEY (session_id, event_index),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            INSERT INTO sessions(session_id, updated_at, state_json)
            VALUES (
                'old-session',
                '2026-01-01 00:00:00 UTC',
                '{"course": {"unit_name": "Sessão antiga"}, "audit": []}'
            );
            """
        )

    store = SQLiteSessionStore(database_path)

    assert store.load("old-session", owner_id="D01") is None
    assert store.load("old-session", owner_id="LEGACY") is not None
