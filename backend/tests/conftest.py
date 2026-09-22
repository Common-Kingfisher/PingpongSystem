"""pytest 公共夹具：每个测试使用独立的临时 SQLite 文件。

A2.5 起，公共 ``client`` 会创建并登录一个真实 ``EVENT_ADMIN``；业务路由因此
可以在测试中验证真实的 Bearer 鉴权，而不是增加生产环境旁路。需要匿名请求的
认证专项用例继续使用各自文件内的独立 TestClient。
"""

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import repository as repo
from app.main import app
from app.models import SystemRole
from app.security import hash_password
from app.services import auth as auth_service


TEST_USERNAME = "fixture-event-admin"
TEST_PASSWORD = "StrongPassword123"


@pytest.fixture()
def test_db_path(tmp_path, monkeypatch):
    """让 ``client`` 与 ``conn`` 在同一测试中共享同一个临时数据库。"""
    path = tmp_path / "test.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(path))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    return path


@pytest.fixture()
def client(test_db_path):
    db_module.init_db()
    conn = db_module.connect()
    try:
        user = repo.get_user_by_username(conn, TEST_USERNAME)
        if user is None:
            user = repo.create_user(
                conn,
                TEST_USERNAME,
                "测试赛事管理员",
                hash_password(TEST_PASSWORD),
                SystemRole.EVENT_ADMIN.value,
            )
            conn.commit()
        login = auth_service.login(conn, TEST_USERNAME, TEST_PASSWORD)
    finally:
        conn.close()

    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {login['access_token']}"
        yield test_client


@pytest.fixture()
def conn(test_db_path):
    """直接使用 repository 层所需的连接，与 ``client`` 共享同一数据库。"""
    db_module.init_db()
    connection = db_module.connect()
    yield connection
    connection.close()
