r"""D6A 数据库备份运维入口。

示例：
    python backup_db.py
    python backup_db.py --database D:\pingpong\demo.db --backup-dir D:\backups
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.services.database_backup import DatabaseBackupError, backup_database


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成经过校验的 SQLite 数据库备份")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="源数据库路径；省略时读取 PINGPONG_DB_PATH / DEMO_DB_PATH / 默认路径",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="备份目录；省略时使用 <数据库目录>/backups/",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = backup_database(args.database, args.backup_dir)
    except DatabaseBackupError as exc:
        print(f"备份失败：{exc}")
        return 1

    print(f"备份成功：{result.backup_path}")
    print(f"源数据库：{result.source_path}")
    print(f"integrity_check：{', '.join(result.integrity_check)}")
    print(f"foreign_key_check：{result.foreign_key_violations} 条违规")
    print(f"schema_migrations：{result.schema_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
