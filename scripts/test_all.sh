#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================="
echo "  SumaiGuard Agent — Test Suite"
echo "========================================="

echo ""
echo "1/5: Running backend tests..."
python3 -m pytest apps/sumai_agent/tests -v

echo ""
echo "2/5: Running verified candidate promotion gate tests..."
python3 -m pytest scripts/test_promote_verified_candidate.py -v

echo ""
echo "3/5: Running deployment entrypoint tests..."
python3 -m pytest scripts/test_deployment_entrypoints.py -v

echo ""
echo "4/5: Checking frontend import..."
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
echo "5/5: Validating docker compose config..."
docker compose config > /dev/null
echo "docker compose config ok"

echo ""
echo "========================================="
echo "  All tests passed ✅"
echo "========================================="
