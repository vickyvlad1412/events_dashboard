import shutil

import pytest

import app.db


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "template.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app.db, "DB_PATH", path)
        app.db.init_db()
        app.db.migrate_add_external_columns()
        app.db.migrate_add_watch_history_columns()
    return path


@pytest.fixture
def temp_db(template_db, tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    shutil.copy(template_db, path)
    monkeypatch.setattr(app.db, "DB_PATH", path)
