"""Patch P-01：部署路径配置兼容边界。"""

from __future__ import annotations

from app import db as db_module


def test_pingpong_db_path_is_preferred(monkeypatch, tmp_path):
    preferred = tmp_path / "p01.db"
    legacy = tmp_path / "legacy.db"
    monkeypatch.setenv("PINGPONG_DB_PATH", str(preferred))
    monkeypatch.setenv("DEMO_DB_PATH", str(legacy))

    assert db_module._db_path() == preferred


def test_demo_db_path_legacy_name_remains_supported(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.db"
    monkeypatch.delenv("PINGPONG_DB_PATH", raising=False)
    monkeypatch.setenv("DEMO_DB_PATH", str(legacy))

    assert db_module._db_path() == legacy
