"""Export the current FastAPI contract for frontend/team consumption.

用法：
    python export_openapi.py            # 写入（覆盖）docs/openapi-v0.2.json
    python export_openapi.py --check    # 只校验快照是否与当前 app.openapi() 一致，不写文件
"""

import json
import sys
from pathlib import Path

from app.main import app


def _dump() -> str:
    """当前 FastAPI 契约的规范化 JSON 字符串。"""
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2)


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "docs" / "openapi-v0.2.json"
    current = _dump()
    if "--check" in sys.argv:
        if not target.exists():
            print("OpenAPI snapshot is stale (missing file)")
            return 1
        if target.read_text(encoding="utf-8") != current:
            print("OpenAPI snapshot is stale")
            return 1
        print("OpenAPI snapshot is up to date")
        return 0
    target.write_text(current, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
