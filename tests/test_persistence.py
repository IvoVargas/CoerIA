from pathlib import Path
from tempfile import TemporaryDirectory

from prism.persistence import SQLiteSessionStore


def test_default_database_path_can_be_configured_from_environment(
    monkeypatch,
) -> None:
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
        configured_path = Path(temporary) / "coeria.db"
        monkeypatch.setenv("COERIA_DATABASE_PATH", str(configured_path))

        store = SQLiteSessionStore()

        assert store.database_path == configured_path
        assert configured_path.is_file()


def test_explicit_database_path_has_priority_over_environment(
    monkeypatch,
) -> None:
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
        temporary_path = Path(temporary)
        configured_path = temporary_path / "configured.db"
        explicit_path = temporary_path / "explicit.db"
        monkeypatch.setenv("COERIA_DATABASE_PATH", str(configured_path))

        store = SQLiteSessionStore(explicit_path)

        assert store.database_path == explicit_path
        assert explicit_path.is_file()
        assert not configured_path.exists()
