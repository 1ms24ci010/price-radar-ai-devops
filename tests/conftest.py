import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import pytest

# Import the application module
import app as app_module

os.environ["DATABASE_PATH"] = str(Path.cwd() / "test_database.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Give every test its own isolated SQLite database
    test_db = tmp_path / "price_radar_test.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(test_db))

    app_module.app.config.update(TESTING=True)
    app_module.init_db()

    with app_module.app.test_client() as test_client:
        yield test_client