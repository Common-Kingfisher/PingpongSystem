"""D2 A2.2：原子 Bootstrap 与恢复状态。"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import db as db_module
from app import repository as repo
from app.models import BootstrapStatus
from app.services import auth as auth_service


PASSWORD = "InitialAdmin123"


def _bootstrap(conn, username="system-admin"):
    return auth_service.bootstrap(
        conn,
        username=username,
        display_name="系统管理员",
        password=PASSWORD,
        phone="13900000000",
        note="首次初始化",
    )


def test_empty_database_can_only_bootstrap_once(conn, monkeypatch):
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    assert auth_service.get_bootstrap_status(conn) == (
        BootstrapStatus.NEEDS_INITIALIZATION.value
    )

    user = _bootstrap(conn)

    assert user["system_role"] == "SYSTEM_ADMIN"
    stored = repo.get_user_by_username(conn, "system-admin")
    assert stored["phone"] == "13900000000"
    assert stored["note"] == "首次初始化"
    assert repo.get_bootstrap_completed(conn) is True
    assert auth_service.get_bootstrap_status(conn) == BootstrapStatus.READY.value

    with pytest.raises(auth_service.AuthError) as exc_info:
        _bootstrap(conn, username="second-admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "BOOTSTRAP_ALREADY_COMPLETED"
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_completed_database_requires_recovery_when_no_active_admin(conn, monkeypatch):
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    user = _bootstrap(conn)
    auth_service.set_user_active(conn, user_id=user["id"], active=False)

    assert auth_service.get_bootstrap_status(conn) == (
        BootstrapStatus.RECOVERY_REQUIRED.value
    )
    with pytest.raises(auth_service.AuthError) as exc_info:
        _bootstrap(conn, username="forbidden-rebootstrap")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "RECOVERY_REQUIRED"
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_restart_and_backup_restore_do_not_reopen_bootstrap(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    original = tmp_path / "initialized.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(original))
    db_module.init_db()

    conn = db_module.connect()
    try:
        _bootstrap(conn)
    finally:
        conn.close()

    db_module.init_db()
    conn = db_module.connect()
    try:
        assert auth_service.get_bootstrap_status(conn) == BootstrapStatus.READY.value
    finally:
        conn.close()

    restored = tmp_path / "restored.db"
    shutil.copy2(original, restored)
    monkeypatch.setenv("DEMO_DB_PATH", str(restored))
    db_module.init_db()

    conn = db_module.connect()
    try:
        assert repo.get_bootstrap_completed(conn) is True
        assert auth_service.get_bootstrap_status(conn) == BootstrapStatus.READY.value
    finally:
        conn.close()


def test_concurrent_bootstrap_only_creates_one_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "concurrent.db"))
    db_module.init_db()

    barrier = Barrier(2)

    def worker(username: str) -> str:
        local_conn = db_module.connect()
        try:
            barrier.wait(timeout=5)
            _bootstrap(local_conn, username=username)
            return "ok"
        except auth_service.AuthError as exc:
            return exc.code
        finally:
            local_conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(worker, ["concurrent-admin-a", "concurrent-admin-b"])
        )

    assert sorted(results) == ["BOOTSTRAP_ALREADY_COMPLETED", "ok"]
    conn = db_module.connect()
    try:
        assert repo.get_bootstrap_completed(conn) is True
        assert conn.execute(
            "SELECT COUNT(*) FROM users WHERE system_role = 'SYSTEM_ADMIN'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
