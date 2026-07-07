#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python -m pytest apps/sumai_agent/tests
python - <<'PY'
import importlib.util
from pathlib import Path

path = Path("apps/sumai_web/app.py")
spec = importlib.util.spec_from_file_location("sumai_web_app", path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
print("frontend import ok")
PY
