"""Export the current FastAPI contract for frontend/team consumption."""

import json
from pathlib import Path

from app.main import app


target = Path(__file__).resolve().parent.parent / "docs" / "openapi-v0.2.json"
target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(target)
