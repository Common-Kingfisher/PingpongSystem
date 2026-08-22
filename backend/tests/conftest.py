"""pytest 公共夹具：每个测试使用独立的临时 SQLite 文件。"""

import os

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """直接使用 repository 层所需的连接。"""
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "repo.db"))
    db_module.init_db()
    conn = db_module.connect()
    yield conn
    conn.close()
