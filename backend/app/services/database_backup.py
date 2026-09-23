"""SQLite 数据库级备份与停服恢复。

本模块只提供运维能力，不暴露 HTTP API。备份使用 SQLite 在线 backup API，
恢复使用“同目录临时库校验、迁移、原子替换”的离线流程。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .. import db as db_module
from ..migrations import MIGRATIONS


SCHEMA_VERSION = max(version for version, _, _ in MIGRATIONS)

# 备份文件必须至少具备这些表，才能被视为可恢复的业务快照。
CORE_TABLES = (
    "schema_migrations",
    "users",
    "tournaments",
    "entries",
    "matches",
)

# 恢复并执行当前 migration 后，所有当前版本业务表都必须存在。
REQUIRED_TABLES = CORE_TABLES + (
    "system_state",
    "user_sessions",
    "tournament_admins",
    "registrations",
    "organizations",
    "venues",
    "players",
    "entry_members",
    "groups",
    "tables",
    "match_games",
    "score_requests",
    "score_audits",
    "qualification_decisions",
    "team_qualifications",
    "team_ties",
    "team_rubbers",
)

_VERSION_5_ADDED_TABLES = ("registrations", "organizations", "venues")


class DatabaseBackupError(RuntimeError):
    """备份或备份校验失败。"""


class DatabaseRestoreError(RuntimeError):
    """恢复或恢复校验失败。"""


@dataclass(frozen=True)
class DatabaseVerification:
    integrity_check: tuple[str, ...]
    foreign_key_violations: int
    schema_version: int | None


@dataclass(frozen=True)
class BackupResult:
    source_path: Path
    backup_path: Path
    integrity_check: tuple[str, ...]
    foreign_key_violations: int
    schema_version: int | None


@dataclass(frozen=True)
class RestoreResult:
    target_path: Path
    backup_path: Path
    pre_restore_backup_path: Path | None
    integrity_check: tuple[str, ...]
    foreign_key_violations: int
    schema_version: int | None


_ENV_LOCK = threading.Lock()


def _resolve_database_path(database_path: str | Path | None) -> Path:
    if database_path is None:
        return Path(db_module._db_path())
    return Path(database_path)


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _unique_backup_path(directory: Path, timestamp: datetime | None) -> Path:
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"pingpong-backup-{stamp}.db"
    index = 1
    while candidate.exists():
        candidate = directory / f"pingpong-backup-{stamp}-{index:02d}.db"
        index += 1
    return candidate


def _sqlite_uri(path: Path, *, mode: str = "rw") -> str:
    """为 Windows 路径生成 SQLite URI，避免手工拼接磁盘盘符。"""
    return f"{path.resolve().as_uri()}?mode={mode}"


def _connect(path: Path, *, mode: str = "rw") -> sqlite3.Connection:
    return sqlite3.connect(
        _sqlite_uri(path, mode=mode),
        uri=True,
        timeout=5,
    )


def _required_tables_for_backup(schema_version: int | None) -> tuple[str, ...]:
    """按源库 migration 版本选择备份快照必须包含的表。"""
    if schema_version is None:
        raise DatabaseBackupError("数据库未记录 migration 版本，拒绝生成不可验证的备份")
    if schema_version > SCHEMA_VERSION:
        raise DatabaseBackupError(
            f"数据库 migration 版本高于当前程序支持版本: {schema_version} > {SCHEMA_VERSION}"
        )
    if schema_version < 2:
        raise DatabaseBackupError(
            f"数据库 migration 版本过旧: {schema_version}；当前只支持 v2-v{SCHEMA_VERSION} 备份"
        )
    if schema_version == SCHEMA_VERSION:
        return REQUIRED_TABLES

    legacy_required = tuple(
        table for table in REQUIRED_TABLES if table not in _VERSION_5_ADDED_TABLES
    )
    if schema_version < 3:
        legacy_required = tuple(
            table for table in legacy_required if table != "system_state"
        )
    return legacy_required


def _verify_database(
    path: Path,
    *,
    required_tables: tuple[str, ...] = CORE_TABLES,
    require_current_version: bool = False,
    allow_legacy_schema: bool = False,
) -> DatabaseVerification:
    if not path.is_file():
        raise DatabaseBackupError(f"数据库文件不存在: {path}")

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(path, mode="ro")
        integrity_rows = tuple(
            str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()
        )
        if integrity_rows != ("ok",):
            raise DatabaseBackupError(
                f"数据库 integrity_check 未通过: {path} -> {integrity_rows[:3]}"
            )

        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_rows:
            raise DatabaseBackupError(
                f"数据库 foreign_key_check 未通过: {path} -> "
                f"{len(foreign_key_rows)} 条违规"
            )

        version_row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        schema_version = int(version_row[0]) if version_row and version_row[0] is not None else None

        effective_required_tables = (
            _required_tables_for_backup(schema_version)
            if allow_legacy_schema
            else required_tables
        )
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        table_names = {str(row[0]) for row in table_rows}
        missing = sorted(set(effective_required_tables) - table_names)
        if missing:
            raise DatabaseBackupError(
                f"数据库缺少关键表: {path} -> {', '.join(missing)}"
            )

        if require_current_version and schema_version != SCHEMA_VERSION:
            raise DatabaseBackupError(
                f"数据库 migration 版本不正确: {path} -> "
                f"当前 {schema_version}，期望 {SCHEMA_VERSION}"
            )
        return DatabaseVerification(
            integrity_check=integrity_rows,
            foreign_key_violations=len(foreign_key_rows),
            schema_version=schema_version,
        )
    except DatabaseBackupError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseBackupError(f"数据库校验失败: {path} -> {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _copy_with_sqlite_backup(source_path: Path, destination_path: Path) -> None:
    """用 SQLite backup API 生成一致快照，禁止直接复制运行中的主库文件。"""
    if source_path.resolve() == destination_path.resolve():
        raise DatabaseBackupError("源数据库和目标数据库不能是同一个文件")
    if not source_path.is_file():
        raise DatabaseBackupError(f"源数据库不存在: {source_path}")
    if destination_path.exists():
        raise DatabaseBackupError(f"目标文件已存在: {destination_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = _connect(source_path, mode="ro")
        destination = _connect(destination_path, mode="rwc")
        source.backup(destination)
        destination.commit()
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseBackupError(
            f"SQLite backup 失败: {source_path} -> {destination_path} -> {exc}"
        ) from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def backup_database(
    source_db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    *,
    timestamp: datetime | None = None,
) -> BackupResult:
    """生成经过完整性和外键检查的数据库快照。"""
    source_path = _resolve_database_path(source_db_path)
    if not source_path.is_file():
        raise DatabaseBackupError(f"源数据库不存在: {source_path}")

    target_dir = (
        Path(backup_dir)
        if backup_dir is not None
        else source_path.parent / "backups"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = _unique_backup_path(target_dir, timestamp)
    temporary_path = target_dir / f".{final_path.name}.{uuid4().hex}.tmp"

    try:
        _copy_with_sqlite_backup(source_path, temporary_path)
        # legacy 库按自身 migration 版本校验；恢复时先迁移再按当前版本全表校验。
        verification = _verify_database(
            temporary_path,
            allow_legacy_schema=True,
        )
        os.replace(temporary_path, final_path)
    except DatabaseBackupError:
        _remove_file(temporary_path)
        raise
    except OSError as exc:
        _remove_file(temporary_path)
        raise DatabaseBackupError(f"备份文件写入失败: {final_path} -> {exc}") from exc

    return BackupResult(
        source_path=source_path,
        backup_path=final_path,
        integrity_check=verification.integrity_check,
        foreign_key_violations=verification.foreign_key_violations,
        schema_version=verification.schema_version,
    )


def _initialize_database_path(database_path: Path) -> None:
    """在不修改全局配置的情况下，让 ``init_db`` 初始化指定数据库文件。"""
    with _ENV_LOCK:
        primary_name = "PINGPONG_DB_PATH"
        legacy_name = "DEMO_DB_PATH"
        original_primary = os.environ.get(primary_name)
        original_legacy = os.environ.get(legacy_name)
        os.environ[primary_name] = str(database_path)
        os.environ.pop(legacy_name, None)
        try:
            db_module.init_db()
        finally:
            if original_primary is None:
                os.environ.pop(primary_name, None)
            else:
                os.environ[primary_name] = original_primary
            if original_legacy is None:
                os.environ.pop(legacy_name, None)
            else:
                os.environ[legacy_name] = original_legacy


def _assert_no_sidecars(database_path: Path) -> None:
    sidecars = [
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        Path(f"{database_path}-journal"),
    ]
    existing = [path for path in sidecars if path.exists()]
    if existing:
        names = ", ".join(str(path) for path in existing)
        raise DatabaseRestoreError(
            "检测到目标数据库仍有 SQLite 临时文件，说明服务可能未干净停止；"
            f"为避免覆盖未落盘数据，拒绝恢复。请检查并清理: {names}"
        )


def _restore_previous_database(previous_backup: Path, target_path: Path) -> None:
    rollback_path = target_path.with_name(
        f".{target_path.name}.rollback-{uuid4().hex}.tmp"
    )
    try:
        _copy_with_sqlite_backup(previous_backup, rollback_path)
        _verify_database(
            rollback_path,
            required_tables=REQUIRED_TABLES,
            require_current_version=True,
        )
        os.replace(rollback_path, target_path)
    finally:
        _remove_file(rollback_path)


def restore_database(
    backup_path: str | Path,
    database_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    *,
    service_stopped: bool = False,
) -> RestoreResult:
    """离线恢复数据库；恢复失败时尽量保留调用前的目标数据库。"""
    if not service_stopped:
        raise DatabaseRestoreError("恢复前必须停止服务，并显式确认 service_stopped=True")

    source_path = Path(backup_path)
    target_path = _resolve_database_path(database_path)
    if source_path.resolve() == target_path.resolve():
        raise DatabaseRestoreError("备份文件和目标数据库不能是同一个文件")
    if not source_path.is_file():
        raise DatabaseRestoreError(f"备份文件不存在: {source_path}")

    try:
        _verify_database(source_path)
    except DatabaseBackupError as exc:
        raise DatabaseRestoreError(str(exc)) from exc

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_sidecars(target_path)

    pre_restore_backup_path: Path | None = None
    if target_path.exists():
        try:
            pre_restore_backup_path = backup_database(
                source_db_path=target_path,
                backup_dir=backup_dir,
            ).backup_path
        except DatabaseBackupError as exc:
            raise DatabaseRestoreError(
                f"恢复前备份当前数据库失败，已中止以避免覆盖原库: {exc}"
            ) from exc

    temporary_path = target_path.with_name(
        f".{target_path.name}.restore-{uuid4().hex}.tmp"
    )
    try:
        _copy_with_sqlite_backup(source_path, temporary_path)
        _verify_database(temporary_path)
        _initialize_database_path(temporary_path)
        verification = _verify_database(
            temporary_path,
            required_tables=REQUIRED_TABLES,
            require_current_version=True,
        )

        # 临时库已经通过完整性、外键和当前 migration 检查，才允许替换正式库。
        os.replace(temporary_path, target_path)
        try:
            final_verification = _verify_database(
                target_path,
                required_tables=REQUIRED_TABLES,
                require_current_version=True,
            )
        except DatabaseBackupError as exc:
            if pre_restore_backup_path is not None:
                _restore_previous_database(pre_restore_backup_path, target_path)
            else:
                _remove_file(target_path)
            raise DatabaseRestoreError(
                f"原子替换后的数据库校验失败，已中止恢复: {exc}"
            ) from exc
    except DatabaseBackupError as exc:
        _remove_file(temporary_path)
        raise DatabaseRestoreError(str(exc)) from exc
    except OSError as exc:
        _remove_file(temporary_path)
        raise DatabaseRestoreError(f"恢复文件替换失败，原数据库保持不变: {exc}") from exc
    finally:
        _remove_file(temporary_path)

    return RestoreResult(
        target_path=target_path,
        backup_path=source_path,
        pre_restore_backup_path=pre_restore_backup_path,
        integrity_check=final_verification.integrity_check,
        foreign_key_violations=final_verification.foreign_key_violations,
        schema_version=final_verification.schema_version,
    )
