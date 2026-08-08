#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================="
echo "  SumaiGuard Agent — Test Suite"
echo "========================================="

echo ""
echo "1/4: Running backend tests..."
python3 -m pytest apps/sumai_agent/tests -v

echo ""
echo "2/4: Running verified candidate promotion gate tests..."
python3 -m pytest scripts/test_promote_verified_candidate.py -v

echo ""
echo "3/4: Checking frontend import..."
python3 -c "
import importlib.util
from pathlib import Path

path = Path('apps/sumai_web/app.py')
spec = importlib.util.spec_from_file_location('sumai_web_app', path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
print('frontend import ok')
"

echo ""
echo "4/4: Validating docker compose config..."
docker compose config > /dev/null
echo "docker compose config ok"

echo ""
echo "========================================="
echo "  All tests passed ✅"
echo "========================================="
