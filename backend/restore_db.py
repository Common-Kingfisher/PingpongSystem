r"""D6A 停服恢复运维入口。

示例：
    python restore_db.py D:\backups\pingpong-backup-20260923-180000.db --service-stopped
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.services.database_backup import DatabaseRestoreError, restore_database


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线恢复 SQLite 数据库")
    parser.add_argument("backup", type=Path, help="待恢复的备份文件")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="目标数据库路径；省略时读取 PINGPONG_DB_PATH / DEMO_DB_PATH / 默认路径",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="pre-restore 备份目录；省略时使用 <数据库目录>/backups/",
    )
    parser.add_argument(
        "--service-stopped",
        action="store_true",
        help="确认应用服务已经完全停止；未提供时拒绝恢复",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.service_stopped:
        print("恢复失败：必须停止应用服务并显式提供 --service-stopped")
        return 2

    try:
        result = restore_database(
            args.backup,
            args.database,
            args.backup_dir,
            service_stopped=True,
        )
    except DatabaseRestoreError as exc:
        print(f"恢复失败：{exc}")
        return 1

    print(f"恢复成功：{result.target_path}")
    print(f"来源备份：{result.backup_path}")
    print(f"恢复前备份：{result.pre_restore_backup_path or '目标库原先不存在'}")
    print(f"integrity_check：{', '.join(result.integrity_check)}")
    print(f"foreign_key_check：{result.foreign_key_violations} 条违规")
    print(f"schema_migrations：{result.schema_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
