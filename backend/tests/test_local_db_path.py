import os
from pathlib import Path

from app.core import local_demo_db


def test_db_path_is_resolved_from_backend_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(local_demo_db.settings, "LOCAL_DB_PATH", "detomsite_local.db")
    monkeypatch.chdir(tmp_path)

    expected = (Path(local_demo_db.__file__).resolve().parents[2] / "detomsite_local.db").resolve()

    assert local_demo_db._db_path() == expected
